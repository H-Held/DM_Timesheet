import os
import logging
from dotenv import load_dotenv

import app_paths

logger = logging.getLogger(__name__)

_ENV_LOADED = False


def _ensure_env_loaded() -> None:
    """
    Load the .env file exactly once.

    From source, python-dotenv locates ``programm/.env`` automatically. As a
    packaged .exe it is read from next to the executable so the user can edit
    it without rebuilding.
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    if app_paths.is_frozen():
        load_dotenv(os.path.join(app_paths.executable_dir(), ".env"))
    else:
        load_dotenv()
    _ENV_LOADED = True


def load_env() -> tuple[str, str]:
    _ensure_env_loaded()
    gmail        = os.getenv("GMAIL")
    app_password = os.getenv("APP_PASSKEY")

    if not gmail or not app_password:
        logger.error("Missing .env variables: GMAIL / APP_PASSKEY")
        raise RuntimeError(
            "\nMissing .env variables.\n"
            '  GMAIL="your_email@gmail.com"\n'
            '  APP_PASSKEY="your_gmail_app_password"'
        )

    logger.info("Gmail credentials loaded for: %s", gmail)
    return gmail, app_password


def load_seppmail_password() -> str:
    _ensure_env_loaded()
    password = os.getenv("SEPPMAIL_PASSWORD")

    if not password:
        logger.error("Missing .env variable: SEPPMAIL_PASSWORD")
        raise RuntimeError(
            "\nMissing .env variable.\n"
            '  SEPPMAIL_PASSWORD="your_seppmail_password"'
        )

    logger.info("SEPPmail password loaded.")
    return password


def load_email_config() -> tuple[str, str]:
    """
    Returns (sender, subject) from .env.
    Both are required — raises RuntimeError if missing.
    """
    _ensure_env_loaded()
    sender  = os.getenv("EMAIL_SENDER")
    subject = os.getenv("EMAIL_SUBJECT")

    if not sender:
        logger.error("Missing .env variable: EMAIL_SENDER")
        raise RuntimeError(
            "\nMissing .env variable.\n"
            '  EMAIL_SENDER="MA-S+B-MitarbeiterSysteme.DE-Mailbox@dm.de"'
        )
    if not subject:
        logger.error("Missing .env variable: EMAIL_SUBJECT")
        raise RuntimeError(
            "\nMissing .env variable.\n"
            '  EMAIL_SUBJECT="dmSAP Nachweise: Ihre angeforderten Dokumente"'
        )

    logger.info("Email filter — sender:  %s", sender)
    logger.info("Email filter — subject: %s", subject)
    return sender, subject


def load_download_dir() -> str:
    """
    Returns the base download directory.
    PDFs will be placed in {DOWNLOAD_DIR}/DM/...
    Falls back to 'downloads' if not set.
    """
    _ensure_env_loaded()
    dl_dir = os.getenv("DOWNLOAD_DIR", "downloads")
    logger.info("Download directory: '%s'", dl_dir)
    return dl_dir