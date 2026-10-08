"""守卫：一次性按钮的回调必须「先占位、后 defer」。

`interaction.response.defer()` 要走网络。回调里若先 `await defer()` 再 `self.view.stop()`，
两次几乎同时的点击会在 stop() 之前一起越过入口，奖励/扣费各结算两遍。
正确写法是回调开头、第一个 await 之前调用 `TimedView.try_claim()`（或自己检查 `is_finished()`）。

这条守卫是**棘轮**：现存的违规列在 KNOWN_DEBT 里，只许减少不许增加 ——
新增违规会红；修好之后条目必须从清单里删掉（否则也会红），清单只会越来越短。
修之前先判断那个回调里的写入是否幂等：幂等的（如绝对值覆盖）连点无害，可以长期留在清单里并注明。
"""

import ast
import pathlib


ROOT = pathlib.Path(__file__).resolve().parent.parent

# 待处理的存量，格式 "相对路径::类名.函数名"。修好一个就删一行。目前已清零。
KNOWN_DEBT = set()

# 已逐个核对过、确认连点无害的写法，**必须写明理由**。它们仍然是「先 defer 后 stop」，
# 所以必须一直留在这里，否则守卫会把它们当成新增违规。
# 理由失效（比如回调里新增了不幂等的写入）时，应当把它从这里挪出来、改用 try_claim()。
REVIEWED_SAFE = {
    "utils/views/gathering.py::GatherButton.callback":
        "写入是一条带条件的 UPDATE（未在采集 + 寿元够 + buff 表 CAS），靠 rowcount 判定，"
        "连点的第二次得到「状态已变化」；失败路径不一定作废面板，玩家可以重试。",
    "utils/views/cultivation.py::CultivateButton.callback":
        "开始闭关：写入是绝对值覆盖（cultivating_until / cultivating_years），连点结果一致，"
        "没有奖励类写入，寿元也不在开始时扣；最多多发一条消息。",
    "utils/views/cultivation.py::_BackToMenuButton.callback":
        "返回主菜单：只读 + 按时间结算（settle_time 以 last_active 为基准，重复调用幂等），无奖励类写入。",
}


def _is_button_callback(fn) -> bool:
    if fn.name == "callback":
        return True
    for d in fn.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        if isinstance(target, ast.Attribute) and target.attr in ("button", "select"):
            return True
    return False


def _offenders():
    found = set()
    files = list((ROOT / "cogs").rglob("*.py")) + list((ROOT / "utils" / "views").rglob("*.py"))
    for path in files:
        tree = ast.parse(path.read_text())
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            for fn in cls.body:
                if not isinstance(fn, ast.AsyncFunctionDef) or not _is_button_callback(fn):
                    continue
                src = ast.unparse(fn)
                if "response.defer" not in src:
                    continue
                if any(m in src for m in ("try_claim", "try_hold", "is_finished")):
                    continue
                # 「作废面板」的写法：stop() 或 finish()
                ends = [src.index(m) for m in (".stop()", ".finish()") if m in src]
                if ends and src.index("response.defer") < min(ends):
                    found.add(f"{path.relative_to(ROOT)}::{cls.name}.{fn.name}")
    return found


def test_不许新增先_defer_后_stop_的一次性按钮():
    new = _offenders() - KNOWN_DEBT - set(REVIEWED_SAFE)
    assert not new, (
        "这些按钮回调先 await defer 再 stop()，连点会重复结算。"
        "请在回调开头、第一个 await 之前调用 self.view.try_claim()（见 utils/views/base.py）；"
        "确认连点无害的话，写进 REVIEWED_SAFE 并注明理由：\n  "
        + "\n  ".join(sorted(new)))


def test_清单里修好的条目必须删掉():
    """棘轮的另一半：清单只许缩短。修好了还留在清单里，说明有人忘了更新。"""
    stale = (KNOWN_DEBT | set(REVIEWED_SAFE)) - _offenders()
    assert not stale, "这些条目已经不再违规，请从清单删掉：\n  " + "\n  ".join(sorted(stale))


def test_已核对安全的条目都写明了理由():
    assert all(len(reason) >= 20 for reason in REVIEWED_SAFE.values())


def test_守卫自己能抓到违规写法(tmp_path, monkeypatch):
    """守卫要是抓不到，就是摆设。"""
    bad = tmp_path / "cogs"
    bad.mkdir()
    (bad / "x.py").write_text(
        "class V:\n"
        "    async def callback(self, interaction):\n"
        "        await interaction.response.defer()\n"
        "        self.view.stop()\n"
        "class Good:\n"
        "    async def callback(self, interaction):\n"
        "        if not self.view.try_claim():\n"
        "            return\n"
        "        await interaction.response.defer()\n"
        "class Other:\n"
        "    async def callback(self, interaction):\n"
        "        self.view.stop()\n"
        "        await interaction.response.defer()\n"
        "class Held:\n"
        "    async def callback(self, interaction):\n"
        "        if not self.view.try_hold():\n"
        "            return\n"
        "        await interaction.response.defer()\n"
        "        self.view.finish()\n"
        "class BadFinish:\n"
        "    async def callback(self, interaction):\n"
        "        await interaction.response.defer()\n"
        "        self.view.finish()\n"
    )
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    (tmp_path / "utils" / "views").mkdir(parents=True)

    assert _offenders() == {"cogs/x.py::V.callback", "cogs/x.py::BadFinish.callback"}


def test_探险的面板都是_timedview():
    """cogs 里的面板不在 test_views_base 的扫描范围内，探险这几个单独守一下。"""
    from cogs import explore
    from utils.views.base import TimedView
    for name in ("ExploreView", "ExploreNextView", "ExploreResultView"):
        assert issubclass(getattr(explore, name), TimedView), name
