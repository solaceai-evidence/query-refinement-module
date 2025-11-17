# -*- mode: python ; coding: utf-8 -*-
"""Custom PyInstaller spec for QueryRefine macOS bundle."""

from __future__ import annotations

import os
from pathlib import Path
import sys

try:
    from PyInstaller.utils.hooks import collect_data_files
except ImportError:
    collect_data_files = None

# ``__file__`` is not defined when PyInstaller execs the spec, so use argv[0].
SPEC_DIR = Path(sys.argv[0]).resolve().parent
REPO_ROOT = SPEC_DIR.parent.parent

# Ensure packaging succeeds even before testers provide their own framework path.
os.environ.setdefault(
    "REFINEMENT_FRAMEWORK_PATH",
    str(SPEC_DIR / "sample_framework.yaml"),
)

block_cipher = None

datas = []
if collect_data_files is not None:
    datas += collect_data_files(
        "query_refinement_module",
        includes=["prompt/*"],
        excludes=None,
    )

datas += [
    (str(SPEC_DIR / "sample.env"), "."),
    (str(SPEC_DIR / "sample_framework.yaml"), "."),
    (str(SPEC_DIR / "Configure Environment.command"), "."),
    (str(SPEC_DIR / "Run Query Refine.command"), "."),
]

hiddenimports = ["litellm"]


a = Analysis(
    ['mac_launcher.py'],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='QueryRefine',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='QueryRefine',
)

app = BUNDLE(
    coll,
    name='QueryRefine.app',
    icon=None,
    bundle_identifier=None,
)
