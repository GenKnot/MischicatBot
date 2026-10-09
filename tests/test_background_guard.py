"""静态守卫：后台任务必须经过 utils/tasks.py 的两个工具（ISSUES.md B17、B24、B26）。

1. 每个 `@tasks.loop` 循环体必须带 `@loop_guard(...)` —— 否则一次意外异常就让它永久停止。
2. 不允许把 `create_task(...)` 当裸语句发出去不管 —— 用 `spawn(...)`，或者把返回值存起来。
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
FILES = [p for d in ("cogs", "utils", "web") for p in (ROOT / d).rglob("*.py")]


def _name(node) -> str:
    return ast.unparse(node.func if isinstance(node, ast.Call) else node)


def _scan():
    loops, bare = [], []
    for path in FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                names = [_name(d) for d in node.decorator_list]
                if any(n.endswith("tasks.loop") for n in names):
                    loops.append((rel, node.name, "loop_guard" in names))
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                if _name(node.value).endswith("create_task"):
                    bare.append(f"{rel}:{node.lineno}")
    return loops, bare


def test_每个tasks_loop都带loop_guard():
    loops, _ = _scan()
    assert loops, "扫描不到任何 @tasks.loop，守卫失效了"
    missing = [f"{f}::{n}" for f, n, ok in loops if not ok]
    assert not missing, f"这些循环没有 @loop_guard，一次异常就会永久停止：{missing}"


def test_不允许裸create_task():
    _, bare = _scan()
    assert not bare, f"用 utils.tasks.spawn 代替裸 create_task：{bare}"
