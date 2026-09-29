import cv2
import numpy as np

from module.core.image import crop


def get_color(image, area):
    """Calculate the average color of a particular area of the image.

    Args:
        image (np.ndarray): Screenshot.
        area (tuple): (upper_left_x, upper_left_y, bottom_right_x, bottom_right_y)

    Returns:
        tuple: (r, g, b)
    """
    temp = crop(image, area, copy=False)
    color = cv2.mean(temp)
    return color[:3]


def color_similarity(color1, color2):
    """
    Args:
        color1 (tuple): (r, g, b)
        color2 (tuple): (r, g, b)

    Returns:
        int:
    """
    # print(color1, color2)
    # diff = np.array(color1).astype(int) - np.array(color2).astype(int)
    # diff = np.max(np.maximum(diff, 0)) - np.min(np.minimum(diff, 0))
    diff_r = color1[0] - color2[0]
    diff_g = color1[1] - color2[1]
    diff_b = color1[2] - color2[2]

    max_positive = 0
    max_negative = 0
    if diff_r > max_positive:
        max_positive = diff_r
    elif diff_r < max_negative:
        max_negative = diff_r
    if diff_g > max_positive:
        max_positive = diff_g
    elif diff_g < max_negative:
        max_negative = diff_g
    if diff_b > max_positive:
        max_positive = diff_b
    elif diff_b < max_negative:
        max_negative = diff_b

    diff = max_positive - max_negative
    return diff


def color_similar(color1, color2, threshold=10):
    """
    Consider two colors are similar, if tolerance lesser or equal threshold.
    Tolerance = Max(Positive(difference_rgb)) + Max(- Negative(difference_rgb))
    The same as the tolerance in Photoshop.

    Args:
        color1 (tuple): (r, g, b)
        color2 (tuple): (r, g, b)
        threshold (int): Default to 10.

    Returns:
        bool: True if two colors are similar.
    """
    # print(color1, color2)
    # diff = np.array(color1).astype(int) - np.array(color2).astype(int)
    # diff = np.max(np.maximum(diff, 0)) - np.min(np.minimum(diff, 0))
    diff_r = color1[0] - color2[0]
    diff_g = color1[1] - color2[1]
    diff_b = color1[2] - color2[2]

    max_positive = 0
    max_negative = 0
    if diff_r > max_positive:
        max_positive = diff_r
    elif diff_r < max_negative:
        max_negative = diff_r
    if diff_g > max_positive:
        max_positive = diff_g
    elif diff_g < max_negative:
        max_negative = diff_g
    if diff_b > max_positive:
        max_positive = diff_b
    elif diff_b < max_negative:
        max_negative = diff_b

    diff = max_positive - max_negative
    return diff <= threshold


def color_similar_1d(image, color, threshold=10):
    """
    Args:
        image (np.ndarray): 1D array.
        color: (r, g, b)
        threshold(int): Default to 10.

    Returns:
        np.ndarray: bool
    """
    diff = image.astype(int) - color
    diff = np.max(np.maximum(diff, 0), axis=1) - np.min(np.minimum(diff, 0), axis=1)
    return diff <= threshold


def color_similarity_2d(image, color):
    """
    Per-pixel color distance map: 255 when the pixel exactly matches color.

    result = 255 - sat_add(max_c(sat_sub(image - c)), max_c(sat_sub(c - image)))
    where c = (r, g, b), sat_sub/sat_add are uint8 saturating ops,
    max_c takes the per-pixel maximum across channels.

    Args:
        image: 2D array.
        color: (r, g, b)

    Returns:
        np.ndarray: uint8
    """
    # r, g, b = cv2.split(cv2.subtract(image, (*color, 0)))
    # positive = cv2.max(cv2.max(r, g), b)
    # r, g, b = cv2.split(cv2.subtract((*color, 0), image))
    # negative = cv2.max(cv2.max(r, g), b)
    # return cv2.subtract(255, cv2.add(positive, negative))
    h, w = image.shape[:2]
    if h * w < 30000:
        # The 3-channel path is faster on tiny images where per-call
        # overhead dominates
        diff = cv2.subtract(image, (*color,))
        r, g, b = cv2.split(diff)
        cv2.max(r, g, dst=r)
        cv2.max(r, b, dst=r)
        positive = r
        cv2.subtract((*color,), image, dst=diff)
        r, g, b = cv2.split(diff)
        cv2.max(r, g, dst=r)
        cv2.max(r, b, dst=r)
        negative = r
        cv2.add(positive, negative, dst=positive)
        cv2.bitwise_not(positive, dst=positive)
        return positive
    # Per-channel subtract with buffer reuse wins on larger images
    r, g, b = cv2.split(image)
    cr, cg, cb = color
    positive = cv2.subtract(r, cr)
    cv2.subtract(cr, r, dst=r)
    negative = r
    diff = cv2.subtract(g, cg)
    cv2.max(positive, diff, dst=positive)
    cv2.subtract(cg, g, dst=diff)
    cv2.max(negative, diff, dst=negative)
    cv2.subtract(b, cb, dst=diff)
    cv2.max(positive, diff, dst=positive)
    cv2.subtract(cb, b, dst=diff)
    cv2.max(negative, diff, dst=negative)
    cv2.add(positive, negative, dst=positive)
    cv2.bitwise_not(positive, dst=positive)
    return positive


