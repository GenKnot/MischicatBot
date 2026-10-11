"""机器人经济离线模拟（scripts/sim_bots.py）。

模拟本身是个『会算账的模型』，错了会把参数带偏，所以要有测试：
· 账目守恒：新钱 = 现存 + 开销 + 买丹 + 被劫 + 死者遗产，在各种参数下差额为 0；
· 约束：全服上限、天花板、补员上限、单次劫财上限、人口不超目标；
· 确定性：同一个种子同一份结果；
· 规则取自游戏本身：改了 `cultivation_needed` 模拟立刻跟着变（没有偷偷抄一份）；
· 命令行与报告能跑通。
"""

import importlib.util
import io
import os
from contextlib import redirect_stdout

import pytest

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "sim_bots.py")
_spec = importlib.util.spec_from_file_location("sim_bots", _PATH)
sb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sb)


def run(**kw):
    kw.setdefault("bots", 60)
    kw.setdefault("days", 40)
    return sb.Sim(sb.Params(**kw)).run()


SCENARIOS = [
    {}, {"seed": 7}, {"cap_stones": 3000}, {"human_top": "无"}, {"human_top": "炼气期"},
    {"robbers": 0, "robs_each": 0}, {"robbers": 20, "robs_each": 10}, {"material_cap_value": 50},
    {"pill_price": {"筑基丹": 1, "凝丹丹": 1, "化婴丹": 1}}, {"refill_rate": 1.0},
]


@pytest.mark.parametrize("kw", SCENARIOS)
def test_账目守恒(kw):
    sim = run(**kw)
    assert abs(sim.ledger_gap()) < 1e-6, kw


def test_同一个种子同一份结果():
    a, b = run(seed=3), run(seed=3)
    assert a.daily == b.daily and dict(a.flow) == dict(b.flow)
    assert run(seed=4).daily != a.daily


def test_全服日收入不超过上限():
    sim = run(cap_stones=2000)
    assert all(d["income_paid"] <= 2000 + 1e-6 for d in sim.daily)
    assert any(d["income_wanted"] > 2000 for d in sim.daily), "上限没起作用就失去了意义"


def test_不设限时按想要的发():
    sim = run(cap_stones=10**9)
    assert all(abs(d["income_paid"] - d["income_wanted"]) < 1e-6 for d in sim.daily)


def test_天花板_没有人被突破推过去():
    sim = run(human_top="炼气期", days=120)
    ceiling = sim.ceiling
    assert all(b.spawn_idx > ceiling or sb.get_realm_index(b.realm) <= ceiling for b in sim.bots)
    assert sum(d["breakthroughs"] for d in sim.daily) > 0, "炼气期内部的小层突破应该照常发生"


def test_天花板_无则放开():
    capped, free = run(human_top="炼气期", days=150, bots=100), run(human_top="无", days=150, bots=100)
    top = lambda s: max(sb.get_realm_index(b.realm) for b in s.bots)   # noqa: E731
    assert top(free) > top(capped)


def test_出生就按天花板收住():
    """生成 / 补员和每日结算一样遵守天花板：没有机器人出生在天花板之上。"""
    sim = run(human_top="炼气期", bots=300, days=60, refill_rate=1.0)
    assert sim.flow["spawn_above_ceiling"] == 0
    assert all(sb.get_realm_index(b.realm) <= sim.ceiling for b in sim.bots)


def test_补员有上限_人口不超目标():
    sim = run(bots=100, days=120, refill_rate=0.02)
    assert all(d["pop"] <= 100 for d in sim.daily)
    assert all(d["refill"] <= 5 for d in sim.daily), "2% = 2 个，被『每天至少 5 个』的下限抬到 5"
    assert sum(d["deaths"] for d in sim.daily) > 0


def test_补员补到目标():
    sim = run(bots=50, days=90, refill_rate=1.0)
    assert all(d["pop"] == 50 for d in sim.daily)


