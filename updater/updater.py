"""
updater.py
──────────
Autostart entry point for the desktop PC ("Festrechner").

Packaged into DM_Timesheet_Updater.exe (windowed, no console) and placed in
the Windows Startup folder. On every login it:

  1. Checks the git repo for new commits on origin/main.
  2. If there are new commits: pulls them and updates the venv's packages.
  3. Launches the app itself (programm/main.py) via the venv's pythonw.exe,
     so the whole thing runs invisibly in the background — no terminal ever
     appears in normal operation.

Everything is logged to updater.log next to this executable; nothing is ever
written to a console, since none exists when this is started from Autostart.
"""

import os
import sys
import logging
import logging.handlers
import subprocess

LOG_FILENAME = "updater.log"
LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 2

# Prevents a console window from flashing up for any child process we spawn.
CREATE_NO_WINDOW = 0x08000000


def _this_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _repo_dir() -> str:
    """The repo root is the parent of the 'updater' folder this exe lives in."""
    override = os.environ.get("DM_TIMESHEET_REPO")
    if override:
        return override
    return os.path.dirname(_this_dir())


def _configure_logging() -> logging.Logger:
    log_path = os.path.join(_this_dir(), LOG_FILENAME)
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
    logger = logging.getLogger("updater")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    return logger


def _run(cmd, cwd, logger) -> subprocess.CompletedProcess:
    logger.debug("Running: %s (cwd=%s)", " ".join(cmd), cwd)
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW,
    )
    if result.stdout.strip():
        logger.debug("stdout: %s", result.stdout.strip())
    if result.stderr.strip():
        logger.debug("stderr: %s", result.stderr.strip())
    return result


def check_and_update(repo_dir: str, logger: logging.Logger) -> None:
    fetch = _run(["git", "fetch", "origin"], repo_dir, logger)
    if fetch.returncode != 0:
        logger.warning("git fetch failed (offline / no access?) — skipping update check.")
        return

    local = _run(["git", "rev-parse", "HEAD"], repo_dir, logger).stdout.strip()
    remote = _run(["git", "rev-parse", "origin/main"], repo_dir, logger).stdout.strip()

    if not local or not remote:
        logger.warning("Could not determine git revisions — skipping update.")
        return

    if local == remote:
        logger.info("Already up to date (%s).", local[:8])
        return

    logger.info("Update available: %s -> %s. Pulling ...", local[:8], remote[:8])
    pull = _run(["git", "pull", "--ff-only", "origin", "main"], repo_dir, logger)
    if pull.returncode != 0:
        logger.error("git pull failed — continuing with the previously installed version.")
        return

    venv_pip = os.path.join(repo_dir, ".venv", "Scripts", "pip.exe")
    requirements = os.path.join(repo_dir, "requirements.txt")
    if os.path.exists(venv_pip) and os.path.exists(requirements):
        logger.info("Updating dependencies ...")
        install = _run([venv_pip, "install", "-q", "-r", requirements], repo_dir, logger)
        if install.returncode != 0:
            logger.error("pip install failed after update — app may not start correctly.")

    logger.info("Update complete: now at %s.", remote[:8])


def launch_app(repo_dir: str, logger: logging.Logger) -> None:
    pythonw = os.path.join(repo_dir, ".venv", "Scripts", "pythonw.exe")
    main_py = os.path.join(repo_dir, "programm", "main.py")

    if not os.path.exists(pythonw):
        logger.error("venv pythonw.exe not found at '%s' — run setup_festrechner.ps1 first.", pythonw)
        return
    if not os.path.exists(main_py):
        logger.error("main.py not found at '%s'.", main_py)
        return

    logger.info("Launching DM Timesheet (standard mode) ...")
    subprocess.Popen(
        [pythonw, main_py, "--mode", "standard"],
        cwd=os.path.join(repo_dir, "programm"),
        creationflags=CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
    )


def main() -> None:
    logger = _configure_logging()
    repo_dir = _repo_dir()
    logger.info("=== Updater starting (repo: %s) ===", repo_dir)

    try:
        if os.path.isdir(os.path.join(repo_dir, ".git")):
            check_and_update(repo_dir, logger)
        else:
            logger.warning("No .git folder at '%s' — skipping update check.", repo_dir)
    except Exception:
        logger.exception("Update check failed — continuing with the current version.")

    try:
        launch_app(repo_dir, logger)
    except Exception:
        logger.exception("Failed to launch the app.")


if __name__ == "__main__":
    main()
