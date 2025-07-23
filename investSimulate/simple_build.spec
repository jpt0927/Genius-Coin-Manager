# -*- mode: python ; coding: utf-8 -*-

import os
import sys

block_cipher = None

# 현재 경로
current_dir = os.path.dirname(os.path.abspath(SPECPATH))

a = Analysis(
    ['gui_app.py'],  # main_unified.py 대신 gui_app.py로 먼저 시도
    pathex=[current_dir],
    binaries=[],
    datas=[
        ('.env', '.') if os.path.exists('.env') else ('config.py', '.'),
    ],
    hiddenimports=[
        'PyQt5',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.QtWebEngineWidgets',
        'matplotlib',
        'matplotlib.backends.backend_qt5agg',
        'pandas',
        'numpy',
        'websocket',
        'websocket-client',
        'python-binance',
        'binance',
        'dotenv',
        'asyncio',
        'aiohttp',
        'ta',
        'requests',
        'urllib3',
        'certifi',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GeniusCoinManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# macOS 앱 번들
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='GeniusCoinManager.app',
        bundle_identifier='com.genius.coinmanager',
        info_plist={
            'CFBundleName': 'Genius Coin Manager',
            'CFBundleDisplayName': 'Genius Coin Manager',
            'CFBundleVersion': '1.0.0',
            'CFBundleShortVersionString': '1.0.0',
            'NSHighResolutionCapable': True,
        },
    )