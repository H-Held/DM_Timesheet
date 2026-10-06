"""
main.py
───────
Entry point for the DM Timesheet tool.

Two run modes (select with --mode):

  standard  Download new timesheet ("Zeitnachweis") e-mails from Gmail,
            decrypt the SEPPmail attachments, sort the PDFs into folders, and
            sync each new Zeitnachweis into Google Calendar (with reminders).

  full      Skip e-mail entirely. Re-scan every Zeitnachweis PDF already saved
            on disk and (re-)sync them all into Google Calendar (no reminders).

Every run writes full DEBUG detail to a rotating ``dm_downloader.log`` (kept
next to the .exe when packaged, at the project root when run from source; see
app_paths.py) while the console only shows INFO and up. Both modes log a
"Starting run — mode=..." line at the very start, and any unhandled error is
logged with its full traceback before the process exits.
"""

import os
import sys
import logging
import logging.handlers
import argparse

# When launched via pythonw.exe (no console attached, as the autostart updater
# does), sys.stdout/sys.stderr are None — any print() or StreamHandler would
# crash. Redirect them to a null stream so the rest of the code can stay
# console-agnostic.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# The project is split across two folders (programm/ and kalender_reader/).
# Put both on the import path so the modules can import each other by name,
# whether run from source or bundled into an .exe.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
for _extra_path in (_THIS_DIR, os.path.join(_PROJECT_ROOT, "kalender_reader")):
    if _extra_path not in sys.path:
        sys.path.insert(0, _extra_path)

import environment_loader
import app_paths
from email_reader import GmailReader
from seppmail_decryptor import (
    decrypt_secure_email,
    download_attachments,
    parse_attachments,
)
from zeitnachweis_parser import month_year_from_filename
from calendar_sync import sync_zeitnachweis, full_sync, export_csv


# ── Logging ──────────────────────────────────────────────────────────────────
LOG_FILENAME = "dm_downloader.log"
LOG_MAX_BYTES = 2_000_000   # rotate at ~2 MB
LOG_BACKUP_COUNT = 3        # keep 3 old logs (~8 MB ceiling total)

# Third-party libraries that log at DEBUG/INFO far beyond anything useful here
# (pdfminer in particular emits one line per PDF token — every "nexttoken",
# "seek", "do_keyword" — which balloons the log file into the hundreds of MB
# and slows every run down with sheer I/O; googleapiclient.discovery emits one
# DEBUG line per HTTP call it makes, which adds up fast during a full sync).
# Capped at WARNING so only real problems from these libraries show up; our
# own modules stay at DEBUG.
_NOISY_LOGGERS = (
    "pdfminer", "PIL", "urllib3",
    "googleapiclient.discovery", "googleapiclient.discovery_cache",
)

logger = logging.getLogger(__name__)


def _configure_logging(log_path: str) -> None:
    """Set up file (DEBUG, rotating) + console (INFO) logging."""
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    # Windows consoles often can't encode "→" / "—"; show "?" instead of an escape.
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="replace")
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[file_handler, console_handler],
    )
    for noisy in _NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ── Behavior constants ───────────────────────────────────────────────────────
ATTACHMENT_NAME = "secure-email.html"  # the encrypted attachment to look for
PROCESS_LABEL = "Inbox"                # Gmail folder/label to scan
PROCESSED_LABEL = "dm_processed"       # label added to finished e-mails
MARK_AS_READ = True
REMOVE_FROM_INBOX = True


# ─────────────────────────────────────────────────────────────────────────────
# Calendar sync helper
# ─────────────────────────────────────────────────────────────────────────────

def _sync_pdf_to_calendar(pdf_path: str, with_reminders: bool) -> None:
    """Sync one saved Zeitnachweis PDF to Google Calendar."""
    month_year = month_year_from_filename(os.path.basename(pdf_path))
    if not month_year:
        return
    month, year = month_year

    logger.info("  Syncing calendar for %02d/%d ...", month, year)
    try:
        sync_zeitnachweis(pdf_path, month, year, with_reminders=with_reminders)
    except Exception:
        logger.exception("  Calendar sync failed:")


# ─────────────────────────────────────────────────────────────────────────────
# Standard mode — process new inbox e-mails only
# ─────────────────────────────────────────────────────────────────────────────

