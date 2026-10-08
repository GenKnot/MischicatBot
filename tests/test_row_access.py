"""守卫：不许对 SQLAlchemy 2 的 Row 用字符串下标。

`row["列名"]` 在 SQLAlchemy 2 的 Row 上抛 TypeError（要写 `row._mapping["列名"]`）。
它不会在导入时炸，只在那条分支真跑到时炸，而且常常落在 `except Exception` 里被吞掉 ——
出关私信丢了、探险发现宗门/装备掉落崩了，都是这么潜伏下来的。

静态扫描：找「由 fetchone/fetchall/all/first 得到的变量（及对其迭代的循环变量）」
被字符串下标的地方。同步 sqlite3 且设了 row_factory=sqlite3.Row 的模块支持字符串下标，
列入白名单。
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 这些模块用的是同步 sqlite3 + sqlite3.Row（或先转成 dict），字符串下标是合法的。
SQLITE3_ROW_MODULES = {
    "utils/db.py",
    "utils/views/menu.py",
    "web/main.py",
}

FETCH_ATTRS = {"fetchone", "fetchall", "all", "first", "one", "one_or_none"}
LIST_ATTRS = {"fetchall", "all"}


def _fetch_attr(node):
    node = node.value if isinstance(node, ast.Await) else node
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in FETCH_ATTRS:
        return node.func.attr
    return None


def _subscripts_of(scope, name):
    for node in ast.walk(scope):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == name \
                and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            yield node


def _violations(path: pathlib.Path):
    """逐个「行变量 + 它的作用范围」检查，避免同名循环变量在别处复用造成误报。"""
    tree = ast.parse(path.read_text())
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        row_scopes = []                                  # (变量名, 作用范围节点)
        list_vars = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                attr = _fetch_attr(node.value)
                if attr in LIST_ATTRS:
                    list_vars.add(node.targets[0].id)
                elif attr:
                    row_scopes.append((node.targets[0].id, fn))        # 单行：整个函数内有效
        for node in ast.walk(fn):
            if isinstance(node, ast.For) and isinstance(node.iter, ast.Name) \
                    and node.iter.id in list_vars and isinstance(node.target, ast.Name):
                row_scopes.append((node.target.id, node))              # 循环变量：只在这个循环里
            if isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.SetComp, ast.DictComp)):
                for g in node.generators:
                    if isinstance(g.iter, ast.Name) and g.iter.id in list_vars and isinstance(g.target, ast.Name):
                        row_scopes.append((g.target.id, node))
        for name, scope in row_scopes:
            for node in _subscripts_of(scope, name):
                yield f"{path.relative_to(ROOT)}:{node.lineno}  {ast.unparse(node)}"


def _source_files():
    for sub in ("cogs", "utils", "web"):
        yield from (ROOT / sub).rglob("*.py")
    for name in ("bot.py", "main.py"):
        if (ROOT / name).exists():
            yield ROOT / name


def test_不对_SQLAlchemy_Row_用字符串下标():
    found = []
    for path in _source_files():
        if str(path.relative_to(ROOT)) in SQLITE3_ROW_MODULES:
            continue
        found.extend(_violations(path))
    assert not found, (
        "下面这些地方对 SQLAlchemy 2 的 Row 用了字符串下标，运行时会抛 TypeError，"
        "请改成 row._mapping['列名']：\n  " + "\n  ".join(found)
    )


def test_守卫自己能抓到违规写法(tmp_path):
    """守卫要是抓不到，就是摆设。"""
    bad = tmp_path / "bad.py"
    bad.write_text(
        "async def f(session):\n"
        "    row = (await session.execute('x')).fetchone()\n"
        "    return row['name']\n"
        "async def g(session):\n"
        "    rows = (await session.execute('x')).fetchall()\n"
        "    return [r['name'] for r in rows]\n"
        "async def ok(session):\n"
        "    row = (await session.execute('x')).fetchone()\n"
        "    return row._mapping['name'], row[0]\n"
    )
    bad_rel = tmp_path / "bad.py"
    got = list(_violations_abs(bad_rel))
    assert len(got) == 2 and all("name" in g for g in got)


def _violations_abs(path):
    # _violations 用 relative_to(ROOT) 排版，测试文件不在仓库里，借一个同构的包装
    global ROOT
    old, ROOT = ROOT, path.parent
    try:
        yield from _violations(path)
    finally:
        ROOT = old
