"""
file_organizer.py
─────────────────
Sorts downloaded PDFs into a structured folder hierarchy:

    {DOWNLOAD_DIR}/
    └── DM/
        ├── 2025/
        │   ├── Zeitnachweis/
        │   │   └── Zeitnachweis_04_April_2025.pdf
        │   └── Entgeltnachweis/
        │       └── Entgeltnachweis_04_April_2025.pdf
        ├── 2026/
        │   └── ...
        └── andere/          ← year-independent
            └── DEÜV ....pdf

Duplicate prevention:
  - Zeitnachweis    → compares "gedruckt am" date from PDF text
  - Entgeltnachweis → compares PDF internal /CreationDate metadata
  - andere          → compares PDF internal /CreationDate metadata
"""

import io
import os
import re
import logging
import pikepdf
from datetime import datetime

import rewrite_creation_date as rwcd

logger = logging.getLogger(__name__)

GERMAN_MONTHS: dict[str, tuple[int, str]] = {
    "januar":    (1,  "Januar"),
    "februar":   (2,  "Februar"),
    "märz":      (3,  "März"),
    "april":     (4,  "April"),
    "mai":       (5,  "Mai"),
    "juni":      (6,  "Juni"),
    "juli":      (7,  "Juli"),
    "august":    (8,  "August"),
    "september": (9,  "September"),
    "oktober":   (10, "Oktober"),
    "november":  (11, "November"),
    "dezember":  (12, "Dezember"),
}


# ─────────────────────────────────────────────────────────────────────────────
# Categorisation
# ─────────────────────────────────────────────────────────────────────────────

def categorize(filename: str) -> dict:
    stem = os.path.splitext(filename)[0]

    for doc_type in ("Zeitnachweis", "Entgeltnachweis"):
        if stem.lower().startswith(doc_type.lower()):
            match = re.search(r"(\w+)\s+(\d{4})\s*$", stem)
            if match:
                month_raw, year_str = match.groups()
                month_info = GERMAN_MONTHS.get(month_raw.lower())
                if month_info:
                    month_num, month_name = month_info
                    year         = int(year_str)
                    new_filename = f"{doc_type}_{month_num:02d}_{month_name}_{year}.pdf"
                    return {
                        "type":         doc_type,
                        "year":         year,
                        "month_num":    month_num,
                        "month_name":   month_name,
                        "new_filename": new_filename,
                    }

    return {
        "type":         "andere",
        "year":         None,
        "month_num":    None,
        "month_name":   None,
        "new_filename": filename,
    }


def target_path(base_dir: str, info: dict) -> str:
    """
    DM/{year}/{type}/{new_filename}   for Zeitnachweis / Entgeltnachweis
    DM/andere/{new_filename}          for andere (year-independent)
    """
    dm = os.path.join(base_dir, "DM")

    if info["type"] == "andere":
        folder = os.path.join(dm, "andere")
    else:
        folder = os.path.join(dm, str(info["year"]), info["type"])

    return os.path.join(folder, info["new_filename"])


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pdf_creation_date(pdf_bytes: bytes) -> datetime | None:
    """Reads /CreationDate from PDF metadata (pikepdf)."""
    try:
        with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
            raw = str(pdf.docinfo.get("/CreationDate", ""))
            m   = re.match(r"D:(\d{4})(\d{2})(\d{2})", raw)
            if m:
                y, mo, d = m.groups()
                return datetime(int(y), int(mo), int(d))
    except Exception as exc:
        logger.debug("[organizer] Could not read /CreationDate: %s", exc)
    return None


def _extract_date(pdf_bytes: bytes, use_print_date: bool) -> datetime | None:
    """The one date that matters for a PDF: 'gedruckt am' for Zeitnachweis, /CreationDate otherwise."""
    if use_print_date:
        return rwcd.extract_print_date(pdf_bytes)
    return _pdf_creation_date(pdf_bytes)


def _is_newer(new_date: datetime | None, existing_path: str, use_print_date: bool) -> bool:
    """
    Returns True if new_date is strictly newer than the date of the file at
    existing_path. Falls back to True (= overwrite) when dates cannot be
    determined.
    """
    try:
        with open(existing_path, "rb") as f:
            existing_bytes = f.read()
    except OSError as exc:
        logger.warning(
            "[organizer] Could not read existing file %s for date comparison — overwriting. (%s)",
            existing_path, exc,
        )
        return True

    existing_date = _extract_date(existing_bytes, use_print_date)

    if new_date is None or existing_date is None:
        logger.debug("[organizer] Date comparison not possible — overwriting.")
        return True

    logger.info(
        "[organizer] Existing: %s | New: %s",
        existing_date.strftime("%d.%m.%Y"),
        new_date.strftime("%d.%m.%Y"),
    )
    return new_date > existing_date


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def organize_file(pdf_bytes: bytes, filename: str, base_dir: str) -> str | None:
    """
    Categorizes, renames, deduplicates and saves a PDF into the sorted
    folder structure — all from RAM, nothing written until the duplicate
    check passes.

    Returns:
        Full path of the saved file, or None if skipped (existing is newer).
    """
    info = categorize(filename)
    dest = target_path(base_dir, info)
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    doc_type       = info["type"]
    use_print_date = (doc_type == "Zeitnachweis")

    logger.info(
        "[organizer] %-40s  type=%-16s  →  %s",
        filename, doc_type, dest,
    )

    # Extracted once, reused for both the duplicate check and the metadata
    # rewrite below — previously this parsed the same PDF up to 3 times.
    new_date = _extract_date(pdf_bytes, use_print_date)

    # ── Duplicate check ───────────────────────────────────────────────────────
    if os.path.exists(dest):
        if not _is_newer(new_date, dest, use_print_date):
            logger.info("[organizer] Skipped — existing file is same-age or newer.")
            return None
        logger.info("[organizer] Replacing with newer version.")

    # ── Write to disk ─────────────────────────────────────────────────────────
    with open(dest, "wb") as f:
        f.write(pdf_bytes)
    logger.info("[organizer] Saved (%d bytes): %s", len(pdf_bytes), dest)

    # ── Sync metadata / filesystem date to the file's real date ──────────────
    if new_date is not None:
        if use_print_date:
            # Zeitnachweis: the PDF's own /CreationDate is unreliable (it's the
            # download/print time, not the timesheet's month) — rewrite it too.
            rwcd.set_pdf_date(dest, new_date)
        else:
            # Entgeltnachweis / andere: /CreationDate is already correct
            # (that's what new_date came from) — only the filesystem
            # timestamp needs to catch up, no need to re-save the PDF.
            rwcd.set_filesystem_date(dest, new_date)

    return dest