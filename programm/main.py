import os
import smtplib
from email.message import EmailMessage
import logging

from email_reader import GmailReader
import environment_loader


logging.basicConfig(level=logging.DEBUG, format="%(asctime)s | %(levelname)s | %(message)s")



def main():
    # 1. Loading Credentials
    gmail, passkey = environment_loader.load_env()

    # 2. Creating reader and connecting
    reader = GmailReader(gmail, passkey)
    reader.connect()

    results = reader.search_emails('MA-S+B-MitarbeiterSysteme.DE-Mailbox@dm.de')

    for folder, email_id in results:
        meta = reader.get_email_metadata(folder, email_id)
        status = "READ  " if meta["read"] else "UNREAD"
        print(f"[{status}] {meta['date']:<32} | Folder: {meta['folder']:<25} | ID: {meta['id']}")

if __name__ == "__main__":
    main()