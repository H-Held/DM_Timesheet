"""
app_paths.py
────────────
Resolves the location of user-editable files (``.env``, ``credentials.json``,
``token.pickle``) so the program works the same whether it runs from source or
as a packaged PyInstaller ``.exe``.

  • From source  → files are read from their normal place in the project tree.
  • As an .exe   → files are read from the folder that contains the executable,
                   so the user can drop ``.env`` and ``credentials.json`` next
                   to ``DM_Timesheet.exe`` and edit them freely.
"""

import os
import sys


def is_frozen() -> bool:
    """True when running inside a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def executable_dir() -> str:
    """Folder that contains the running .exe (only meaningful when frozen)."""
    return os.path.dirname(sys.executable)


def resolve(filename: str, source_dir: str) -> str:
    """
    Return the full path to a user file.

    Args:
        filename:   Name of the file, e.g. ``credentials.json``.
        source_dir: Folder to use when running from source (not frozen).

    Returns:
        ``<exe folder>/filename`` when frozen, else ``<source_dir>/filename``.
    """
    if is_frozen():
        return os.path.join(executable_dir(), filename)
    return os.path.join(source_dir, filename)
