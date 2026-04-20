import os
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

def load_env():
    load_dotenv()
    gmail = os.getenv("GMAIL")
    app_password = os.getenv("APP_PASSKEY")

    if not gmail or not app_password:
        logging.error("Error loading environment variables")
        raise RuntimeError(
            "\nError loading environment variables.\n"
            "Please ensure that the .env file exists and contains the required variables.\n"
            "Expected variables: GMAIL, APP_PASSKEY\n"
            "Example .env file content:\n"
            'GMAIL="your_email@gmail.com"\n'
            'APP_PASSKEY="your_app_password"'
        )
    
    logger.info("Credentials loaded for: %s", gmail)
    return gmail, app_password