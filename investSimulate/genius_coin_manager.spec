# -*- mode: python ; coding: utf-8 -*-
"""
Genius Coin Manager PyInstaller 빌드 스펙
.env 파일과 모든 필요한 리소스를 포함합니다.
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# 프로젝트 경로 설정
PROJECT_ROOT = os.path.dirname(os.path.abspath(SPECPATH))
BACKTEST_PATH = os.path.join(os.path.dirname(PROJECT_ROOT), 'backtest')

# 추가 파일 목록
added_files = [
    # .env 파일 (있는 경우)
    (os.path.join(PROJECT_ROOT, '.env'), '.') if os.path.exists(os.path.join(PROJECT_ROOT, '.env')) else None,
    # 설정 파일들
    (os.path.join(PROJECT_ROOT, 'config.py'), '.') if os.path.exists(os.path.join(PROJECT_ROOT, 'config.py')) else None,
    # backtest 모듈 전체
    (BACKTEST_PATH, 'backtest') if os.path.exists(BACKTEST_PATH) else None,
    # trading_bot 디렉토리
    (os.path.join(PROJECT_ROOT, 'trading_bot'), 'trading_bot') if os.path.exists(os.path.join(PROJECT_ROOT, 'trading_bot')) else None,
    # 아이콘 파일 (있는 경우)
    (os.path.join(PROJECT_ROOT, 'assets'), 'assets') if os.path.exists(os.path.join(PROJECT_ROOT, 'assets')) else None,
]

# None 값 제거
added_files = [f for f in added_files if f is not None]

# hidden imports - 동적으로 임포트되는 모듈들
hidden_imports = [
    'PyQt5',
    'PyQt5.QtCore',
    'PyQt5.QtGui', 
    'PyQt5.QtWidgets',
    'PyQt5.QtWebEngineWidgets',
    'matplotlib',
    'matplotlib.backends.backend_qt5agg',
    'mplfinance',
    'pandas',
    'numpy',
    'websocket',
    'websocket-client',
    'python-binance',
    'binance',
    'dotenv',
    'asyncio',
    'aiohttp',
    'pyqtgraph',
    'ta',
    'requests',
    'urllib3',
    'certifi',
    'trading_bot',
    'trading_bot.strategies',
    'trading_bot.strategies.base_strategy',
    'trading_bot.strategies.trend_following',
    'trading_bot.strategies.arbitrage',
    'trading_bot.strategies.scalping',
    'trading_bot.bot_manager',
    'backtest',
    'backtest.main',
    'backtest.dataset',
    'backtest.backtesting',
    'backtest.invest_strategy',
    'backtest.visualization',
]

# matplotlib 데이터 파일 수집
matplotlib_data = collect_data_files('matplotlib')

a = Analysis(
    ['main_unified.py'],
    pathex=[PROJECT_ROOT, BACKTEST_PATH],
    binaries=[],
    datas=added_files + matplotlib_data,
    hiddenimports=hidden_imports,
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
    console=False,  # GUI 앱이므로 콘솔 창 숨김
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico' if sys.platform == 'win32' and os.path.exists('assets/icon.ico') else None,
)

# macOS용 앱 번들 생성
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='GeniusCoinManager.app',
        icon='assets/icon.icns' if os.path.exists('assets/icon.icns') else None,
        bundle_identifier='com.genius.coinmanager',
        info_plist={
            'CFBundleName': 'Genius Coin Manager',
            'CFBundleDisplayName': 'Genius Coin Manager',
            'CFBundleGetInfoString': "Genius Coin Manager - Trading Platform",
            'CFBundleIdentifier': "com.genius.coinmanager",
            'CFBundleVersion': "1.0.0",
            'CFBundleShortVersionString': "1.0.0",
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '10.13.0',
        },
    )