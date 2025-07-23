# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['gui_app.py'],
    pathex=[],
    binaries=[],
    datas=[('.env', '.')],
    hiddenimports=['PyQt5', 'matplotlib', 'pandas', 'numpy', 'websocket', 'binance'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['notebook', 'IPython', 'jupyter', 'scipy', 'sklearn', 'conda', 'dask', 'numba', 'bokeh', 'panel', 'plotly'],
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

app = BUNDLE(
    exe,
    name='GeniusCoinManager.app',
    bundle_identifier='com.genius.coinmanager',
)