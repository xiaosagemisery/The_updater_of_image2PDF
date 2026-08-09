# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: 命令行版 exe。
#
# 本地用法: pip install -r requirements.txt -r requirements-build.txt
#           pyinstaller image2PDF-cli.spec
# 产物落在 dist/image2PDF-cli.exe。CI(.github/workflows/build-exe.yml)用的是
# 同一份 spec。没有 templates/static,不需要 datas 里带那两个目录;reportlab
# 的数据文件仍然要显式收集,原因同 image2PDF-web.spec。
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files('reportlab')

a = Analysis(
    ['Image2PDF.py'],
    pathex=[],
    binaries=[],
    datas=datas,
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
    name='image2PDF-cli',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # 保留控制台窗口: CLI 版本本来就是靠 input() 交互式要路径、打印转换日志的,
    # 必须有控制台。
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
