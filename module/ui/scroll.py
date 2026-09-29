import numpy as np
from scipy import signal

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import color_similarity_2d, random_rectangle_point, rgb2gray
from module.logger import logger

# ---------------------------------------------------------------------------
# Scroll drive flow (B2b): `set` loop as flow data (returns dragged count).
# ---------------------------------------------------------------------------


def _scroll_done(ctx, args=None, **kw):
    scroll = (args or {}).get("scroll")
    position = (args or {}).get("position")
    current = scroll.cal_position(ctx.owner)
    if abs(position - current) < scroll.drag_threshold:
        return True
    ctx.params["_scroll_current"] = current
    if scroll.length:
        scroll.drag_timeout.reset()
        ctx.params["_scroll_skip"] = False
    else:
        if scroll.drag_timeout.reached():
            logger.warning("Scroll disappeared, assume scroll set")
            return True
        ctx.params["_scroll_skip"] = True
    return False


def _scroll_click_ready(ctx, args=None, **kw):
    if ctx.params.get("_scroll_skip"):
        ctx.params["_scroll_skip"] = False
        return False
    return (args or {}).get("scroll").drag_interval.reached()


def _scroll_click(ctx, args=None, **kw):
    scroll = (args or {}).get("scroll")
    position = (args or {}).get("position")
    random_range = (args or {}).get("random_range")
    distance_check = (args or {}).get("distance_check", True)
    current = ctx.params["_scroll_current"]
    p1 = random_rectangle_point(scroll.position_to_screen(current), n=1)
    p2 = random_rectangle_point(scroll.position_to_screen(position, random_range=random_range), n=1)
    ctx.owner.device.swipe(p1, p2, name=scroll.name, distance_check=distance_check)
    scroll.drag_interval.reset()
    ctx.params["_dragged"] = ctx.params.get("_dragged", 0) + 1
    return True


def _scroll_set_flow(scroll: "Scroll", position: float, random_range, distance_check: bool) -> dict:
    return {
        "name": "scroll_set",
        "entry": "s",
        "states": {
            "s": {
                "exit": {"check": {"custom": _scroll_done, "args": {
                    "scroll": scroll, "position": position}},
                    "on_success": {"exit": {"__var__": "_dragged"}}},
                "rules": [
                    {"name": "drag", "check": {"custom": _scroll_click_ready, "args": {"scroll": scroll}},
                     "action": {"call": _scroll_click, "args": {
                         "scroll": scroll, "position": position,
                         "random_range": random_range, "distance_check": distance_check}}},
                ],
            },
        },
    }