def color_mask(image, color, threshold=30):
    """
    Create a binary mask for the pixels similar to color.

    result = 255 if diff <= threshold else 0
    where diff = sat_add(max_c(sat_sub(image - c)), max_c(sat_sub(c - image))),
    c = (r, g, b), sat_sub/sat_add are uint8 saturating ops,
    max_c takes the per-pixel maximum across channels.
    The tolerance is the same as color_similar().

    Same result as `cv2.inRange(255 - color_similarity_2d(image, color), 255 - threshold, 255)`,
    but it skips the two intermediate bitmaps, which is what made the
    per-pixel path the hot spot on large screenshots.

    Args:
        image: Shape (height, width, channel)
        color: (r, g, b)
        threshold (int): Default to 30. Pixels with a tolerance lesser or
            equal to threshold are matched.

    Returns:
        np.ndarray: Shape (height, width), uint8, 255 for matched pixels
            and 0 for the rest.
    """
    h, w = image.shape[:2]
    if h * w < 30000:
        # The 3-channel path is faster on tiny images where per-call
        # overhead dominates
        diff = cv2.subtract(image, (*color, 0))
        r, g, b = cv2.split(diff)
        cv2.max(r, g, dst=r)
        cv2.max(r, b, dst=r)
        positive = r
        cv2.subtract((*color, 0), image, dst=diff)
        r, g, b = cv2.split(diff)
        cv2.max(r, g, dst=r)
        cv2.max(r, b, dst=r)
        negative = r
        cv2.add(positive, negative, dst=positive)
        # diff is always non-negative, so 255 where diff <= threshold is
        # equivalent to inRange(255 - diff, 255 - threshold, 255) and skips
        # the intermediate bitwise_not in color_similarity_2d
        cv2.threshold(positive, threshold, 255, cv2.THRESH_BINARY_INV, dst=positive)
        return positive
    # Per-channel subtract with buffer reuse wins on larger images
    r, g, b = cv2.split(image)
    cr, cg, cb = color
    positive = cv2.subtract(r, cr)
    cv2.subtract(cr, r, dst=r)
    negative = r
    diff = cv2.subtract(g, cg)
    cv2.max(positive, diff, dst=positive)
    cv2.subtract(cg, g, dst=diff)
    cv2.max(negative, diff, dst=negative)
    diff = cv2.subtract(b, cb, dst=diff)
    cv2.max(positive, diff, dst=positive)
    cv2.subtract(cb, b, dst=diff)
    cv2.max(negative, diff, dst=negative)
    cv2.add(positive, negative, dst=positive)
    # diff is always non-negative, so 255 where diff <= threshold is
    # equivalent to inRange(255 - diff, 255 - threshold, 255) and skips
    # the intermediate bitwise_not in color_similarity_2d
    cv2.threshold(positive, threshold, 255, cv2.THRESH_BINARY_INV, dst=positive)
    return positive


def color_bar_percentage(image, area, prev_color, reverse=False, starter=0, threshold=30):
    """
    Args:
        image:
        area:
        prev_color:
        reverse: True if bar goes from right to left.
        starter:
        threshold:

    Returns:
        float: 0 to 1.
    """
    image = crop(image, area, copy=False)
    image = image[:, ::-1, :] if reverse else image
    length = image.shape[1]
    prev_index = starter

    for _ in range(1280):
        bar = color_similarity_2d(image, color=prev_color)
        index = np.where(np.any(bar > 255 - threshold, axis=0))[0]
        if not index.size:
            return prev_index / length
        else:
            index = index[-1]
        if index <= prev_index:
            return index / length
        prev_index = index

        prev_row = bar[:, prev_index] > 255 - threshold
        if not prev_row.size:
            return prev_index / length
        # Look back 5px to get average color
        left = max(prev_index - 5, 0)
        mask = np.where(bar[:, left : prev_index + 1] > 255 - threshold)
        prev_color = np.mean(image[:, left : prev_index + 1][mask], axis=0)

    return 0.0
