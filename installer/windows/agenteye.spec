# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec file for Agent Eye (Windows)
#
# Build with:
#   pyinstaller installer/windows/agenteye.spec
#
# Output: dist/AgentEye/AgentEye.exe (directory bundle)
#
# Prerequisites:
#   pip install pyinstaller
#   pip install -r requirements.txt
#   (frontend must be built first: cd frontend && npm run build)

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Project root is two levels up from this spec file
project_root = Path(SPECPATH).parent.parent

# ── Data files ────────────────────────────────────────────────────────────────
# Include the pre-built frontend (static/dist) and icon assets.
datas = [
    (str(project_root / "src" / "static"), "src/static"),
]

# Collect uvicorn/fastapi data (templates, etc.)
datas += collect_data_files("uvicorn")
datas += collect_data_files("fastapi")

# ── Hidden imports ────────────────────────────────────────────────────────────
# Modules imported dynamically at runtime that PyInstaller cannot detect.
hiddenimports = [
    # FastAPI / Starlette internals
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "starlette.routing",
    # Windows-specific (pywin32)
    "win32api",
    "win32con",
    "win32gui",
    "win32process",
    "pywintypes",
    "winreg",
    # Tray / webview
    "pystray._win32",
    "PIL._tkinter_finder",
    # Agent Eye modules (dynamic imports in session_dashboard.py)
    "src.dashboard_api",
    "src.tray_app",
    "src.macos_app",
    "src.sync",
    "src.scout",
    "src.grouping",
    "src.process_tracker",
    "src.models",
    "src.schemas",
    "src.constants",
    "src.logging_config",
    "src.__version__",
]

hiddenimports += collect_submodules("src")
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("starlette")

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [str(project_root / "src" / "session_dashboard.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # macOS-only modules
        "AppKit",
        "Foundation",
        "objc",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AgentEye",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                 # no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "src" / "static" / "tray-icon.ico"),
    version=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AgentEye",
)
