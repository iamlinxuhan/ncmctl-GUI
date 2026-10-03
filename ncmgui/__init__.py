"""ncmctl GUI —— 网易云音乐命令行工具 ncmctl 的 PyQt6 图形界面。"""

import sys

APP_NAME = "ncmctl GUI"
APP_ID = "ncmctl-gui"
VERSION = "1.0.0"


def ensure_utf8_stdout() -> None:
    """让标准输出能够打印中文。

    Windows 控制台默认是 cp1252 / cp936，中文一 ``print`` 就抛
    ``UnicodeEncodeError``；重定向到文件时也可能撞上同样的编码问题。
    命令行自检在动手之前先调一次，省得每个 ``print`` 都得自己防一手。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


__all__ = ["APP_NAME", "APP_ID", "VERSION", "ensure_utf8_stdout"]
