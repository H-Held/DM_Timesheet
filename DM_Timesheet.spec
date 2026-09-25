# DM_Timesheet.spec — PyInstaller build recipe for a single-file Windows .exe
#
# Build with:   pyinstaller DM_Timesheet.spec
# Result:       dist/DM_Timesheet.exe
#
# The .exe contains only code. At runtime it reads three user files from the
# folder it is started in (see app_paths.py):
#     .env                 — your settings / passwords
#     credentials.json     — Google OAuth client (from Google Cloud Console)
#     token.pickle         — created automatically after the first login
# Keep those next to DM_Timesheet.exe; do NOT bundle them into the binary.

from PyInstaller.utils.hooks import collect_all

# These packages ship data files / dynamic submodules that PyInstaller cannot
# always discover on its own, so collect everything they need explicitly.
_datas, _binaries, _hiddenimports = [], [], []
for _pkg in (
    "googleapiclient",
    "google_auth_oauthlib",
    "google_auth_httplib2",
    "pdfplumber",
    "pdfminer",
    "pikepdf",
):
    _d, _b, _h = collect_all(_pkg)
    _datas += _d
    _binaries += _b
    _hiddenimports += _h

# pywin32 modules used by rewrite_creation_date.py are imported lazily.
_hiddenimports += ["win32file", "win32timezone", "pywintypes"]


a = Analysis(
    ["programm/main.py"],
    pathex=["programm", "kalender_reader"],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DM_Timesheet",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # keep the console window so you can see the log output
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
