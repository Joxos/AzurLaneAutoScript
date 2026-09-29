import multiprocessing
import threading
from multiprocessing.managers import SyncManager
from typing import TYPE_CHECKING, Any

from module.base.decorator import cached_class_property

if TYPE_CHECKING:
    from module.config.config_updater import ConfigUpdater
    from module.webui.config import DeployConfig


class State:
    """
    Shared settings
    """

    _init = False
    _clearup = False

    restart_event: threading.Event | None = None
    # created by init(); None until the webui app is up
    manager: SyncManager | None = None
    theme: str = "dark"
    # The pywebview window, when the desktop flavor owns one. The tray (a
    # separate process) brings it back through the webui router, so the
    # backend has to publish the handle here. None in headless/web mode.
    window: Any = None

    @classmethod
    def init(cls):
        cls.manager = multiprocessing.Manager()
        cls._init = True

    @classmethod
    def require_manager(cls) -> SyncManager:
        """The manager, or a clear error when `init()` has not run.

        ProcessManager builds its queues from it and clearup() shuts it down;
        the webui app lifespan owns init(). Without this the same mistake
        surfaced as `AttributeError: 'NoneType' object has no attribute
        'Queue'` in three unrelated places.
        """
        if cls.manager is None:
            raise RuntimeError("State.init() has not run yet (the webui app lifespan calls it)")
        return cls.manager

    @classmethod
    def clearup(cls):
        cls.require_manager().shutdown()
        cls._clearup = True

    @cached_class_property
    def deploy_config(self) -> "DeployConfig":
        """
        Returns:
            DeployConfig：
        """
        from module.webui.config import DeployConfig

        return DeployConfig()

    @cached_class_property
    def config_updater(self) -> "ConfigUpdater":
        """
        Returns:
            ConfigUpdater：
        """
        from module.config.config_updater import ConfigUpdater

        return ConfigUpdater()
