"""Backward-compatible shim: `python gui.py` ≡ `alas run web`.

The real implementation lives in module/cli (see module/cli/run.py); this
file only translates legacy command-line invocations. When the first
argument is an `alas` subcommand it is passed through, so the frozen
sidecar also supports `alas-backend.exe run desktop` (NSIS shortcut).
"""

import sys

_SUBCOMMANDS = {"run", "build", "doctor", "version"}

if __name__ == "__main__":
    from module.cli.app import main

    argv = sys.argv[1:]
    if argv and argv[0] in _SUBCOMMANDS:
        main(argv)
    else:
        main(["run", "web", *argv])
