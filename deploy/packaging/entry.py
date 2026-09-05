"""PyInstaller entry for the alas-backend sidecar.

The one and only runtime entry is the `alas` console script
(pyproject.toml `[project.scripts] alas = "module.cli:main"`); this tiny
script exists so PyInstaller has a valid top-level module to analyze
(the package `module.cli` cannot be a spec entry directly).
"""

from module.cli.app import main

if __name__ == "__main__":
    main()