def process_single_email(
    reader: GmailReader,
    folder: str,
    email_id: bytes,
    seppmail_password: str,
    download_dir: str,
) -> list[str]:
    """Decrypt, save, and calendar-sync the attachments of a single e-mail."""
    meta = reader.get_email_metadata(folder, email_id)
    if not meta:
        logger.warning("Could not read metadata — skipping email ID %s.", email_id)
        return []

    logger.info("Processing: [ID %s] %s", meta.get("id"), meta.get("date"))
    logger.info("  Subject: %s", meta.get("subject"))

    secure_html = reader.fetch_attachments_to_ram([(folder, email_id)], ATTACHMENT_NAME)
    if not secure_html:
        logger.warning("  No secure-email.html — skipping.")
        return []

    html_bytes = secure_html[0]["data"].read()

    logger.info("  Decrypting ...")
    result = decrypt_secure_email(html_bytes, seppmail_password)

    attachments = parse_attachments(result)
    if not attachments:
        logger.info("  No PDF attachments found.")
        return []

    logger.info("  Found %d PDF(s): %s", len(attachments), [a["filename"] for a in attachments])

    saved = download_attachments(result, base_dir=download_dir, attachments=attachments)

    # Calendar sync for each saved Zeitnachweis (with reminders in standard mode).
    for pdf_path in saved:
        if "Zeitnachweis" in os.path.basename(pdf_path):
            _sync_pdf_to_calendar(pdf_path, with_reminders=True)

    if PROCESSED_LABEL:
        reader.add_label(folder, email_id, PROCESSED_LABEL)
    if MARK_AS_READ:
        reader.mark_as_read(folder, email_id)
    if REMOVE_FROM_INBOX and folder == "Inbox":
        reader.remove_label("Inbox", email_id)
        logger.info("  INBOX label removed.")

    return saved


def run_standard(gmail, passkey, seppmail_password, sender, subject, download_dir):
    """Connect to Gmail and process every matching e-mail in the inbox."""
    reader = GmailReader(gmail, passkey)
    reader.connect()
    try:
        if PROCESSED_LABEL:
            reader.create_label(PROCESSED_LABEL)

        results = reader.search_emails(sender, subject=subject, label=PROCESS_LABEL)
        if not results:
            logger.warning("No matching emails found.")
            return []

        logger.info("Found %d matching email(s) — processing all.", len(results))
        all_saved = []
        for folder, email_id in results:
            saved = process_single_email(
                reader, folder, email_id, seppmail_password, download_dir
            )
            all_saved.extend(saved)
        return all_saved
    finally:
        reader.disconnect()


# ─────────────────────────────────────────────────────────────────────────────
# Full mode — re-sync all saved PDFs from disk, no e-mail access
# ─────────────────────────────────────────────────────────────────────────────

def run_full(download_dir: str):
    """Re-sync every saved Zeitnachweis PDF on disk to Google Calendar."""
    logger.info("Full sync mode — scanning all saved Zeitnachweis PDFs ...")
    full_sync(download_dir)
    _export_csv(download_dir)


def _export_csv(download_dir: str) -> None:
    """Rebuild the local CSV overview (DM/Kalender_Uebersicht.csv) from every saved PDF."""
    csv_path = export_csv(download_dir)
    if csv_path:
        logger.info("CSV overview written: %s", csv_path)
        print(f"CSV overview: {csv_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    log_path = app_paths.resolve(LOG_FILENAME, _PROJECT_ROOT)
    _configure_logging(log_path)

    parser = argparse.ArgumentParser(description="DM Timesheet downloader & calendar sync")
    parser.add_argument(
        "--mode",
        choices=["standard", "full"],
        default="standard",
        help=(
            "standard: process new inbox emails + calendar sync with reminders (default); "
            "full: re-sync ALL saved PDFs to calendar (past=grey, future=violet)"
        ),
    )
    args = parser.parse_args()
    logger.info("Starting run — mode=%s", args.mode)

    try:
        if args.mode == "full":
            download_dir = environment_loader.load_download_dir()
            run_full(download_dir)
            return

        # standard mode — needs e-mail credentials and filters.
        gmail, passkey = environment_loader.load_env()
        seppmail_password = environment_loader.load_seppmail_password()
        download_dir = environment_loader.load_download_dir()
        sender, subject = environment_loader.load_email_config()

        all_saved = run_standard(
            gmail, passkey, seppmail_password, sender, subject, download_dir
        )
        _export_csv(download_dir)

        print("\n" + "=" * 60)
        if all_saved:
            logger.info("Done — %d PDF(s) sorted into '%s/DM/'.", len(all_saved), download_dir)
            print(f"Done! {len(all_saved)} PDF(s) sorted into '{download_dir}/DM/':")
            for path in all_saved:
                print(f"    {path}")
        else:
            logger.info("No new PDFs — nothing to do (all skipped or none found).")
            print("No PDFs were saved (all skipped or none found).")
        print("=" * 60)
    except Exception:
        logger.exception("Fatal error during run (mode=%s)", args.mode)
        sys.exit(1)


if __name__ == "__main__":
    main()
