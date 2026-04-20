import imaplib
import email
import logging
import io

logger = logging.getLogger(__name__)

class GmailReader:
    """
    Verbindet sich mit einem Gmail-Konto per IMAP
    und ermöglicht das Suchen und Herunterladen von E-Mails.
    """
 
    def __init__(self, gmail_address: str, passkey: str):
        self.gmail_address = gmail_address
        self.passkey = passkey
        self.mail = None
        self._connected = False
 
    # ──────────────────────────────────────────
    # Connect & Disconnect
    # ──────────────────────────────────────────
 
    def connect(self):
        """Connecting to Gmail IMAP-Server."""
        if(self._connected == False):
            logger.info("Connecting to imap.gmail.com ...")
            self.mail = imaplib.IMAP4_SSL("imap.gmail.com")
            self.mail.login(self.gmail_address, self.passkey)
            logger.info("Valid connection as: %s", self.gmail_address)
            self._connected = True
        else:
            logger.info("Already connected as %s" , self.gmail_address)
 
    def disconnect(self):
        """Closes the Connection"""
        if self.mail:
            self.mail.logout()
            logger.info("Disconnected.") 
            self._connected = False

    # ──────────────────────────────────────────
    # Read all Labels/Folders
    # ──────────────────────────────────────────

    def _get_all_folders(self) -> list[str]:
        """Returns a list of all folders/labels in the mailbox."""
        status, folders = self.mail.list()
        if status != "OK":
            logger.warning("Could not retrieve folder list.")
            return []

        folder_names = []
        for folder in folders:
            decoded = folder.decode()
            name = decoded.split('"')[-2]
            folder_names.append(name)

        logger.debug("Available folders: %s", folder_names)
        return folder_names
    
    # ──────────────────────────────────────────
    # SEARCH EMAILS
    #
    # label=None    → search everywhere (all folders/labels)
    # label="INBOX" → only search in the inbox
    # label="dm"    → only search in the "dm" label
    # ──────────────────────────────────────────

    def search_emails(self, sender: str, label: str = None) -> list:
        """
        Searches for emails from a specific sender.
 
        Args:
            sender: The sender's email address (e.g. "noreply@dm.de")
            label:  Gmail label/folder to search in (e.g. "INBOX" or "dm").
                    None = no filter, searches all folders.
 
        Returns:
            List of (folder, email_id) tuples, empty if nothing found.
        """
        if not self.mail:
            self._connected()
 
        # Determine which folders to search
        if label is None:
            folders = self._get_all_folders()
            logger.info("No label specified → searching ALL %d folders.", len(folders))
        else:
            folders = [label]
            logger.info("Searching only in folder: '%s'", label)
 
        search_criteria = f'(FROM "{sender}")'
        all_results = []  # list of (folder, email_id) tuples
 
        for folder in folders:
            # Quote the folder name — required for names containing spaces or slashes
            quoted_folder = f'"{folder}"'

            status, _ = self.mail.select(quoted_folder, readonly=True)
            if status != "OK":
                logger.debug("Skipping folder '%s' (could not open).", folder)
                continue

            status, data = self.mail.search(None, search_criteria)
            if status != "OK" or not data[0]:
                continue

            ids = data[0].split()
            logger.info("  '%s': %d match(es)", folder, len(ids))

            for email_id in ids:
                all_results.append((folder, email_id))

        logger.info("Total: %d email(s) found.", len(all_results))
        return all_results
    

    def get_email_metadata(self, folder: str, email_id: bytes) -> dict:
        """
        Fetches only metadata (date, subject, seen/unseen) without downloading the full email.

        Args:
            folder:   The folder the email is in (from search_emails results).
            email_id: The email ID as bytes (from search_emails results).

        Returns:
            Dict with keys: "id", "folder", "date", "subject", "read"
        """
        self.mail.select(f'"{folder}"', readonly=True)

        # ENVELOPE = lightweight header info (date, subject, from, to ...)
        # FLAGS     = e.g. \\Seen, \\Answered, \\Flagged
        status, data = self.mail.fetch(email_id, "(FLAGS ENVELOPE)")
        if status != "OK":
            logger.warning("Could not fetch metadata for email %s.", email_id)
            return {}

        raw = data[0].decode()

        # FLAGS: check if \Seen is present
        is_read = "\\Seen" in raw

        # ENVELOPE: date is the second quoted field
        # Format: ENVELOPE ("date" "subject" ...)
        parts = raw.split('"')
        date    = parts[1] if len(parts) > 1 else "unknown"
        subject = parts[3] if len(parts) > 3 else "unknown"

        return {
            "id":      email_id.decode(),
            "folder":  folder,
            "date":    date,
            "subject": subject,
            "read":    is_read,
        }
    
    # ──────────────────────────────────────────
    # FETCH ATTACHMENTS INTO RAM
    #
    # Instead of writing to disk, we use io.BytesIO —
    # a file-like object that lives only in memory.
    # It behaves exactly like open(..., "rb") but nothing
    # is ever written to the hard drive.
    # ──────────────────────────────────────────

    def fetch_attachments_to_ram(
        self,
        email_results: list,        # from search_emails() → [(folder, id), ...]
        target_filename: str,
    ) -> list[dict]:
        """
        Loads matching attachments directly into RAM (no disk writes).
 
        Args:
            email_results:   List of (folder, email_id) tuples from search_emails().
            target_filename: Name of the attachment to look for (e.g. "secure-email.html").
 
        Returns:
            List of dicts: [{"filename": str, "data": io.BytesIO}, ...]
            Call attachment["data"].read() to get the raw bytes.
        """
        found = []
 
        for folder, email_id in email_results:
            # Re-select the folder so we can fetch from it
            self.mail.select(folder, readonly=True)
 
            status, msg_data = self.mail.fetch(email_id, "(RFC822)")
            if status != "OK":
                logger.warning("Could not fetch email %s.", email_id)
                continue
 
            msg = email.message_from_bytes(msg_data[0][1])
            subject = msg.get("Subject", "(no subject)")
            logger.info("Checking: '%s' (folder: %s)", subject, folder)
 
            for part in msg.walk():
                if "attachment" not in part.get("Content-Disposition", ""):
                    continue
 
                filename = part.get_filename()
                if not filename:
                    continue
 
                if filename.lower() != target_filename.lower():
                    logger.debug("Skipping attachment '%s'.", filename)
                    continue
 
                # Write the attachment bytes into a RAM buffer instead of a file
                buffer = io.BytesIO(part.get_payload(decode=True))
                buffer.seek(0)  # reset read position to the beginning
 
                logger.info(
                    "✓ '%s' loaded into RAM (%d bytes)",
                    filename,
                    buffer.getbuffer().nbytes,
                )
                found.append({"filename": filename, "data": buffer})
 
        if not found:
            logger.warning("No attachment named '%s' was found.", target_filename)
 
        return found