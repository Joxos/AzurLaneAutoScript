"""Allow `python -m module.cli` as an alternative to the installed `alas` script."""

from module.cli.app import main

if __name__ == "__main__":
    main()
