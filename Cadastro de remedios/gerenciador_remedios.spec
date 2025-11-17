# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['gerenciador_remedios.py'],
    pathex=[],
    binaries=[],
    datas=[('cardiogram.png', '.'), ('cardiogram.ico', '.')],
    hiddenimports=['pystray', 'PIL', 'pkg_resources.py2_warn', 'win32api', 'win32con', 'win32gui'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='gerenciador_remedios',
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
    icon=['cardiogram.ico'],
)
