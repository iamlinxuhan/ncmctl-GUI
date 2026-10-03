"""设置页：ncmctl 定位、全局运行参数、配置持久化与自更新。"""

from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QLabel

from .. import ncmctl
from ..config import config_dir
from ..widgets.card import accent_button, danger_button, ghost_button
from ..widgets.form import FormCard
from .base import BasePage


class SettingsPage(BasePage):
    PAGE_TITLE = "设置"
    PAGE_SUBTITLE = "ncmctl 可执行文件位置、全局参数与程序配置。"

    def build(self) -> None:
        self._build_binary_card()
        self._build_global_card()
        self._build_update_card()
        self._build_about_card()

    # --------------------------------------------------------- ncmctl 定位

    def _build_binary_card(self) -> None:
        card = FormCard(
            "ncmctl 位置",
            "留空时自动在 PATH 与常见安装位置（~/go/bin 等）查找。",
        )
        self.binary_path = card.add_path(
            "可执行文件", mode="file",
            value=self.cfg.get("ncmctl_path", ""),
            placeholder="留空表示自动探测",
            hint="从 GitHub Release 装的话通常在 ~/go/bin/ncmctl 或 /usr/local/bin/ncmctl。",
        )

        self.detected = QLabel("")
        self.detected.setObjectName("Hint")
        self.detected.setWordWrap(True)
        card.add_widget(self.detected)

        detect = ghost_button("重新探测")
        detect.clicked.connect(self._detect)
        card.add_row_of(detect)
        self.content.addWidget(card)

        self._detect()

    def _detect(self) -> None:
        found = ncmctl.find_binary(self.binary_path.path())
        if found:
            self.detected.setText(f"✅ 当前使用：{found}")
        else:
            self.detected.setText(
                "⚠ 未找到 ncmctl。请在上面指定完整路径，或先安装 ncmctl。"
            )

    # -------------------------------------------------------------- 全局参数

    def _build_global_card(self) -> None:
        card = FormCard(
            "全局运行参数",
            "对应 ncmctl 的 --home / -c / --debug，会附加到每一条命令后面。",
        )
        self.home = card.add_path(
            "状态目录（--home）", mode="dir",
            value=self.cfg.get("home", ""),
            placeholder="留空表示使用系统家目录",
            hint="ncmctl 会在这里的 .ncmctl/ 子目录下保存登录凭据与缓存。",
        )
        self.config_file = card.add_path(
            "配置文件（-c）", mode="file",
            value=self.cfg.get("config_file", ""),
            placeholder="留空表示不指定，使用 ncmctl 默认查找逻辑",
        )
        self.debug = card.add_switch(
            "输出详细日志（--debug）",
            bool(self.cfg.get("debug", False)),
            hint="会打印 API 请求头与响应体，其中可能包含敏感数据。排查问题时才建议开启。",
        )

        save = accent_button("保存设置")
        save.clicked.connect(self._save)
        reset = ghost_button("恢复默认")
        reset.clicked.connect(self._reset)
        card.add_row_of(save, reset)
        self.content.addWidget(card)

    def _save(self) -> None:
        self.save_config()
        self.cfg.save()
        self.window.reload_binary()
        self._detect()
        self.toast("设置已保存，并已重新探测 ncmctl。")

    def _reset(self) -> None:
        self.binary_path.set_path("")
        self.home.set_path("")
        self.config_file.set_path("")
        self.debug.setChecked(False)
        self.save_config()
        self.cfg.save()
        self.window.reload_binary()
        self._detect()
        self.toast("已恢复默认设置。")

    # ---------------------------------------------------------------- 更新

    def _build_update_card(self) -> None:
        card = FormCard(
            "更新 ncmctl",
            "从 GitHub Release 下载最新版本，校验 SHA-256 后原地替换当前可执行文件。"
            "已安装的版本不会被降级。",
        )
        self.update_proxy = card.add_line(
            "下载代理", value=self.cfg.get("update.proxy", ""),
            placeholder="留空使用内置代理链；填 direct 强制直连",
            hint="国内网络直连 GitHub 常常失败，留空通常最省事。",
        )

        run = danger_button("立即更新")
        run.clicked.connect(self._update)
        card.add_row_of(run)
        self.content.addWidget(card)

    def _update(self) -> None:
        proxy = self.update_proxy.text().strip()
        if proxy.lower() == "direct":
            proxy = ""
        self.cfg.set("update.proxy", self.update_proxy.text().strip())

        self.window.submit(
            "更新 ncmctl",
            ncmctl.build_update(proxy, self.opts()),
            confirm=(
                "确认更新 ncmctl？",
                "更新会下载新版本并<b>原地覆盖</b>当前的 ncmctl 可执行文件。"
                "更新期间请勿运行其他 ncmctl 作业。<br><br>"
                "下载来源为 GitHub Release，并会校验 SHA-256。",
            ),
        )

    # ---------------------------------------------------------------- 关于

    def _build_about_card(self) -> None:
        card = FormCard("配置与关于")

        path = QLabel(f"本程序的配置文件：<code>{config_dir() / 'config.json'}</code>")
        path.setObjectName("Hint")
        path.setWordWrap(True)
        card.add_widget(path)

        note = QLabel(
            "本程序只是 ncmctl 的图形前端，不保存你的账号密码。<br>"
            "登录凭据由 ncmctl 自己写在 <code>~/.ncmctl/</code> 下，本程序只读取状态用于显示。"
        )
        note.setObjectName("Hint")
        note.setWordWrap(True)
        card.add_widget(note)

        open_dir = ghost_button("打开配置目录")
        open_dir.clicked.connect(self._open_config_dir)
        link = ghost_button("打开 ncmctl 项目主页")
        link.clicked.connect(self._open_project)
        card.add_row_of(open_dir, link)
        self.content.addWidget(card)

    def _open_config_dir(self) -> None:
        directory = config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def _open_project(self) -> None:
        QDesktopServices.openUrl(QUrl("https://github.com/chaunsin/netease-cloud-music"))

    # ------------------------------------------------------------------ 配置

    def save_config(self) -> None:
        self.cfg.set("ncmctl_path", self.binary_path.path())
        self.cfg.set("home", self.home.path())
        self.cfg.set("config_file", self.config_file.path())
        self.cfg.set("debug", self.debug.isChecked())
        self.cfg.set("update.proxy", self.update_proxy.text().strip())
