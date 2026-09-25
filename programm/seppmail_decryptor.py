import os
import re
import requests
import logging
from dataclasses import dataclass
from urllib.parse import urlparse
from bs4 import BeautifulSoup

import file_organizer

logger = logging.getLogger(__name__)


@dataclass
class SEPPMailResult:
    """
    Holds everything returned after a successful decryption.
    The session must stay alive to download attachments —
    all three fields are needed together.
    """
    html:     str
    session:  requests.Session  # active HTTP session (keeps server cookie alive)
    base_url: str               # e.g. "https://securemail.dm.de"


def decrypt_secure_email(html_bytes: bytes, password: str) -> SEPPMailResult:
    """
    Decrypts a SEPPmail secure-email.html in two HTTP steps.

        Step 1 — Init (OK button):
            POST all secmail chunks to web.app?op=init
            → Server returns login form

        Step 2 — Login (password form):
            POST password + session tokens
            → Server returns decrypted email HTML
    """
    soup = BeautifulSoup(html_bytes, "html.parser")

    # ── Step 1 ────────────────────────────────
    init_form = soup.find("form", action=lambda a: a and "op=init" in a)
    if not init_form:
        raise ValueError("Could not find init form (op=init) in secure-email.html")

    init_url     = init_form["action"]
    init_payload = {
        inp["name"]: inp.get("value", "")
        for inp in init_form.find_all("input", {"type": "hidden"})
        if inp.get("name")
    }

    logger.info("Step 1 — Sending encrypted chunks to: %s", init_url)
    logger.debug("Init fields: %d total, keys: %s", len(init_payload), list(init_payload.keys())[:5])

    http      = requests.Session()
    response1 = http.post(init_url, data=init_payload, timeout=30)
    response1.raise_for_status()
    logger.info("Step 1 OK — %d bytes", len(response1.content))

    # ── Step 2 ────────────────────────────────
    soup2      = BeautifulSoup(response1.text, "html.parser")
    login_form = soup2.find("form", id="loginForm")
    if not login_form:
        raise ValueError("Login form not found in server response.")

    parsed    = urlparse(init_url)
    base_url  = f"{parsed.scheme}://{parsed.netloc}"
    action    = login_form.get("action", "web.app")
    login_url = f"{base_url}/{action.lstrip('/')}"

    login_payload = {
        inp["name"]: inp.get("value", "")
        for inp in login_form.find_all("input", {"type": "hidden"})
        if inp.get("name")
    }
    login_payload["password"] = password

    logger.info("Step 2 — Posting password to: %s", login_url)
    response2 = http.post(login_url, data=login_payload, timeout=30)
    response2.raise_for_status()
    logger.info("Step 2 OK — %d bytes, decryption complete", len(response2.content))

    return SEPPMailResult(html=response2.text, session=http, base_url=base_url)


def parse_attachments(result: SEPPMailResult) -> list[dict]:
    """
    Parses all individual PDF attachments from the decrypted email.
    Skips the "Alle Anhänge herunterladen" ZIP button (path=all).

    Returns:
        List of {"filename": str, "payload": dict}
    """
    soup        = BeautifulSoup(result.html, "html.parser")
    attachments = []

    for form in soup.find_all("form"):
        inputs = {
            i["name"]: i.get("value", "")
            for i in form.find_all("input")
            if i.get("name")
        }

        if inputs.get("op") != "access":
            continue
        if inputs.get("access") != "part":
            continue
        if inputs.get("path") == "all":
            logger.debug("Skipping ZIP download button (path=all).")
            continue

        btn      = form.find("button")
        raw_text = btn.get_text(separator=" ", strip=True) if btn else ""
        filename = re.sub(r"Datei herunterladen\s*", "", raw_text)
        filename = re.sub(r"\s*\(\d+\.?\d*\s*KB\)\s*$", "", filename).strip()

        if not filename:
            filename = f"attachment_{inputs.get('path','?').replace('/','_')}.pdf"

        attachments.append({"filename": filename, "payload": inputs})
        logger.debug("Found: '%s' (path: %s)", filename, inputs.get("path"))

    logger.info("Found %d individual attachment(s).", len(attachments))
    return attachments


def download_attachments(
    result: SEPPMailResult,
    base_dir: str = ".",
    attachments: list[dict] | None = None,
) -> list[str]:
    """
    Downloads all individual PDF attachments from the decrypted email into RAM,
    then delegates sorting, renaming and duplicate-prevention to file_organizer.

    Args:
        result:      SEPPMailResult from decrypt_secure_email().
        base_dir:    Root download directory (DOWNLOAD_DIR from .env).
                     Files land in base_dir/DM/{year}/{type}/ or base_dir/DM/andere/.
        attachments: Already-parsed attachments from parse_attachments(); parsed
                     here if omitted.

    Returns:
        List of saved file paths.
    """
    if attachments is None:
        attachments = parse_attachments(result)
    download_url = f"{result.base_url}/web.app"
    saved_files  = []

    for att in attachments:
        filename = att["filename"]
        logger.info("Downloading into RAM: '%s' ...", filename)

        response = result.session.post(download_url, data=att["payload"], timeout=30)
        response.raise_for_status()

        saved = file_organizer.organize_file(response.content, filename, base_dir)
        if saved:
            logger.info("[OK] %s", saved)
            saved_files.append(saved)
        else:
            logger.info("  [SKIP] Existing file is newer: '%s'", filename)

    return saved_files