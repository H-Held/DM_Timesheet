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

    def search_emails(self, sender: str, subject: str = None, label: str = None) -> list[tuple]:
        """
        Searches for emails from a specific sender, optionally filtered by subject.

        Uses IMAP UIDs (not sequence numbers) so results stay valid even after
        expunge() is called during processing.

        Args:
            sender:  Sender email address.
            subject: Required subject text (IMAP SUBJECT filter). None = no filter.
            label:   Folder/label to search. None = all folders.

        Returns:
            List of (folder, uid_bytes) tuples.
            uid_bytes is a UID string encoded as bytes, e.g. b'1234'.
        """
        if not self.mail:
            logger.error("Not connected! Call connect() first.")
            return []

        folders = self._get_all_folders() if label is None else [label]
        if label is None:
            logger.info("No label → searching ALL %d folders.", len(folders))
        else:
            logger.info("Searching in folder: '%s'", label)

        criteria = [f'FROM "{sender}"']
        if subject:
            criteria.append(f'SUBJECT "{subject}"')
        search_criteria = "(" + " ".join(criteria) + ")"
        logger.debug("IMAP search criteria: %s", search_criteria)
        all_results = []

        for folder in folders:
            status, _ = self._select(folder, readonly=True)
            if status != "OK":
                logger.debug("Skipping folder '%s'.", folder)
                continue

            # UID SEARCH instead of plain SEARCH — UIDs never shift after expunge
            status, data = self.mail.uid("search", None, search_criteria)
            if status != "OK" or not data[0]:
                continue

            uids = data[0].split()
            logger.info("  '%s': %d match(es)", folder, len(uids))
            for uid in uids:
                all_results.append((folder, uid))

        logger.info("Total: %d email(s) found.", len(all_results))
        return all_results

    # ──────────────────────────────────────────
    # Metadata
    # ──────────────────────────────────────────

    def get_email_metadata(self, folder: str, email_uid: bytes) -> dict:
        """Fetches date, subject and read/unread status via UID (no body download)."""
        self._select(folder, readonly=True)
        status, data = self.mail.uid("fetch", email_uid, "(FLAGS ENVELOPE)")
        if status != "OK" or not data or data[0] is None:
            logger.warning("Could not fetch metadata for UID %s in '%s'.", email_uid.decode(), folder)
            return {}

        raw     = data[0].decode()
        is_read = "\\Seen" in raw
        parts   = raw.split('"')

        return {
            "id":      email_uid.decode(),
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

    def mark_as_read(self, folder: str, email_uid: bytes):
        """Marks an email as read (adds \\Seen flag)."""
        self._select(folder, readonly=False)
        self.mail.uid("store", email_uid, "+FLAGS", "\\Seen")
        logger.info("Marked as READ — folder: %s | UID: %s", folder, email_uid.decode())

    def mark_as_unread(self, folder: str, email_uid: bytes):
        """Marks an email as unread (removes \\Seen flag)."""
        self._select(folder, readonly=False)
        self.mail.uid("store", email_uid, "-FLAGS", "\\Seen")
        logger.info("Marked as UNREAD — folder: %s | UID: %s", folder, email_uid.decode())

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
            logger.debug("Label '%s' not created (already exists or IMAP refused).", label_name)
            return False

    def add_label(self, folder: str, email_uid: bytes, label_name: str):
        """
        Adds a Gmail label to an email by copying it into that label's folder.

        In Gmail, an email can have multiple labels simultaneously —
        copying to a label folder does NOT remove it from the original.

        Args:
            folder:     Current folder of the email (e.g. "INBOX").
            email_uid:  Email UID as bytes.
            label_name: Label to add (e.g. "dm_processed").
        """
        self._select(folder, readonly=False)
        status, _ = self.mail.uid("copy", email_uid, f'"{label_name}"')
        if status == "OK":
            logger.info(
                "Label '%s' added — folder: %s | UID: %s",
                label_name, folder, email_uid.decode(),
            )
        else:
            logger.warning("Could not add label '%s'. Does it exist?", label_name)

    def remove_label(self, label_name: str, email_uid: bytes):
        """
        Removes a Gmail label from an email by deleting it from that label's folder.

        This does NOT delete the email — it only removes the label.
        The email stays in any other labels it has.

        Uses UID STORE so the correct message is targeted even if other messages
        were expunged earlier in the same session (sequence numbers would have shifted).

        Args:
            label_name: Label to remove (e.g. "INBOX" or "dm_processed").
            email_uid:  Email UID as bytes — must be the UID valid in label_name's folder.
        """
        status, _ = self._select(label_name, readonly=False)
        if status != "OK":
            logger.warning("Could not open label '%s'.", label_name)
            return

        # After selecting the new folder the UID is the same (Gmail uses global UIDs
        # per-message across labels), so uid("store") hits the right message.
        self.mail.uid("store", email_uid, "+FLAGS", "\\Deleted")
        self.mail.expunge()
        logger.info("Label '%s' removed from UID %s.", label_name, email_uid.decode())

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
        Uses UID FETCH to stay stable across expunge() calls.

        Returns:
            List of {"filename": str, "data": io.BytesIO}
        """
        found = []

        for folder, email_uid in email_results:
            self._select(folder, readonly=True)

            status, msg_data = self.mail.uid("fetch", email_uid, "(RFC822)")
            if status != "OK" or not msg_data or msg_data[0] is None:
                logger.warning("Could not fetch email UID %s.", email_uid)
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
                logger.info("[OK] '%s' loaded into RAM (%d bytes)", filename, buffer.getbuffer().nbytes)
                found.append({"filename": filename, "data": buffer})

        if not found:
            logger.warning("No attachment named '%s' found.", target_filename)
        return found