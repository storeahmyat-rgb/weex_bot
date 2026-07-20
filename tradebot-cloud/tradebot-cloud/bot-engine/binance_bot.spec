# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller Spec File - Binance Futures Bot
Builds a single .exe file with all dependencies bundled.

Usage:
    pyinstaller binance_bot.spec

Output:
    dist/BinanceFuturesBot.exe (single executable, ~150MB)
"""
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Collect all submodules for packages that use dynamic imports
hiddenimports = []
hiddenimports += collect_submodules('binance')
hiddenimports += collect_submodules('flask')
hiddenimports += collect_submodules('flask_socketio')
hiddenimports += collect_submodules('engineio')
hiddenimports += collect_submodules('socketio')
hiddenimports += collect_submodules('pandas')
hiddenimports += collect_submodules('numpy')
hiddenimports += collect_submodules('pyarrow')
hiddenimports += collect_submodules('requests')
hiddenimports += collect_submodules('urllib3')
hiddenimports += collect_submodules('certifi')
hiddenimports += collect_submodules('charset_normalizer')
hiddenimports += collect_submodules('idna')

# Add our own modules explicitly
hiddenimports += [
    'bot',
    'bot.__init__',
    'bot.indicators',
    'bot.strategy',
    'bot.trader',
    'bot.weex_trader',
    'bot.engine',
    'bot.notifier',
    'bot.license',
    'bot.crypto_store',
    'bot.secret',
    'bot.antitamper',
    # Standard library modules sometimes missed
    'pydoc',                    # REQUIRED by pyarrow (was excluded before - bug!)
    'pydoc_data',
    'pydoc_data.topics',
    'html',
    'html.parser',
    'http',
    'http.client',
    'email',
    'email.mime.text',
    'email.mime.multipart',
    'smtplib',
    'ssl',
    'asyncio',
    'concurrent',
    'concurrent.futures',
]

# Data files to include (templates, static files, libraries)
datas = []
datas += collect_data_files('flask')
datas += [('templates', 'templates')]
datas += [('static', 'static')]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'PIL',
        'pytest',
        'unittest',
        'IPython',
        'jupyter',
        'notebook',
        'nbformat',
        'nbconvert',
    ],
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
    name='BinanceFuturesBot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # MUST be True - so crash errors are visible
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
