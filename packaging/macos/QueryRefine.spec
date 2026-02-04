# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for QueryRefine CLI application.
Builds a standalone macOS executable bundle.
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect all data files from query_refinement_module
datas = []
datas += collect_data_files('query_refinement_module')

# Collect tokenizer data for Anthropic (if using prompt caching)
try:
    import anthropic
    anthropic_path = os.path.dirname(anthropic.__file__)
    tokenizer_file = os.path.join(anthropic_path, 'lib', 'anthropic_tokenizer.json')
    if os.path.exists(tokenizer_file):
        datas.append((tokenizer_file, 'anthropic/lib'))
except ImportError:
    pass

# Collect all submodules
hiddenimports = []
hiddenimports += collect_submodules('query_refinement_module')
hiddenimports += collect_submodules('litellm')
hiddenimports += collect_submodules('sqlalchemy')
hiddenimports += collect_submodules('pydantic')
hiddenimports += collect_submodules('jinja2')
hiddenimports += ['anthropic', 'openai', 'tiktoken', 'anthropic_tokenizer']

a = Analysis(
    ['cli_entrypoint.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'PIL', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
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
    bundle_identifier='com.queryrefine.app',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': 'True',
        'CFBundleShortVersionString': '1.0.0',
    },
)
