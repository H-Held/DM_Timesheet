# DM Timesheet

Automates the monthly **dm** payroll workflow:

1. Downloads the encrypted "Zeitnachweis" (timesheet) e-mails from **Gmail**.
2. Decrypts the **SEPPmail** secure-mail attachments.
3. Sorts the resulting PDFs into a tidy `DM/{year}/{type}/` folder structure.
4. Syncs every Zeitnachweis into **Google Calendar** — one event per shift,
   colored grey for past shifts and violet for upcoming ones, with reminders.

---

## Project layout

```
DM_Timesheet/
├── programm/                 # e-mail, decryption, PDF, and entry point
│   ├── main.py               #   ← run this
│   ├── app_paths.py          # finds .env / credentials whether source or .exe
│   ├── environment_loader.py # reads settings from .env
│   ├── email_reader.py       # Gmail IMAP access
│   ├── seppmail_decryptor.py # decrypts SEPPmail secure-email.html
│   ├── file_organizer.py     # sorts & deduplicates downloaded PDFs
│   ├── rewrite_creation_date.py
│   └── zeitnachweis_parser.py# parses a timesheet PDF into structured rows
├── kalender_reader/          # Google Calendar code
│   ├── calendar_sync.py      # turns parsed timesheets into calendar events
│   └── google_calendar.py    # reusable Google Calendar API wrapper
├── requirements.txt
├── DM_Timesheet.spec         # PyInstaller build recipe
└── README.md
```

---

## Setup

### 1. Install dependencies

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Create `programm/.env`

```ini
GMAIL=your_email@gmail.com
APP_PASSKEY=your_gmail_app_password          # Gmail "App password", not your login
SEPPMAIL_PASSWORD=your_seppmail_password

EMAIL_SENDER=MA-S+B-MitarbeiterSysteme.DE-Mailbox@dm.de
EMAIL_SUBJECT=dmSAP Nachweise: Ihre angeforderten Dokumente

DOWNLOAD_DIR=C:/Users/You/Documents/Arbeit   # where PDFs are stored
```

> The Gmail **App password** is created at
> <https://myaccount.google.com/apppasswords> (requires 2-factor auth).

### 3. Add Google Calendar credentials

Place `credentials.json` (an **OAuth client ID** of type *Desktop app*,
downloaded from the [Google Cloud Console](https://console.cloud.google.com/)
→ *APIs & Services* → *Credentials*) into `kalender_reader/`.

On the first calendar sync a browser window opens for you to grant access.
The login is then cached in `kalender_reader/token.pickle`.

---

## Running

```powershell
# Standard: download new inbox e-mails, decrypt, sort, sync (with reminders)
python programm/main.py --mode standard

# Full: skip e-mail, re-sync every saved Zeitnachweis PDF (no reminders)
python programm/main.py --mode full
```

---

## Logging

Every run writes to `dm_downloader.log` — next to `DM_Timesheet.exe` when
running the packaged app, or at the project root when running from source
(resolved via `app_paths.py`, just like `.env`/`credentials.json`).

- **File** (`dm_downloader.log`): full `DEBUG` detail — every step, including
  per-day sync decisions and full tracebacks for any error.
- **Console**: only `INFO` and above — a concise progress view.
- Both `standard` and `full` mode log a `Starting run — mode=...` line at the
  very start, so you can always tell which mode a given run used.
- The file **rotates automatically** at ~2 MB, keeping the last 3 archives
  (`dm_downloader.log.1`, `.2`, `.3`) — it never grows without bound.
- **Calendar sync:** `+` created, `~` updated and `-` removed events are logged
  at `INFO`; unchanged days only at `DEBUG` (with the reason whenever something
  *is* changed, e.g. `color mismatch`), so the `INFO` level stays readable.
- **Nothing to do:** when a run changes nothing you get an explicit line, e.g.
  `[full_sync] Complete: no changes — everything already up to date` or
  `No new PDFs — nothing to do`.

If something goes wrong, `dm_downloader.log` is the first place to look: it
contains the full DEBUG trail plus the complete traceback of any error, even
ones that only showed a short message on screen.

---

## Troubleshooting

### `invalid_grant: Bad Request` during calendar sync

This means the saved Google login (`token.pickle`) can no longer be refreshed.
The program now handles this automatically: it deletes the stale token and
opens a fresh browser login the next time you run it.

**Permanent fix:** the error keeps coming back every ~7 days while your Google
OAuth app is in **"Testing"** publishing status, because Google expires refresh
tokens for test apps after one week. To stop it for good:

> Google Cloud Console → *APIs & Services* → *OAuth consent screen* →
> set **Publishing status** to **In production**.

After that, the cached token stays valid indefinitely.

### `credentials.json not found`

Download the OAuth client from the Google Cloud Console and put it in
`kalender_reader/` (running from source) or next to `DM_Timesheet.exe`
(running the packaged app).

---

## Building a standalone `.exe`

```powershell
pip install pyinstaller          # already in requirements.txt
pyinstaller DM_Timesheet.spec
```

The result is `dist/DM_Timesheet.exe`. It contains only code — copy these three
files **next to the .exe** before running it:

| File               | Purpose                                            |
| ------------------ | -------------------------------------------------- |
| `.env`             | your settings / passwords                          |
| `credentials.json` | Google OAuth client                                |
| `token.pickle`     | created automatically after the first login        |

Then run it like the script:

```powershell
.\DM_Timesheet.exe --mode full
```

`app_paths.py` automatically reads these files from the executable's folder
when frozen, and from the project tree when running from source — no code
changes needed between the two.
