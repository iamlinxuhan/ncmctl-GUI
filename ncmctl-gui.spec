# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置，三平台共用。

    pip install pyinstaller
    pyinstaller ncmctl-gui.spec --noconfirm

产物落在 ``dist/``，三个平台都是一个**单文件可执行程序**：

* Linux   → ``dist/ncmctl-gui``
* macOS   → ``dist/ncmctl-gui``（Unix 可执行文件，没做 .app 封装）
* Windows → ``dist/ncmctl-gui.exe``

名字可以用环境变量 ``NCMGUI_BUILD_NAME`` 覆盖，CI 里靠它区分架构。

**不把 ncmctl 本体打进去**：它是独立的 Go 程序，官方就有各平台 Release，
让用户自己装、自己升级，比跟着这里重新打包省事得多。程序启动时按
「PATH → 常见安装目录 → 设置页指定的路径」的顺序去找它。
"""

import os
import sys

from PyInstaller.utils.hooks import collect_all

# Windows 上 pywinpty 除了 Python 扩展之外还带几个**非 .pyd 的二进制**：
# conpty.dll、OpenConsole.exe、winpty.dll、winpty-agent.exe。PyInstaller 的
# 常规依赖分析只看得到 .pyd，这几个会全部漏掉——而 ConPTY 后端运行时要按
# 相对路径找到它们。collect_all 把整个包连同这些文件一起收进来。
datas, binaries, hiddenimports = [], [], []
if sys.platform == "win32":
    datas, binaries, hiddenimports = collect_all("winpty")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 这些是 PyQt6 拖得进来、界面里一个都没用到的大家伙
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtWebEngine",
        "PyQt6.QtBluetooth",
        "PyQt6.QtMultimedia",
        "PyQt6.QtSql",
        "PyQt6.QtTest",
        "tkinter",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=os.environ.get("NCMGUI_BUILD_NAME", "ncmctl-gui"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # 不要另外弹一个黑框控制台：所有输出都走界面里的作业控制台。
    # ncmctl 子进程有它自己的伪终端，跟这个开关没有关系。
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