class Scroll:
    color_threshold = 221
    drag_threshold = 0.05
    edge_threshold = 0.05
    edge_add = (0.3, 0.5)

    def __init__(self, area, color, is_vertical=True, name="Scroll"):
        """
        Args:
            area (Button, tuple): A button or area of the whole scroll.
            color (tuple): RGB of the scroll
            is_vertical (bool): True if vertical, false if horizontal.
            name (str):
        """
        if isinstance(area, Button):
            name = area.name
            area = area.area
        self.area = area
        self.color = color
        self.is_vertical = is_vertical
        self.name = name

        if self.is_vertical:
            self.total = self.area[3] - self.area[1]
        else:
            self.total = self.area[2] - self.area[0]
        # Just default value, will change in match_color()
        self.length = self.total / 2
        self.drag_interval = Timer(1, count=2)
        self.drag_timeout = Timer(5, count=10)

    def match_color(self, main):
        """
        Args:
            main (ModuleBase):

        Returns:
            np.ndarray: Shape (n,), dtype bool.
        """
        image = main.image_crop(self.area, copy=False)
        image = color_similarity_2d(image, color=self.color)
        mask = np.max(image, axis=1 if self.is_vertical else 0) > self.color_threshold
        self.length = np.sum(mask)
        return mask

    def cal_position(self, main):
        """
        Args:
            main (ModuleBase):

        Returns:
            float: 0 to 1.
        """
        mask = self.match_color(main)
        middle = np.mean(np.where(mask)[0])

        position = (middle - self.length / 2) / (self.total - self.length)
        position = position if position > 0 else 0.0
        position = position if position < 1 else 1.0
        logger.attr(self.name, f"{position:.2f} ({middle}-{self.length / 2})/({self.total}-{self.length})")
        return position

    def position_to_screen(self, position, random_range=(-0.05, 0.05)):
        """
        Convert scroll position to screen coordinates.
        Call cal_position() or match_color() to get length, before calling this.

        Args:
            position (int, float):
            random_range (tuple):

        Returns:
            tuple[int]: (upper_left_x, upper_left_y, bottom_right_x, bottom_right_y)
        """
        position = np.add(position, random_range)
        middle = position * (self.total - self.length) + self.length / 2
        middle = middle.astype(int)
        if self.is_vertical:
            middle += self.area[1]
            while np.max(middle) >= 720:
                middle -= 2
            while np.min(middle) <= 0:
                middle += 2
            area = (self.area[0], middle[0], self.area[2], middle[1])
        else:
            middle += self.area[0]
            while np.max(middle) >= 1280:
                middle -= 2
            while np.min(middle) <= 0:
                middle += 2
            area = (middle[0], self.area[1], middle[1], self.area[3])
        return area

    def appear(self, main):
        """
        Args:
            main (ModuleBase):

        Returns:
            bool
        """
        return np.mean(self.match_color(main)) > 0.1

    def at_top(self, main):
        return self.cal_position(main) < self.edge_threshold

    def at_bottom(self, main):
        return self.cal_position(main) > 1 - self.edge_threshold

    def set(self, position, main, random_range=(-0.05, 0.05), distance_check=True, skip_first_screenshot=True):
        """
        Set scroll to a specific position.

        Args:
            position (float, int): 0 to 1.
            main (ModuleBase):
            random_range (tuple(int, float)):
            distance_check (bool): Whether to drop short swipes
            skip_first_screenshot:

        Returns:
            bool: If dragged.
        """
        logger.info(f"{self.name} set to {position}")
        self.drag_interval.clear()
        self.drag_timeout.reset()
        if position <= self.edge_threshold:
            random_range = np.subtract(0, self.edge_add)
        if position >= 1 - self.edge_threshold:
            random_range = self.edge_add

        from module.flow.runtime import run_flow

        return run_flow(
            _scroll_set_flow(self, position, random_range, distance_check), owner=main,
            skip_first=skip_first_screenshot, params={"_dragged": 0},
        )

    def set_top(self, main, random_range=(-0.05, 0.05), skip_first_screenshot=True):
        return self.set(0.00, main=main, random_range=random_range, skip_first_screenshot=skip_first_screenshot)

    def set_bottom(self, main, random_range=(-0.05, 0.05), skip_first_screenshot=True):
        return self.set(1.00, main=main, random_range=random_range, skip_first_screenshot=skip_first_screenshot)

    def drag_page(self, page, main, random_range=(-0.05, 0.05), skip_first_screenshot=True):
        """
        Drag scroll forward or backward.

        Args:
            page (int, float): Relative position to drag. 1.0 means next page, -1.0 means previous page.
            main (ModuleBase):
            random_range (tuple[float]):
            skip_first_screenshot:
        """
        if not skip_first_screenshot:
            main.device.screenshot()
        current = self.cal_position(main)

        multiply = self.length / (self.total - self.length)
        target = current + page * multiply
        target = round(min(max(target, 0), 1), 3)
        return self.set(target, main=main, random_range=random_range, skip_first_screenshot=True)

    def next_page(self, main, page=0.8, random_range=(-0.01, 0.01), skip_first_screenshot=True):
        return self.drag_page(page, main=main, random_range=random_range, skip_first_screenshot=skip_first_screenshot)

    def prev_page(self, main, page=0.8, random_range=(-0.01, 0.01), skip_first_screenshot=True):
        return self.drag_page(-page, main=main, random_range=random_range, skip_first_screenshot=skip_first_screenshot)


class AdaptiveScroll(Scroll):
    def __init__(self, area, parameters: dict | None = None, background=5, is_vertical=True, name="Scroll"):
        """
        Args:
            area (Button, tuple): A button or area of the whole scroll.
            parameters (dict): Parameters passing to scipy.find_peaks
            background (int):
            is_vertical (bool): True if vertical, false if horizontal.
            name (str):
        """
        if parameters is None:
            parameters = {}
        self.parameters = parameters
        self.background = background
        super().__init__(area, color=(255, 255, 255), is_vertical=is_vertical, name=name)

    def match_color(self, main):
        if self.is_vertical:
            area = (self.area[0] - self.background, self.area[1], self.area[2] + self.background, self.area[3])
            image = main.image_crop(area, copy=False)
            image = rgb2gray(image)
            image = image.flatten()
            wlen = area[2] - area[0]
        else:
            area = (self.area[0], self.area[1] - self.background, self.area[2], self.area[3] + self.background)
            image = main.image_crop(area, copy=False)
            image = rgb2gray(image)
            image = image.flatten("F")
            wlen = area[3] - area[1]

        parameters = {
            "height": 128,
            "prominence": 30,
            "wlen": wlen,
            "width": 2,
        }
        parameters.update(self.parameters)
        peaks, _ = signal.find_peaks(image, **parameters)
        peaks //= wlen

        self.length = len(peaks)
        mask = np.zeros((self.total,), dtype=np.bool_)
        mask[peaks] = 1
        return mask
