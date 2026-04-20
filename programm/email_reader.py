import imaplib
import email
import logging
import io

logger = logging.getLogger(__name__)


class GmailReader:

    def __init__(self, gmail_address: str, passkey: str):
        self.gmail_address = gmail_address
        self.passkey       = passkey
        self.mail          = None
        self._connected    = False

    # ──────────────────────────────────────────
    # Connect & Disconnect
    # ──────────────────────────────────────────

    def connect(self):
        """Opens an SSL connection to Gmail's IMAP server and logs in."""
        if not self._connected:
            logger.info("Connecting to imap.gmail.com ...")
            self.mail = imaplib.IMAP4_SSL("imap.gmail.com")
            self.mail.login(self.gmail_address, self.passkey)
            self._connected = True
            logger.info("Valid connection as: %s", self.gmail_address)
        else:
            logger.info("Already connected as: %s", self.gmail_address)

    def disconnect(self):
        """Closes the connection cleanly."""
        if self.mail:
            self.mail.logout()
            self._connected = False
            logger.info("Disconnected.")

    # ──────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────

    def _select(self, folder: str, readonly: bool = False):
        """Selects a folder, quoting the name correctly for IMAP."""
        return self.mail.select(f'"{folder}"', readonly=readonly)

    def _get_all_folders(self) -> list[str]:
        """Returns a list of all folders/labels in the mailbox."""
        status, folders = self.mail.list()
        if status != "OK":
            logger.warning("Could not retrieve folder list.")
            return []

        folder_names = []
        for folder in folders:
            decoded = folder.decode()
            name    = decoded.split('"')[-2]
            folder_names.append(name)

        logger.debug("Available folders: %s", folder_names)
        return folder_names

    # ──────────────────────────────────────────
    # Search emails
    # ──────────────────────────────────────────

    def search_emails(self, sender: str, label: str = None) -> list[tuple]:
        """
        Searches for emails from a specific sender.

        Args:
            sender: Sender email address.
            label:  Folder/label to search. None = all folders.
                    Use "INBOX" to avoid duplicates.

        Returns:
            List of (folder, email_id) tuples.
        """
        if not self.mail:
            logger.error("Not connected! Call connect() first.")
            return []

        folders = self._get_all_folders() if label is None else [label]
        if label is None:
            logger.info("No label → searching ALL %d folders.", len(folders))
        else:
            logger.info("Searching in folder: '%s'", label)

        search_criteria = f'(FROM "{sender}")'
        all_results     = []

        for folder in folders:
            status, _ = self._select(folder, readonly=True)
            if status != "OK":
                logger.debug("Skipping folder '%s'.", folder)
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

    # ──────────────────────────────────────────
    # Metadata
    # ──────────────────────────────────────────

    def get_email_metadata(self, folder: str, email_id: bytes) -> dict:
        """Fetches date, subject and read/unread status (no body download)."""
        self._select(folder, readonly=True)
        status, data = self.mail.fetch(email_id, "(FLAGS ENVELOPE)")
        if status != "OK":
            return {}

        raw     = data[0].decode()
        is_read = "\\Seen" in raw
        parts   = raw.split('"')

        return {
            "id":      email_id.decode(),
            "folder":  folder,
            "date":    parts[1] if len(parts) > 1 else "unknown",
            "subject": parts[3] if len(parts) > 3 else "unknown",
            "read":    is_read,
        }

    # ──────────────────────────────────────────
    # Read / Unread
    #
    # IMAP flags work with +FLAGS (add) and -FLAGS (remove).
    # \Seen = read,  removing it = unread.
    # Important: select WITHOUT readonly=True to allow changes.
    # ──────────────────────────────────────────

    def mark_as_read(self, folder: str, email_id: bytes):
        """Marks an email as read (adds \\Seen flag)."""
        self._select(folder, readonly=False)  # must NOT be readonly to modify
        self.mail.store(email_id, "+FLAGS", "\\Seen")
        logger.info("Marked as READ — folder: %s | ID: %s", folder, email_id.decode())

    def mark_as_unread(self, folder: str, email_id: bytes):
        """Marks an email as unread (removes \\Seen flag)."""
        self._select(folder, readonly=False)
        self.mail.store(email_id, "-FLAGS", "\\Seen")
        logger.info("Marked as UNREAD — folder: %s | ID: %s", folder, email_id.decode())

    # ──────────────────────────────────────────
    # Gmail Labels
    #
    # In Gmail's IMAP, labels are folders.
    # Adding a label = copying the email into that folder.
    # Removing a label = selecting that folder and deleting from it.
    # Creating a label = creating a new IMAP folder.
    #
    # Note: Gmail's IMAP shows labels as folders, so
    # "INBOX", "dm", "work" etc. all appear as selectable folders.
    # ──────────────────────────────────────────

    def create_label(self, label_name: str) -> bool:
        """
        Creates a new Gmail label (= IMAP folder).

        Args:
            label_name: Name of the new label (e.g. "dm_processed").

        Returns:
            True if created successfully, False if already exists or failed.
        """
        status, _ = self.mail.create(f'"{label_name}"')
        if status == "OK":
            logger.info("Label created: '%s'", label_name)
            return True
        else:
            logger.warning("Could not create label '%s' (may already exist).", label_name)
            return False

    def add_label(self, folder: str, email_id: bytes, label_name: str):
        """
        Adds a Gmail label to an email by copying it into that label's folder.

        In Gmail, an email can have multiple labels simultaneously —
        copying to a label folder does NOT remove it from the original.

        Args:
            folder:     Current folder of the email (e.g. "INBOX").
            email_id:   Email ID as bytes.
            label_name: Label to add (e.g. "dm_processed").
        """
        self._select(folder, readonly=False)
        status, _ = self.mail.copy(email_id, f'"{label_name}"')
        if status == "OK":
            logger.info(
                "Label '%s' added — folder: %s | ID: %s",
                label_name, folder, email_id.decode(),
            )
        else:
            logger.warning("Could not add label '%s'. Does it exist?", label_name)

    def remove_label(self, label_name: str, email_id: bytes):
        """
        Removes a Gmail label from an email by deleting it from that label's folder.

        This does NOT delete the email — it only removes the label.
        The email stays in INBOX and any other labels it has.

        Args:
            label_name: Label to remove (e.g. "dm_processed").
            email_id:   Email ID as bytes.
        """
        # Select the label folder and mark for deletion, then expunge
        status, _ = self._select(label_name, readonly=False)
        if status != "OK":
            logger.warning("Could not open label '%s'.", label_name)
            return

        self.mail.store(email_id, "+FLAGS", "\\Deleted")
        self.mail.expunge()
        logger.info("Label '%s' removed from email %s.", label_name, email_id.decode())

    def list_labels(self) -> list[str]:
        """
        Returns all existing Gmail labels (= all IMAP folders).
        Filters out Gmail system folders like [Gmail]/Spam etc.
        """
        all_folders = self._get_all_folders()
        # Filter out Gmail system folders (they start with [Gmail])
        user_labels = [f for f in all_folders if not f.startswith("[Gmail]")]
        logger.info("User labels: %s", user_labels)
        return user_labels

    # ──────────────────────────────────────────
    # Attachment download into RAM
    # ──────────────────────────────────────────

    def fetch_attachments_to_ram(
        self,
        email_results: list[tuple],
        target_filename: str,
    ) -> list[dict]:
        """
        Loads a named attachment from emails directly into RAM (no disk write).

        Returns:
            List of {"filename": str, "data": io.BytesIO}
        """
        found = []

        for folder, email_id in email_results:
            self._select(folder, readonly=True)

            status, msg_data = self.mail.fetch(email_id, "(RFC822)")
            if status != "OK":
                logger.warning("Could not fetch email %s.", email_id)
                continue

            msg     = email.message_from_bytes(msg_data[0][1])
            subject = msg.get("Subject", "(no subject)")
            logger.info("Checking: '%s' (folder: %s)", subject, folder)

            for part in msg.walk():
                if "attachment" not in part.get("Content-Disposition", ""):
                    continue
                filename = part.get_filename()
                if not filename:
                    continue
                if filename.lower() != target_filename.lower():
                    logger.debug("Skipping '%s'.", filename)
                    continue

                buffer = io.BytesIO(part.get_payload(decode=True))
                buffer.seek(0)
                logger.info("✓ '%s' loaded into RAM (%d bytes)", filename, buffer.getbuffer().nbytes)
                found.append({"filename": filename, "data": buffer})

        if not found:
            logger.warning("No attachment named '%s' found.", target_filename)
        return found