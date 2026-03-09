# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Mischicat-Bot
# 使用 one-dir 模式便于包含 web/static、web/templates 及动态加载的 cogs

import os

block_cipher = None

# 需要打包的数据目录（Web 界面）
datas = [
    ('web/static', 'web/static'),
    ('web/templates', 'web/templates'),
]

# 动态加载的 cogs 和常用隐式导入
hiddenimports = [
    'bot',
    'discord',
    'discord.ext.commands',
    'cogs.music',
    'cogs.character',
    'cogs.travel',
    'cogs.cultivation',
    'cogs.sect',
    'cogs.explore',
    'cogs.property',
    'cogs.tavern',
    'cogs.public_events',
    'cogs.equipment',
    'web.main',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
]

a = Analysis(
    ['main.py'],
    pathex=[],
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

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='mischicat-bot',
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
    name='mischicat-bot',
)
