"""下载页的端到端集成测试。

走的是页面真实代码路径（``_download_liked`` / ``_start`` / ``_preview``），
不 mock 解析层，所以会真的调网易云接口、真的下歌。需要已登录。

    .venv/bin/python -u tests/gui_integration.py

用临时目录当输出目录、临时文件当配置文件，不碰你的真实配置和曲库。
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtWidgets import QApplication, QMessageBox

# 无头环境下模态框没人点，会永久阻塞 —— 换成记录
DIALOGS: list[tuple[str, str, str]] = []
for _name in ("warning", "information", "critical", "question"):

    def _stub(parent, title, text, *a, _n=_name, **kw):
        DIALOGS.append((_n, title, text))
        print(f"      [对话框 {_n}] {title}: {text[:120]}")
        return QMessageBox.StandardButton.Ok

    setattr(QMessageBox, _name, staticmethod(_stub))

from ncmgui import ncmctl, theme
from ncmgui.config import Config
from ncmgui.pages.download import DownloadPage
from ncmgui.resolver import PLAYLIST_URL, Plan, Resolver, Song
from ncmgui.window import MainWindow

app = QApplication([])
theme.apply_theme(app)

cfg_path = Path(tempfile.mkdtemp(prefix="ncmgui-cfg-")) / "config.json"
window = MainWindow(Config(cfg_path))
window.show()
window.show_page("download")
page = window.pages["download"]

fails: list[str] = []


def check(name: str, cond: object, detail: object = "") -> None:
    print(("  OK  " if cond else "  FAIL") + f" {name} {detail}", flush=True)
    if not cond:
        fails.append(name)


def pump(pred, seconds: float = 240) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.05)
        if pred():
            return True
    return False


def positionals(argv: list[str]) -> list[str]:
    """取 argparse 的位置参数：跳过 argv[0] 与所有 --flag（含其取值）。"""
    out, expecting_value = [], False
    for token in argv[1:]:
        if expecting_value:
            expecting_value = False
            continue
        if token.startswith("-"):
            expecting_value = True
            continue
        out.append(token)
    return out


submitted: list[tuple[str, list[str], list[str]]] = []
tagger_seen: list[object] = []
real_submit = window.submit


def spy(title, argv, confirm=None, cwd=None, intro=None, tagger=None):
    submitted.append((title, list(argv), list(intro or [])))
    tagger_seen.append(tagger)
    return real_submit(title, argv, confirm, cwd, intro=intro, tagger=tagger)


window.submit = spy

# ====================================================================== #
print("[0] 解析红心歌单，把除前 2 首外的都伪造成本地已有文件", flush=True)
out = Path(tempfile.mkdtemp(prefix="ncmgui-out-"))
resolver = Resolver(ncmctl.find_binary(), opts=ncmctl.GlobalOpts())
playlist_id, playlist_name = resolver.liked_playlist()
plan = resolver.plan([PLAYLIST_URL.format(playlist_id)], out)
print(f"      歌单「{playlist_name}」共 {plan.total} 首；账号会员={plan.vip}", flush=True)
print(f"      其中需会员/购买 {len(plan.paid)} 首", flush=True)
keep = plan.songs[:2]
for song in plan.songs[2:]:
    (out / f"{song.base}.flac").write_bytes(b"")
print(f"      伪造 {plan.total - 2} 个文件，保留 {len(keep)} 首待下载", flush=True)

page.output.set_path(str(out))
page.skip_existing.setChecked(True)

# ====================================================================== #
print("[1] 点击「下载我喜欢的音乐」", flush=True)
page._download_liked()
ok = pump(lambda: page._task is not None and page._task.finished)
check("解析任务完成", ok, "" if ok else f"对话框={DIALOGS}")
pump(lambda: bool(submitted), 15)

check(
    "回填了歌单链接",
    PLAYLIST_URL.format(playlist_id) in page.targets.toPlainText(),
    page.targets.toPlainText()[:60],
)
check("提交了一个下载作业", len(submitted) == 1, [t for t, _, _ in submitted])

intro: list[str] = []
if submitted:
    title, argv, intro = submitted[0]
    check("标题带歌单名", playlist_name in title, title)
    check("只提交了缺的 2 首", sorted(positionals(argv)) == sorted(str(s.id) for s in keep), positionals(argv))
    check("音质参数正确", argv[argv.index("--level") + 1] == "lossless")
    check("输出目录正确", argv[argv.index("--output") + 1] == str(out))

check("报告显示跳过数", f"已存在 {plan.total - 2} 首" in page.report_label.text(),
      page.report_label.text())
check("「显示明细」按钮出现", page.details_button.isVisible())
check("明细默认收起", not page.report_view.isVisible())
page._toggle_details()
check("展开后可见且带内容",
      page.report_view.isVisible()
      and f"已存在，跳过下载（{plan.total - 2} 首）" in page.report_view.toPlainText(),
      page.details_button.text())
check("按钮文案翻转", page.details_button.text() == "隐藏明细")
page._toggle_details()
check("收起后重新隐藏", not page.report_view.isVisible())

# ---- VIP 标注 -------------------------------------------------------- #
print("      —— VIP 标注 ——", flush=True)
detail = page.report_view.toPlainText()
# 注意用页面自己的 _plan —— 上面那个 plan 是伪造文件之前算的，missing 还是全量
shown_plan = page._plan
paid_songs = [s for s in shown_plan.missing if s.is_paid]
if paid_songs:
    # 待下载的这 2 首里若有付费的，明细里就该带方括号标记
    missing_marks = [s for s in paid_songs if f"[{s.fee_label}] {s.display}" not in detail]
    check("待下载的付费歌曲在明细里带标记", not missing_marks,
          [(s.display, s.fee_label) for s in missing_marks])
    check("明细里有图例", "标记含义：" in detail)
    check("图例说明当前会员状态",
          ("当前账号是会员" if plan.vip else "当前账号不是会员") in detail, plan.vip)
else:
    print("      （这 2 首都不付费，标记相关断言跳过）", flush=True)

check("控制台开场白非空（有付费歌曲时）", bool(intro) == bool(paid_songs), intro[:1])

# ---- 进度行标注 ------------------------------------------------------ #
# 开场白只在开跑前出现一次，滚两屏就没了。真正要的是下载过程中每一行进度
# 都带着标记 —— 那是 FeeTagger 干的活，这里离线验一遍，真机结果在 [2] 里查。
print("      —— 进度行标注 ——", flush=True)
tagger = tagger_seen[0] if tagger_seen else None
check("作业装上了标注器", tagger is not None, tagger_seen[:1])

if tagger is not None:
    for song in shown_plan.missing:
        line = f"{song.base}                      [--------] 1.00 MiB/2.00 MiB  50.00%"
        got = tagger(line)
        if song.is_paid:
            check(f"付费进度行加标记：{song.display[:24]}",
                  got is not None and got.startswith(f"[{song.fee_label}]"), got)
        else:
            check(f"免费进度行不动：{song.display[:24]}", got is None, got)

# ====================================================================== #
print("[2] 真机下载这 2 首，验证查重与实际落盘一致", flush=True)
if submitted:
    end = time.time() + 400
    ticks = 0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.1)
        ticks += 1
        if not window._running_panels():
            break

    panel = window.console_tabs.widget(window.console_tabs.count() - 1)
    log = panel.view.toPlainText()
    report_line = next(
        (ln for ln in log.splitlines() if ln.startswith("report total:")), "(没有 report 行)"
    )
    print(f"      等待循环跑了 {ticks} 次（{ticks / 10:.1f} 秒）；{report_line}", flush=True)

    names = sorted(f.name for f in out.iterdir() if f.suffix in (".mp3", ".flac"))
    real = [n for n in names if (out / n).stat().st_size > 0]
    check("只新增了 2 个真实音频文件", len(real) == 2, real)
    check("落盘文件名与查重推断一致", {Path(n).stem for n in real} == {s.base for s in keep})

    plan2 = resolver.plan([PLAYLIST_URL.format(playlist_id)], out)
    check("再查重 => 一首不缺", not plan2.missing, plan2.report())

    # 开场白应当真的写进了控制台，而不只是传了个参数
    if intro:
        check("开场白已写进控制台", intro[0] in log, log.splitlines()[:3])

    # 真机跑出来的进度行应当自带标记 —— 这是「下载中也能看见」的最终证据
    if any(song.is_paid for song in keep):
        marked = [ln for ln in log.splitlines() if ln.startswith("[VIP")]
        check("下载日志里有带标记的进度行", bool(marked), marked[:2])
        check(
            "标记跟着歌名而不是另起一行",
            all(ln.split(" ")[0].startswith("[") for ln in marked),
            marked[:1],
        )
    else:
        print("      （这 2 首都不付费，真机标记断言跳过）", flush=True)

# ====================================================================== #
print("[3] 关掉查重后，应当把原始目标直接交给 ncmctl", flush=True)
submitted.clear()
page._plan = None
page.skip_existing.setChecked(False)
page.targets.setPlainText("1901371647\n2161154646")
page._start()
pump(lambda: bool(submitted), 10)
check("提交了作业", len(submitted) == 1)
if submitted:
    argv = submitted[0][1]
    assert argv[0] == "download", argv
    check("原始目标原样传递", positionals(argv) == ["1901371647", "2161154646"], argv)

# ====================================================================== #
print("[4] 「仅查重」不应当触发下载", flush=True)
submitted.clear()
page._plan = None
page.skip_existing.setChecked(True)
page.output.set_path(str(out))
page.targets.setPlainText(PLAYLIST_URL.format(playlist_id))
page._preview()
pump(lambda: page._task is not None and page._task.finished, 240)
pump(lambda: page.report_label.text().startswith("共"), 5)  # 等队列里的 done 信号落地
check("没有提交下载作业", not submitted, submitted)
check("有查重结论", page.report_label.text().startswith("共"), page.report_label.text())

# ====================================================================== #
# 会员语气：离线构造，三种状态都要说对话
print("[5] 会员状态影响文案（离线）", flush=True)
free = Song(1, "免费歌", ("甲",))
vip = Song(2, "会员歌", ("乙",), fee=1)


def paid_plan(vip_state: bool | None) -> Plan:
    return Plan(songs=[free, vip], missing=[vip], present=[free], vip=vip_state)


for state, expect, forbid in (
    (True, "通常能下", "多半会失败"),
    (False, "多半会失败", "通常能下"),
    (None, "多半是它们", "当前账号"),
):
    text = "\n".join(DownloadPage._intro_for(paid_plan(state), [vip]))
    check(f"会员={state} 的开场白", expect in text and forbid not in text, text)

check("全免费时不开场白", DownloadPage._intro_for(
    Plan(songs=[free], missing=[free]), [free]) == [], True)

print(flush=True)
if fails:
    print("失败：", fails)
    sys.exit(1)
print("界面集成测试全部通过")
