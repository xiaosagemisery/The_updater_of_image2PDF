# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: 网页界面版 exe。
#
# 本地用法: pip install -r requirements.txt -r requirements-build.txt
#           pyinstaller image2PDF-web.spec
# 产物落在 dist/image2PDF-web.exe。CI(.github/workflows/build-exe.yml)用的是
# 同一份 spec,保证本地构建和自动发布到 Release 的 exe 是同一套配置。
#
# datas 里必须显式带上 templates/static——onefile 冻结后 webapp.py 靠
# sys._MEIPASS(见 webapp._resource_dir())去读这两个目录,这里不打进去的话
# 运行时就是 TemplateNotFound。reportlab 自带一批字体/编码相关的数据文件,
# collect_data_files 显式收集,避免冻结环境里 import 时找不到数据文件。
from PyInstaller.utils.hooks import collect_data_files

datas = [('templates', 'templates'), ('static', 'static')]
datas += collect_data_files('reportlab')

a = Analysis(
    ['webapp.py'],
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
    name='image2PDF-web',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # 保留控制台窗口: 网页版靠这个窗口打印监听地址、并且需要 Ctrl+C 才能停服务,
    # 做成无窗口(windowed)模式用户就没法优雅退出了。
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
