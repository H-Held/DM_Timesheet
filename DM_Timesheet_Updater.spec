# DM_Timesheet_Updater.spec — PyInstaller build recipe for the autostart
# updater/launcher.
#
# Build with:   pyinstaller DM_Timesheet_Updater.spec
# Result:       dist/DM_Timesheet_Updater.exe
#
# Put this .exe (or a shortcut to it) into the Windows Startup folder
# (Win+R -> shell:startup) on the Festrechner. On every login it checks the
# git repo for updates, pulls + installs them if found, then launches
# programm/main.py through the venv's pythonw.exe — no console window ever
# appears. See updater/updater.py for the logic and setup_festrechner.ps1 for
# one-time provisioning.
#
# Uses only the Python standard library, so no collect_all() hooks are needed.

a = Analysis(
    ["updater/updater.py"],
    pathex=["updater"],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    name="DM_Timesheet_Updater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # windowed — no terminal in normal operation
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
