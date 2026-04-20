import logging
import environment_loader
from email_reader import GmailReader
from seppmail_decryptor import decrypt_secure_email, download_attachments, parse_attachments

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

SENDER          = "MA-S+B-MitarbeiterSysteme.DE-Mailbox@dm.de"
ATTACHMENT_NAME = "secure-email.html"
PDF_SAVE_DIR    = "downloads"

# ── Label settings ─────────────────────────────────────────────────
# After processing an email, the script will:
#   1. Add the label PROCESSED_LABEL to it
#   2. Mark it as read
#
# Set to None to disable either action:
#   PROCESSED_LABEL = None  → don't add any label
#   MARK_AS_READ    = False → don't change read/unread status
PROCESSED_LABEL = "dm_processed"
MARK_AS_READ    = True


def process_single_email(
    reader:          GmailReader,
    folder:          str,
    email_id:        bytes,
    seppmail_passwd: str,
) -> list[str]:
    """
    Fetches secure-email.html from one email, decrypts it,
    downloads all PDFs, then labels and marks it as read.

    Returns:
        List of saved PDF file paths.
    """
    meta = reader.get_email_metadata(folder, email_id)
    logger.info("Processing: [ID %s] %s", meta.get("id"), meta.get("date"))

    # Download secure-email.html into RAM
    secure_html = reader.fetch_attachments_to_ram([(folder, email_id)], ATTACHMENT_NAME)
    if not secure_html:
        logger.warning("  No secure-email.html — skipping.")
        return []

    html_bytes = secure_html[0]["data"].read()

    # Decrypt and download PDFs
    logger.info("  Decrypting ...")
    result = decrypt_secure_email(html_bytes, seppmail_passwd)

    attachments = parse_attachments(result)
    if not attachments:
        logger.info("  No PDF attachments.")
        return []

    logger.info("  Found %d PDF(s): %s", len(attachments), [a["filename"] for a in attachments])
    saved = download_attachments(result, save_dir=PDF_SAVE_DIR)

    # ── Post-processing: label + mark as read ──────────────────────
    if PROCESSED_LABEL:
        reader.add_label(folder, email_id, PROCESSED_LABEL)

    if MARK_AS_READ:
        reader.mark_as_read(folder, email_id)

    return saved


def main():
    gmail, passkey  = environment_loader.load_env()
    seppmail_passwd = environment_loader.load_seppmail_password()

    reader = GmailReader(gmail, passkey)
    reader.connect()

    try:
        # Create the label if it doesn't exist yet
        if PROCESSED_LABEL:
            reader.create_label(PROCESSED_LABEL)

        results = reader.search_emails(SENDER)
        if not results:
            logger.warning("No emails found.")
            return

        logger.info("Found %d email(s) — processing all.", len(results))

        all_saved = []
        for folder, email_id in results:
            saved = process_single_email(reader, folder, email_id, seppmail_passwd)
            all_saved.extend(saved)

    finally:
        reader.disconnect()

    print("\n" + "=" * 60)
    if all_saved:
        print(f"✓ Done! {len(all_saved)} PDF(s) saved to '{PDF_SAVE_DIR}':")
        for path in all_saved:
            print(f"    {path}")
    else:
        print("No PDFs were downloaded.")
    print("=" * 60)


if __name__ == "__main__":
    main()