"""守卫：灵石 / 物品数量的写入必须是条件写，不许「读出来 → 判断 → 写成绝对值」。

这是本项目反复出现的一种 bug 形态（ISSUES.md C1、B12、B19，以及 `修炼功法`）：
- 把「读到的余额 - 花费」**写成绝对值**：读和写之间别处到账的收入被抹掉；别处花掉的灵石又被「写回去」（凭空造钱）；
- 扣减**没有余额保护**，或用 `MAX(0, …)` 把不足夹成 0：付不起的人照样拿到东西，对方却收了全额（B19）；
- 调了 `spend_stones` / `consume_item` 这类「可能失败」的原语却**不看返回值**。

正确做法见 CONVENTIONS #1：用 `utils/atomic.py` 的原语，或把条件写进 UPDATE 的 WHERE、靠 rowcount 判断。

静态扫描 `cogs/ utils/ web/`。已逐个核对过确实安全的例外写在 REVIEWED 里，**必须附理由**；
清单只许缩短 —— 例外不再违规时必须删掉（否则也会红）。
"""

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent

CHECKED_CALLS = {"spend_stones", "consume_item", "remove_item", "claim_daily_quota", "claim_cooldown", "claim_highest_bid"}

# 已核对过的例外："相对路径::函数名::类型" → 理由
REVIEWED = {
    "utils/death_rebirth_logic.py::handle_rebirth::ORM赋值":
        "轮回重生时重置为启动资金 500，本来就是丢弃旧值。",
    "utils/events/public/wanbao.py::settle_lot::夹零扣减":
        "流拍取回费：卖家付得起多少付多少（不允许扣成负数）；物品照退，不存在「付不起却拿到东西」。",
}


def _files():
    for sub in ("cogs", "utils", "web"):
        yield from (ROOT / sub).rglob("*.py")
    for name in ("bot.py", "main.py"):
        if (ROOT / name).exists():
            yield ROOT / name


def _strings(node):
    for n in ast.walk(node):
        if isinstance(n, ast.JoinedStr):
            yield "".join(v.value if isinstance(v, ast.Constant) else "{…}" for v in n.values)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            yield n.value


def _classify_sql(sql: str):
    """返回 [(列, 类型)]：只关心 UPDATE 里对灵石 / 数量的写法。"""
    low = " ".join(sql.split()).lower()
    if not low.startswith(("update", "insert")) and " update " not in f" {low}":
        return []
    out = []
    m = re.search(r"\bset\s+(.*?)(\swhere\s|$)", low)
    setpart = m.group(1) if m else ""
    where = low.split(" where ", 1)[1] if " where " in low else ""
    for col in ("spirit_stones", "quantity"):
        if col not in setpart:
            continue
        if re.search(rf"{col}\s*=\s*max\(", setpart):
            out.append((col, "夹零扣减"))
        elif re.search(rf"{col}\s*=\s*{col}\s*-", setpart):
            if not re.search(rf"{col}\s*>=", where):
                out.append((col, "无保护扣减"))
        elif re.search(rf"{col}\s*=\s*:", setpart) or re.search(rf"{col}\s*=\s*\d", setpart):
            out.append((col, "绝对值赋值"))
    return out


def _call_name(call):
    f = call.func
    return f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)


def find_violations(files):
    found = set()
    for path in files:
        if path.name in ("atomic.py", "db_async.py"):
            continue
        rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name
        tree = ast.parse(path.read_text())
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for s in _strings(fn):
                for col, kind in _classify_sql(s):
                    found.add(f"{rel}::{fn.name}::{kind}")
            for n in ast.walk(fn):
                # ORM 属性写灵石 / 数量
                targets = []
                if isinstance(n, ast.AugAssign):
                    targets = [n.target]
                elif isinstance(n, ast.Assign):
                    targets = n.targets
                for t in targets:
                    if isinstance(t, ast.Attribute) and t.attr in ("spirit_stones", "quantity"):
                        found.add(f"{rel}::{fn.name}::ORM赋值")
                # 忽略「可能失败」原语的返回值
                if isinstance(n, ast.Expr):
                    v = n.value.value if isinstance(n.value, ast.Await) else n.value
                    if isinstance(v, ast.Call) and _call_name(v) in CHECKED_CALLS:
                        found.add(f"{rel}::{fn.name}::忽略返回值:{_call_name(v)}")
    return found


