import io
import os
import re
import pikepdf
import pdfplumber
import platform
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def set_pdf_date(full_path: str, dt: datetime) -> None:
    """
    Setzt das Datum einer PDF-Datei vollständig:
    - PDF-interne Metadaten (CreationDate, ModDate)
    - Windows-Dateisystem-Timestamps (Erstellungs-, Zugriffs-, Änderungsdatum)

    Use this when the PDF's own /CreationDate is wrong or missing (e.g.
    Zeitnachweis files, where the only reliable date is the "gedruckt am"
    text printed on the page). If the PDF's internal date is already correct
    and only the filesystem timestamp needs to match it, use
    set_filesystem_date() instead — it skips the pikepdf rewrite.
    """
    _set_pdf_internal_date(full_path, dt)
    set_filesystem_date(full_path, dt)
    logger.debug("[set_pdf_date] '%s' → %s", os.path.basename(full_path), dt.strftime("%d.%m.%Y"))


def _set_pdf_internal_date(full_path: str, dt: datetime) -> None:
    """Rewrite the PDF-internal /CreationDate and /ModDate metadata fields."""
    pdf_date = dt.strftime("D:%Y%m%d%H%M%S")
    with pikepdf.open(full_path, allow_overwriting_input=True) as pdf_file:
        pdf_file.docinfo["/CreationDate"] = pdf_date
        pdf_file.docinfo["/ModDate"]      = pdf_date
        pdf_file.save(full_path)


def set_filesystem_date(full_path: str, dt: datetime) -> None:
    """
    Set only the Windows filesystem timestamps (created/accessed/modified) to
    match ``dt`` — no PDF rewrite. Only has an effect on Windows.
    """
    if platform.system() != "Windows":
        return

    import pywintypes
    import win32file

    timestamp = pywintypes.Time(dt)
    handle    = win32file.CreateFile(
        full_path,
        win32file.GENERIC_WRITE,
        0, None,
        win32file.OPEN_EXISTING,
        win32file.FILE_ATTRIBUTE_NORMAL,
        None,
    )
    win32file.SetFileTime(handle, timestamp, timestamp, timestamp)
    handle.close()
    logger.debug("[set_filesystem_date] '%s' → %s", os.path.basename(full_path), dt.strftime("%d.%m.%Y"))


def extract_print_date(pdf_bytes: bytes) -> datetime | None:
    """
    Reads a PDF from bytes (RAM only) and searches every page for the pattern:
        gedruckt am: DD.MM.YYYY

    Returns a datetime on success, None if not found or unreadable.
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text  = page.extract_text() or ""
                match = re.search(
                    r"gedruckt am:\s*(\d{2})\.(\d{2})\.(\d{4})",
                    text,
                    re.IGNORECASE,
                )
                if match:
                    day, month, year = match.groups()
                    return datetime(int(year), int(month), int(day))
    except Exception as exc:
        logger.warning("[extract_print_date] Could not read PDF: %s", exc)
    return None


def process_zeitnachweis(pdf_bytes: bytes, filename: str, save_dir: str) -> str | None:
    """
    Processes a Zeitnachweis PDF entirely in RAM before writing anything to disk.
    (Legacy entry point — main pipeline now uses file_organizer.organize_file.)
    """
    new_date = extract_print_date(pdf_bytes)

    if new_date is None:
        logger.warning(
            "[process_zeitnachweis] No 'gedruckt am' date found in '%s' "
            "— saving without date rewrite.",
            filename,
        )
    else:
        logger.info(
            "[process_zeitnachweis] '%s' — print date: %s",
            filename,
            new_date.strftime("%d.%m.%Y"),
        )

    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, filename)

    if os.path.exists(save_path) and new_date is not None:
        try:
            with open(save_path, "rb") as f:
                existing_bytes = f.read()
            existing_date = extract_print_date(existing_bytes)
        except OSError as exc:
            logger.warning("[process_zeitnachweis] Could not read existing file: %s", exc)
            existing_date = None

        if existing_date is not None:
            logger.info(
                "[process_zeitnachweis] On-disk: %s | New: %s",
                existing_date.strftime("%d.%m.%Y"),
                new_date.strftime("%d.%m.%Y"),
            )
            if existing_date >= new_date:
                logger.info("[process_zeitnachweis] Skipped — existing is same-age or newer.")
                return None

    with open(save_path, "wb") as f:
        f.write(pdf_bytes)
    logger.info("[process_zeitnachweis] Saved: %s (%d bytes)", save_path, len(pdf_bytes))

    if new_date is not None:
        set_pdf_date(save_path, new_date)

    return save_path