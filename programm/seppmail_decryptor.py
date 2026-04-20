import re
import requests
import logging
from dataclasses import dataclass
from urllib.parse import urlparse
from bs4 import BeautifulSoup

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

        # Only individual file downloads: op=access, access=part, path != "all"
        if inputs.get("op") != "access":
            continue
        if inputs.get("access") != "part":
            continue
        if inputs.get("path") == "all":
            # "Alle Anhänge herunterladen" ZIP button — skip
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


def download_attachments(result: SEPPMailResult, save_dir: str = ".") -> list[str]:
    """
    Downloads all individual PDF attachments from the decrypted email.
    Must reuse the SEPPMailResult from decrypt_secure_email() —
    the session contains the active server cookie.

    Returns:
        List of saved file paths.
    """
    import os
    os.makedirs(save_dir, exist_ok=True)

    attachments  = parse_attachments(result)
    download_url = f"{result.base_url}/web.app"
    saved_files  = []

    for att in attachments:
        logger.info("Downloading: '%s' ...", att["filename"])
        response = result.session.post(download_url, data=att["payload"], timeout=30)
        response.raise_for_status()

        save_path = os.path.join(save_dir, att["filename"])
        with open(save_path, "wb") as f:
            f.write(response.content)

        logger.info("✓ Saved: %s (%d bytes)", save_path, len(response.content))
        saved_files.append(save_path)

    return saved_files