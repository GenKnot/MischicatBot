#!/usr/bin/env python3
"""机器人台词的写作工具（让任何 AI 都能接着扩写）。在仓库根目录运行：

    .venv/bin/python scripts/dialogue_tool.py coverage                 # 各原型写了多少、缺哪些
    .venv/bin/python scripts/dialogue_tool.py prompt 豪爽              # 出一份给 AI 的提示词（默认补缺口）
    .venv/bin/python scripts/dialogue_tool.py prompt 阴鸷 --scenes greet,gift_love --tiers 陌生,至交 -n 6
    .venv/bin/python scripts/dialogue_tool.py merge 豪爽 reply.json --batch gpt-0610   # 收稿：校验后并入
    .venv/bin/python scripts/dialogue_tool.py check                    # 校验所有台词文件与角色卡

    .venv/bin/python scripts/dialogue_tool.py chatter-coverage         # 主动搭话（条件化文案库）覆盖表
    .venv/bin/python scripts/dialogue_tool.py chatter-prompt chatter_arrive -n 8   # 出提示词
    .venv/bin/python scripts/dialogue_tool.py chatter-merge chatter_arrive reply.json --batch gpt-1013

完整流程见 data/bot_dialogues/README.md 和 data/CONTENT_GUIDE.md。
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("DB_PATH", os.path.join(ROOT, "game.db"))          # 只为让模块能导入；不读写数据库

from utils import bot_dialogue as bd                                      # noqa: E402
from utils import bot_dialogue_tools as tools                             # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("coverage", help="各原型的台词覆盖情况")
    p.add_argument("archetype", nargs="*")
    p.add_argument("--target", type=int, default=tools.DEFAULT_TARGET, help="每个格子至少几句才算写够")
    p = sub.add_parser("prompt", help="生成给 AI 的提示词")
    p.add_argument("archetype")
    p.add_argument("--scenes", help="逗号分隔；不给就取缺口里涉及的场景")
    p.add_argument("--tiers", help="逗号分隔；不给就取缺口里涉及的档位")
    p.add_argument("-n", type=int, default=tools.DEFAULT_TARGET, help="每个格子要写几句新的")
    p.add_argument("--target", type=int, default=tools.DEFAULT_TARGET)
    p = sub.add_parser("merge", help="校验并合并 AI 返回的 JSON")
    p.add_argument("archetype")
    p.add_argument("file", help="AI 返回的 JSON 文件；写 - 表示从标准输入读")
    p.add_argument("--batch", help="写到独立的批次文件 <原型>.<批次名>.json（推荐，不同 AI 互不覆盖）")
    p.add_argument("--dry-run", action="store_true", help="只校验，不写文件")
    sub.add_parser("check", help="校验所有台词文件、角色卡与特质池")
    p = sub.add_parser("traits-prompt", help="生成给 AI 的提示词：扩写特质池（出身 / 习惯 / 星座 / 嗜好 / 往事 / 口头禅）")
    p.add_argument("pool", choices=tools.TRAIT_POOLS)
    p.add_argument("-n", type=int, default=8)
    p = sub.add_parser("traits-merge", help="校验并合并 AI 写的特质条目")
    p.add_argument("pool", choices=tools.TRAIT_POOLS)
    p.add_argument("file", help="AI 返回的 JSON；- 表示标准输入")
    p.add_argument("--batch")
    p.add_argument("--dry-run", action="store_true")
    sub.add_parser("chatter-coverage", help="条件化文案库（主动搭话）的覆盖情况")
    p = sub.add_parser("chatter-prompt", help="生成给 AI 的提示词：为主动搭话的某个场景扩写规则")
    p.add_argument("scene")
    p.add_argument("-n", type=int, default=8)
    p.add_argument("--archetypes", help="逗号分隔；不给就覆盖所有性格")
    p = sub.add_parser("chatter-merge", help="校验并合并 AI 写的搭话规则")
    p.add_argument("scene")
    p.add_argument("file", help="AI 返回的 JSON；- 表示标准输入")
    p.add_argument("--batch")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("sample", help="抽样看多样性：同一性格、场景、档位，不同的机器人会怎么说")
    p.add_argument("archetype")
    p.add_argument("scene")
    p.add_argument("tier")
    p.add_argument("-n", type=int, default=12)
    p.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)

    if a.cmd == "coverage":
        print(tools.coverage_report(a.archetype or None, a.target))
    elif a.cmd == "prompt":
        split = lambda s: s.split(",") if s else None                    # noqa: E731
        print(tools.build_prompt(a.archetype, split(a.scenes), split(a.tiers), a.n, a.target))
    elif a.cmd == "merge":
        raw = sys.stdin.read() if a.file == "-" else open(a.file, encoding="utf-8").read()
        res = tools.merge_lines(a.archetype, raw, a.batch, a.dry_run)
        if not res["ok"]:
            print("未写入，请让 AI 修正以下问题：", *res["errors"], sep="\n  - ")
            return 1
        print(f"{'（试运行）' if a.dry_run else ''}新增 {res['added']} 句，重复跳过 {res['duplicates']} 句 → {res['path']}")
    elif a.cmd == "check":
        from utils import bot_traits as bt
        from utils import bot_chatter_lines as cl
        errors = bd.validate_all() + tools.validate_voices(tools.load_voices()) + bt.validate_pools() + cl.validate_all()
        print("\n".join(errors) if errors else "全部合法")
        return 1 if errors else 0
    elif a.cmd == "chatter-coverage":
        print(tools.chatter_report())
    elif a.cmd == "chatter-prompt":
        print(tools.chatter_prompt(a.scene, a.n, a.archetypes.split(",") if a.archetypes else None))
    elif a.cmd == "chatter-merge":
        raw = sys.stdin.read() if a.file == "-" else open(a.file, encoding="utf-8").read()
        res = tools.chatter_merge(a.scene, raw, a.batch, a.dry_run)
        if not res["ok"]:
            print("未写入，请让 AI 修正以下问题：", *res["errors"], sep="\n  - ")
            return 1
        print(f"{'（试运行）' if a.dry_run else ''}新增 {res['added_rules']} 条规则 / {res['added_lines']} 句，重复跳过 {res['duplicates']} 句 → {res['path']}")
    elif a.cmd == "traits-prompt":
        print(tools.traits_prompt(a.pool, a.n))
    elif a.cmd == "traits-merge":
        raw = sys.stdin.read() if a.file == "-" else open(a.file, encoding="utf-8").read()
        res = tools.traits_merge(a.pool, raw, a.batch, a.dry_run)
        if not res["ok"]:
            print("未写入，请让 AI 修正以下问题：", *res["errors"], sep="\n  - ")
            return 1
        print(f"{'（试运行）' if a.dry_run else ''}新增 {res['added']} 个，已存在跳过 {res['skipped']} 个 → {res['path']}")
    elif a.cmd == "sample":
        print("\n".join(tools.sample_lines(a.archetype, a.scene, a.tier, a.n, a.seed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
