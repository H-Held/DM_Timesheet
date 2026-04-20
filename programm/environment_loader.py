import os
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)


def load_env() -> tuple[str, str]:
    load_dotenv()
    gmail        = os.getenv("GMAIL")
    app_password = os.getenv("APP_PASSKEY")

    if not gmail or not app_password:
        raise RuntimeError(
            "\nMissing .env variables.\n"
            '  GMAIL="your_email@gmail.com"\n'
            '  APP_PASSKEY="your_gmail_app_password"'
        )

    logger.info("Gmail credentials loaded for: %s", gmail)
    return gmail, app_password


def load_seppmail_password() -> str:
    load_dotenv()
    password = os.getenv("SEPPMAIL_PASSWORD")

    if not password:
        raise RuntimeError(
            "\nMissing .env variable.\n"
            '  SEPPMAIL_PASSWORD="your_seppmail_password"'
        )

    logger.info("SEPPmail password loaded.")
    return password