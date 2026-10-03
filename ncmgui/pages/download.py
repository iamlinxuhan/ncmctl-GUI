"""下载页：歌曲 ID / 链接 → 本地音乐文件。

除了把 ncmctl 的 download 子命令表单化，这一页还补了两件 ncmctl 自己不做的
事（见 :mod:`ncmgui.resolver`）：

* **查重** —— ncmctl 遇到同名文件只会改写成 ``歌曲(1).flac`` 接着下，
  不会跳过。这里在下载前先把目标展开成歌曲清单，比对输出目录，把已有的剔掉。
* **下载「我喜欢的音乐」** —— 一键把整个红心歌单搬回本地。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMessageBox

from .. import ncmctl
from ..config import default_music_dir
from ..resolver import PLAYLIST_URL, FeeTagger, Plan, Resolver, Song
from ..widgets.card import Card, accent_button, ghost_button
from ..widgets.console import ConsoleView, classify
from ..widgets.form import FormCard, combo_data
from .base import BasePage

PLACEHOLDER = (
    "2161154646\n"
    "https://music.163.com/song?id=1820944399\n"
    "https://music.163.com/playlist?id=593617579\n"
    "https://music.163.com/album?id=32311"
)

#: 解析任务当前的意图，决定拿到计划之后做什么
MODE_PREVIEW = "preview"
MODE_DOWNLOAD = "download"
MODE_LIKED = "liked"


class DownloadPage(BasePage):
    PAGE_TITLE = "下载"
    PAGE_SUBTITLE = "解析歌曲 ID、专辑 / 歌手 / 歌单链接并下载到本地。需要登录。"

    # --------------------------------------------------------------- 生命周期

    def __init__(self, window) -> None:
        # 必须在 build() 之前就位：build() 里会用到它们
        self._task = None
        self._plan: Plan | None = None
        self._plan_mode = ""
        super().__init__(window)

    # -------------------------------------------------------------------- 构建

    def build(self) -> None:
        self._build_targets()
        self._build_quick()
        self._build_options()
        self._build_report()
        self._build_actions()
        self._sync_buttons()

    def _build_targets(self) -> None:
        targets_card = FormCard(
            "下载目标",
            "每行一个，也可以用空格或逗号分隔。支持歌曲 ID 以及歌曲 / 专辑 / 歌手 / 歌单链接。",
        )
        self.targets = targets_card.add_text(
            "", value="", placeholder=PLACEHOLDER, height=150
        )
        self.target_count = QLabel("尚未识别到目标")
        self.target_count.setObjectName("Hint")
        targets_card.add_widget(self.target_count)
        self.targets.textChanged.connect(self._on_targets_changed)
        self.content.addWidget(targets_card)

    def _build_quick(self) -> None:
        card = Card("快捷下载", "不用手抄歌单 ID，直接从账号里取。")

        self.liked_button = accent_button("下载「我喜欢的音乐」全部歌曲")
        self.liked_button.clicked.connect(self._download_liked)

        hint = QLabel(
            "先读取红心歌单的曲目，再按下面的「查重」设置决定跳过哪些，"
            "最后只把缺的交给 ncmctl。"
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)

        card.add(self.liked_button)
        card.add(hint)
        self.content.addWidget(card)

    def _build_options(self) -> None:
        options = FormCard("下载设置")
        self.level = options.add_combo(
            "音质",
            ncmctl.DOWNLOAD_LEVELS,
            self.cfg.get("download.level", "lossless"),
            hint="该音质不可得时默认自动降级；想严格按所选音质下载请打开下面的开关。",
        )
        self.strict = options.add_switch(
            "严格音质（音质不可得时跳过，而不是降级）",
            bool(self.cfg.get("download.strict", False)),
        )
        self.skip_existing = options.add_switch(
            "跳过输出目录里已存在的歌曲（查重）",
            bool(self.cfg.get("download.skip_existing", True)),
            hint=(
                "下载前先解析出每首歌的文件名并比对输出目录，已存在的直接跳过。"
                "ncmctl 自身不会跳过，重名时会写成「歌曲(1).flac」再下一遍。"
            ),
        )
        self.parallel = options.add_spin(
            "并发数",
            int(self.cfg.get("download.parallel", 5)),
            1, 20,
            hint="同时下载的曲目数量，网络不稳定时建议调小。",
        )
        self.output = options.add_path(
            "输出目录",
            mode="dir",
            value=self.cfg.get("download.output", ""),
            default=str(default_music_dir()),
            hint="下载完成的文件会写到这里，MD5 校验通过后才算完成。",
        )
        # 输出目录变了，之前的查重结论就作废
        self.output.pathChanged.connect(lambda _path: self._invalidate_plan())
        self.content.addWidget(options)

    def _build_report(self) -> None:
        card = Card("查重结果", "点「开始下载」或「仅查重」后，这里会列出跳过与待下载的曲目。")

        self.report_label = QLabel("还没有查重结果。")
        self.report_label.setObjectName("Hint")
        self.report_label.setWordWrap(True)

        self.report_view = ConsoleView()
        self.report_view.setFixedHeight(150)
        self.report_view.setVisible(False)

        self.details_button = ghost_button("显示明细", compact=True)
        self.details_button.setVisible(False)
        self.details_button.clicked.connect(self._toggle_details)

        # 按钮单独一行并靠左，别被卡片拉成通栏
        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.addWidget(self.details_button)
        toggle_row.addStretch(1)

        card.add(self.report_label)
        card.add(toggle_row)
        card.add(self.report_view)
        self.content.addWidget(card)

    def _build_actions(self) -> None:
        actions = FormCard()
        self.start_button = accent_button("开始下载")
        self.start_button.clicked.connect(self._start)

        self.preview_button = ghost_button("仅查重")
        self.preview_button.clicked.connect(self._preview)

        clear_button = ghost_button("清空目标")
        clear_button.clicked.connect(lambda: self.targets.setPlainText(""))

        open_button = ghost_button("打开输出目录")
        open_button.clicked.connect(self.output.reveal)

        actions.add_row_of(self.start_button, self.preview_button)
        actions.add_row_of(clear_button, open_button)
        self.content.addWidget(actions)

    # ------------------------------------------------------------------ 交互

    def _on_targets_changed(self) -> None:
        count = len(ncmctl.parse_targets(self.targets.toPlainText()))
        self.target_count.setText(
            f"已识别 {count} 个目标" if count else "尚未识别到目标"
        )
        self._invalidate_plan()

    def _invalidate_plan(self) -> None:
        """输入或输出目录变了，上次的查重结论就不算数了。"""
        self._plan = None

    def _sync_buttons(self) -> None:
        """按钮可用状态只在这里决定，避免各处各改一套。"""
        busy = bool(self._task is not None and self._task.is_running)
        self.start_button.setEnabled(not busy)
        self.preview_button.setEnabled(not busy)
        self.liked_button.setEnabled(not busy and self.is_logged_in())
        self.setCursor(
            Qt.CursorShape.BusyCursor if busy else Qt.CursorShape.ArrowCursor
        )

    def _toggle_details(self) -> None:
        visible = not self.report_view.isVisible()
        self.report_view.setVisible(visible)
        self.details_button.setText("隐藏明细" if visible else "显示明细")

    def on_login_changed(self, logged_in: bool) -> None:
        self._sync_buttons()

    # ------------------------------------------------------------------ 查重

    def _output_dir(self) -> str:
        return self.output.path()

    def _start_task(self, work, busy_text: str, mode: str) -> None:
        """在后台跑一次解析。

        :param work: 接收一个 :class:`Resolver`、返回结果的函数。**不得触碰界面。**
        :param mode: 见 ``MODE_*``，决定结果回来之后做什么
        """
        if self._task is not None and self._task.is_running:
            self.toast("上一次解析还没结束，请稍候")
            return

        from ..workers import BackgroundTask

        resolver = Resolver(self.window.binary, opts=self.opts())
        task = BackgroundTask(lambda: work(resolver), parent=self)
        resolver.progress = task.progress.emit

        self._task = task
        self._plan_mode = mode
        task.progress.connect(self._on_progress)
        task.done.connect(self._on_plan_ready)
        task.failed.connect(self._on_task_failed)

        self.report_label.setText(busy_text)
        self._sync_buttons()
        task.start()

    def _on_progress(self, message: str) -> None:
        self.report_label.setText(message)

    def _on_task_failed(self, message: str) -> None:
        self._plan_mode = ""
        self._sync_buttons()
        self.report_label.setText("解析失败，未做任何下载。")
        self.warn(message, "解析失败")

    def _on_plan_ready(self, plan: object) -> None:
        mode, self._plan_mode = self._plan_mode, ""
        self._sync_buttons()

        if not isinstance(plan, Plan):
            return

        if mode == MODE_LIKED and plan.sources:
            # 把解析出来的歌单链接回填到目标框，让用户看得见到底下了什么。
            # 这一步会触发 textChanged → 作废计划，所以计划要等它之后再存。
            self.targets.setPlainText("\n".join(plan.sources))
            self._update_count_only()

        self._plan = plan
        self._show_plan(plan)

        if mode in (MODE_DOWNLOAD, MODE_LIKED):
            self._execute_plan(plan)
        elif plan.warnings:
            self.toast(f"有 {len(plan.warnings)} 个目标没能解析，展开明细可以看到")

    def _update_count_only(self) -> None:
        """回填目标框时刷新计数，但不作废刚拿到的计划。"""
        count = len(ncmctl.parse_targets(self.targets.toPlainText()))
        self.target_count.setText(f"已识别 {count} 个目标")

    def _show_plan(self, plan: Plan) -> None:
        self.report_label.setText(plan.report())
        self.report_view.clear_log()
        for line in plan.details().splitlines():
            self.report_view.append_line(line, classify(line))
        self.details_button.setVisible(bool(plan.present or plan.warnings))

    # ------------------------------------------------------------------ 下载

    def _plan_is_fresh(self, targets: list[str]) -> bool:
        return isinstance(self._plan, Plan) and self._plan.matches(
            targets, self._output_dir()
        )

    def _preview(self) -> None:
        targets = ncmctl.parse_targets(self.targets.toPlainText())
        if not targets:
            self.warn("请至少填写一个歌曲 ID 或链接。")
            return
        if not self.require_login("查重"):
            return
        self.save_config()
        output = self._output_dir()
        self._start_task(
            lambda r: r.plan(targets, output),
            "正在解析目标并对照输出目录查重…",
            MODE_PREVIEW,
        )

    def _start(self) -> None:
        targets = ncmctl.parse_targets(self.targets.toPlainText())
        if not targets:
            self.warn("请至少填写一个歌曲 ID 或链接。")
            return
        if not self.require_login("下载"):
            return

        if self.level.currentData() == "hires":
            QMessageBox.information(
                self,
                "关于 Hi-Res",
                "Hi-Res 只有部分曲目提供。若长时间没有进展，"
                "可以改用「无损 FLAC」，或打开「严格音质」之外的降级行为。",
            )

        self.save_config()

        # 关掉查重就直接把原始目标交给 ncmctl，行为与以前一致
        if not self.skip_existing.isChecked():
            self._submit_download(targets, self._title_for(targets))
            return

        # 「仅查重」刚跑过且条件没变，直接复用结果
        if self._plan_is_fresh(targets):
            self._show_plan(self._plan)
            self._execute_plan(self._plan)
            return

        output = self._output_dir()
        self._start_task(
            lambda r: r.plan(targets, output),
            "正在解析目标并对照输出目录查重…",
            MODE_DOWNLOAD,
        )

    def _download_liked(self) -> None:
        if not self.require_login("下载我喜欢的音乐"):
            return
        self.save_config()
        output = self._output_dir()

        def work(resolver: Resolver) -> Plan:
            playlist_id, name = resolver.liked_playlist()
            url = PLAYLIST_URL.format(playlist_id)
            resolver.notify(f"「{name}」正在读取曲目列表…")
            plan = resolver.plan([url], output)
            plan.label = name
            return plan

        self._start_task(work, "正在读取「我喜欢的音乐」…", MODE_LIKED)

    def _execute_plan(self, plan: Plan) -> None:
        if self.skip_existing.isChecked():
            songs = plan.missing
        else:
            songs = plan.songs

        label = f"「{plan.label}」" if plan.label else ""
        if not songs:
            self.toast(f"{label}{plan.total} 首歌曲都已存在于输出目录，无需下载")
            return

        title = f"下载{label} {len(songs)} 首" if label else f"下载 {len(songs)} 首"
        self._submit_download(
            [str(song.id) for song in songs],
            title,
            intro=self._intro_for(plan, songs),
            songs=songs,
        )

    @staticmethod
    def _intro_for(plan: Plan, songs: list[Song]) -> list[str]:
        """开跑前在控制台里交代一句：这批里哪些是要会员的。

        ncmctl 的下载日志只有进度条和一句 report，从不提付费情况 —— 而拉不到
        音质的往往正是这几首。所以把清单摆在日志最前面，出错时好对照。
        """
        paid = [song for song in songs if song.is_paid]
        if not paid:
            return []

        if plan.vip is True:
            tail = "当前账号是会员，通常能下"
        elif plan.vip is False:
            tail = "而当前账号不是会员，这些多半会失败"
        else:
            tail = "下载失败多半是它们"

        lines = [
            f"── 本批 {len(songs)} 首里有 {len(paid)} 首需要会员或购买，{tail} ──"
        ]
        limit = 20
        lines.extend(f"   {song.marked}" for song in paid[:limit])
        if len(paid) > limit:
            lines.append(f"   … 还有 {len(paid) - limit} 首")
        return lines

    def _submit_download(
        self,
        targets: list[str],
        title: str,
        intro: list[str] | None = None,
        songs: list[Song] | None = None,
    ) -> None:
        """提交下载作业。

        :param songs: 这批目标对应的歌曲。给了它就能顺带装上付费标注 ——
            ncmctl 的进度行会被改写成 ``[VIP]歌手 - 歌名  [进度条]`` 并标黄，
            让人一眼看出哪几首可能拉不到音质。跳过查重时拿不到，就不标。
        """
        argv = ncmctl.build_download(
            targets,
            level=combo_data(self.level, "lossless"),
            output=self._output_dir(),
            parallel=self.parallel.value(),
            strict=self.strict.isChecked(),
            opts=self.opts(),
        )
        self.submit(
            title,
            argv,
            intro=intro,
            tagger=FeeTagger(songs) if songs else None,
        )

    @staticmethod
    def _title_for(targets: list[str]) -> str:
        return f"下载 {targets[0]}" if len(targets) == 1 else f"下载 {len(targets)} 个目标"

    # ------------------------------------------------------------------ 配置

    def save_config(self) -> None:
        self.cfg.set("download.level", combo_data(self.level, "lossless"))
        self.cfg.set("download.strict", self.strict.isChecked())
        self.cfg.set("download.skip_existing", self.skip_existing.isChecked())
        self.cfg.set("download.parallel", self.parallel.value())
        self.cfg.set("download.output", self.output.path())
