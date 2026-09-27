"""Entry point for the packaged app: no arguments opens the window, arguments run the command line."""
import multiprocessing
import os
import sys


def _attach_console():
    """A windowed Windows build has no stdout; borrow the terminal it was started from, if any."""
    if sys.platform != "win32" or sys.stdout is not None:
        return
    import ctypes

    if ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
    else:
        sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) > 1:
        _attach_console()
        from ratica.cli import main as cli_main

        sys.exit(cli_main())
    from ratica.gui import main

    main()
