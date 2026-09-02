"""Alas core package.

Top-level import hook: packaging==20.9 (pinned by uiautomator2==2.16.17)
imports stdlib `distutils`, which no longer exists on Python 3.12+; the
setuptools (<81) shim provides it, but only if it is pinned into
sys.modules before anything reaches packaging. module/logger.py does the
same at the end of the import chain; this ensures any `module.*` import
(including devices that pull in adbutils -> pkg_resources -> packaging)
is safe regardless of order.
"""

import contextlib

with contextlib.suppress(ImportError):  # pragma: no cover - setuptools is always installed
    import distutils  # noqa: F401