def test_灵石与数量的写入都是条件写():
    new = find_violations(_files()) - set(REVIEWED)
    assert not new, (
        "这些地方把灵石 / 物品数量写成绝对值、没有余额保护地扣减、或忽略了扣减原语的返回值。\n"
        "请改用 utils/atomic.py 的原语（spend_stones / consume_item / increment_player / cas_player_field），\n"
        "或把条件写进 UPDATE 的 WHERE 并用 rowcount 判断（CONVENTIONS #1）；确认安全的话写进 REVIEWED 并注明理由：\n  "
        + "\n  ".join(sorted(new)))


def test_清单里不再违规的例外必须删掉():
    stale = set(REVIEWED) - find_violations(_files())
    assert not stale, "这些例外已经不再违规，请从 REVIEWED 删掉：\n  " + "\n  ".join(sorted(stale))


def test_例外都写明了理由():
    assert all(len(reason) >= 10 for reason in REVIEWED.values())


def test_守卫自己能抓到各种违规写法(tmp_path):
    """守卫要是抓不到，就是摆设。"""
    bad = tmp_path / "bad.py"
    bad.write_text(
        "async def abs_write(session, uid, n):\n"
        "    await session.execute(text('UPDATE players SET spirit_stones = :stones WHERE discord_id = :uid'), {})\n"
        "async def unguarded(session, uid):\n"
        "    await session.execute(text('UPDATE players SET spirit_stones = spirit_stones - :c WHERE discord_id = :uid'), {})\n"
        "async def clamped(session, uid):\n"
        "    await session.execute(text('UPDATE players SET spirit_stones = MAX(0, spirit_stones - :c) WHERE discord_id = :uid'), {})\n"
        "async def orm(player):\n"
        "    player.spirit_stones -= 5\n"
        "    inv.quantity = 3\n"
        "async def ignored(session, uid):\n"
        "    await spend_stones(session, uid, 10)\n"
        "    await consume_item(session, uid, 'x', 1)\n"
        "async def good(session, uid):\n"
        "    if not await spend_stones(session, uid, 10):\n"
        "        return\n"
        "    await session.execute(text('UPDATE players SET spirit_stones = spirit_stones - :c "
        "WHERE discord_id = :uid AND spirit_stones >= :c'), {})\n"
        "    await session.execute(text('UPDATE players SET spirit_stones = spirit_stones + :c WHERE discord_id = :uid'), {})\n"
        "    await session.execute(text('UPDATE players SET lifespan = :l WHERE discord_id = :uid'), {})\n"
    )

    got = find_violations([bad])

    assert got == {
        "bad.py::abs_write::绝对值赋值", "bad.py::unguarded::无保护扣减", "bad.py::clamped::夹零扣减",
        "bad.py::orm::ORM赋值", "bad.py::ignored::忽略返回值:spend_stones", "bad.py::ignored::忽略返回值:consume_item",
    }


def test_任务数据里没有负的灵石奖励():
    """任务奖励走 `increment_player`，它不设下限 —— 负的灵石奖励会把玩家的灵石扣成负数。
    （探险事件里有 179 处负奖励，但那条路径用了 MAX(0, …) 夹零，不受影响。）"""
    import utils.quests as q

    negatives = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "spirit_stones" and isinstance(v, (int, float)) and v < 0:
                    negatives.append(f"{path}: {v}")
                walk(v, f"{path}/{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")
    for name in dir(q):
        obj = getattr(q, name)
        if isinstance(obj, (list, dict)):
            walk(obj, name)

    assert not negatives, f"任务数据里有负的灵石奖励：{negatives}"