def test_劫财单次与总量有上限():
    sim = run(rob_cap=5, robbers=3, robs_each=4)
    assert all(d["robbed"] <= 3 * 4 * 5 + 1e-6 for d in sim.daily)
    assert sim.flow["robbed"] > 0
    assert run(robbers=0, robs_each=0).flow["robbed"] == 0


def test_材料有上限时被截断():
    sim = run(material_cap_value=10)
    assert all(d["mat_value"] <= 10 + 1e-6 for d in sim.daily)
    assert run(material_cap_value=0).flow["mat_value"] > sim.flow["mat_value"]


def test_买不起丹就卡关_便宜了就能过():
    poor = run(pill_price={"筑基丹": 10**9, "凝丹丹": 10**9, "化婴丹": 10**9}, days=200, bots=100)
    assert poor.flow["pills"] == 0 and poor.gate_wait_days > 0
    cheap = run(pill_price={"筑基丹": 1, "凝丹丹": 1, "化婴丹": 1}, days=200, bots=100)
    assert cheap.flow["pills"] > 0


def test_修为规则取自游戏本身(monkeypatch):
    """把 cultivation_needed 改成永远够不着：模拟里就不会有任何突破。"""
    monkeypatch.setattr(sb, "cultivation_needed", lambda realm: 10**9)
    sim = run(days=60)
    assert sum(d["breakthroughs"] + d["bt_failures"] for d in sim.daily) == 0


def test_寿元耗尽会死():
    sim = run(bots=40, days=200)
    assert sum(n for (_, cause), n in sim.deaths.items() if cause == "寿元耗尽") > 0


def test_速度越快死得越多():
    slow = run(bots=100, days=100, speed={"炮灰": 0.05, "正常": 0.05, "天骄": 0.05})
    fast = run(bots=100, days=100, speed={"炮灰": 0.9, "正常": 0.9, "天骄": 0.9})
    assert sum(slow.deaths.values()) < sum(fast.deaths.values())


def test_每日记录键齐全():
    """安静的一天也不能缺键（曾经只在事件发生时才有键，报告里 KeyError）。"""
    sim = run(robbers=0, robs_each=0, days=3, bots=5)
    for d in sim.daily:
        assert {"income_paid", "upkeep", "pills", "robbed", "mat_value", "deaths", "refill", "pop"} <= set(d)


def test_报告能生成且包含各节():
    sim = run(days=30)
    text = sb.report(sim, power=None)
    for part in ("## 参数", "## 逐阶段", "## 全程账目", "账目差额", "## 材料", "## 终局人口", "## 死亡与更替", "劫匪每天"):
        assert part in text, part


def test_战力对比表():
    rows = sb.power_table(realms=("炼气期5层",), samples=200)
    assert len(rows) == 2 * 3
    by = {(r["human"], r["tier"]): r for r in rows}
    assert by[("用心", "炮灰")]["ratio"] > by[("用心", "正常")]["ratio"] > by[("用心", "天骄")]["ratio"]
    assert by[("用心", "正常")]["ratio"] > by[("普通", "正常")]["ratio"]
    assert 0 <= by[("普通", "天骄")]["win"] <= 1


def test_命令行跑通():
    buf = io.StringIO()
    with redirect_stdout(buf):
        sim = sb.main(["--bots", "20", "--days", "10", "--no-power", "--pill-price", "1", "2", "3", "--human-top", "无"])
    assert "机器人经济离线模拟" in buf.getvalue() and sim.p.pill_price["凝丹丹"] == 2 and sim.p.human_top == "无"


def test_命令行可导出JSON(tmp_path):
    out = tmp_path / "o.json"
    with redirect_stdout(io.StringIO()):
        sb.main(["--bots", "10", "--days", "5", "--no-power", "--json", str(out)])
    import json
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["daily"]) == 5 and data["params"]["bots"] == 10


def test_不读写数据库():
    """脚本导入后不应该创建 / 修改仓库根目录的 game.db。"""
    db = os.path.join(os.path.dirname(_PATH), "..", "game.db")
    before = os.path.getmtime(db) if os.path.exists(db) else None
    run(days=5)
    after = os.path.getmtime(db) if os.path.exists(db) else None
    assert before == after
