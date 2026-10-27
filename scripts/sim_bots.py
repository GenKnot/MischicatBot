#!/usr/bin/env python3
"""机器人经济的离线模拟（U1「江湖百态」）。

跑法（在仓库根目录）：

    .venv/bin/python scripts/sim_bots.py                       # 500 个机器人 × 180 天，默认参数
    .venv/bin/python scripts/sim_bots.py --bots 200 --days 90 --cap-stones 30000
    .venv/bin/python scripts/sim_bots.py --human-top 结丹期     # 假设最高真人已到结丹期
    .venv/bin/python scripts/sim_bots.py --json out.json        # 另存逐日数据

**不碰数据库、不碰线上代码**。修为增长、突破成功率与失败惩罚、寿元上限、战力公式、打工表、机器人属性生成，
全部直接调用游戏里的规则函数 —— 规则改了，模拟自动跟着变。游戏里**还没有**的东西（每日结算、劫财、补员、机器人开销）
按 `.gk/ISSUES.md`「经济参数」里用户 2026-10-10 定的数值建模，写在下面的 `Params` 里，命令行都能改。

一天 = 12 游戏年（1 游戏年 = 现实 2 小时）。机器人每天「活跃」的游戏年数 = 12 × 速度系数；
寿元只在活跃的游戏年里消耗（和真人闭关一样）。

模型里的假设（都在报告开头列出，不确定的已标 ⚠）：
  · 机器人日收入 = 档位基数 × U(0.7, 1.3)，超过全服上限则按比例缩减；
  · 收入按性格分成「随身」和「钱庄」；钱庄无利息；开销只从随身扣；
  · 三道大关（筑基 / 凝丹 / 化婴）必须服丹，丹药价格 ⚠ 游戏里丹药没有标价，用 Params.pill_price 的估计；
    付不起就等，等的时候继续攒修为（封顶 2 倍）；普通小层突破不收费 ⚠；
  · 劫财：`robbers` 个真人，每人每天劫 `robs_each` 个**不同的**机器人，拿随身灵石的 30%（单次 ≤500）；
  · 材料：每天 3 次打工只用来掷「材料掉落」，概率 ×`material_discount`，价值取 items 表的 sell_price ⚠（采集的产出没建模）；
  · 死亡（寿元耗尽 / 突破失败）后其全部灵石消失；每天最多补目标数的 5%。
"""

import argparse
import asyncio
import json
import os
import random
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("DB_PATH", os.path.join(ROOT, "game.db"))          # 只为让模块能导入；脚本不读写数据库

from utils import bot_economy as be                                      # noqa: E402
from utils import bot_world                                              # noqa: E402
from utils.bot_social import generate_personality                        # noqa: E402
from utils.combat import calc_power                                      # noqa: E402
from utils.equipment import generate_equipment                           # noqa: E402
from utils.realms import (REALM_GROUPS, REALMS, apply_failure, cultivation_needed,   # noqa: E402
                          get_realm_index, lifespan_max_for_realm, major_realm, next_realm,
                          roll_breakthrough, roll_failure_outcome)

DAY_YEARS = 12            # 一天 = 12 游戏年
MAJORS = [m for m, _ in REALM_GROUPS]

GATES = be.GATES
CFG = be.load_config()          # 参数与每日结算共用 data/bot_economy.json


@dataclass
class Params:
    bots: int = 500
    days: int = 180
    seed: int = 1
    # 经济：默认值全部来自 data/bot_economy.json（每日结算用的同一份）
    income: dict = field(default_factory=lambda: dict(CFG["income"]))
    cap_stones: float = 0               # 0 = 按配置的「每个机器人每天 N」×人口；>0 = 直接指定全服每日上限
    speed: dict = field(default_factory=lambda: dict(CFG["speed"]))
    human_top: str = "筑基期"            # 当前最高真人所在大境；机器人不超过它。"无" = 不设天花板
    refill_rate: float = CFG["refill_rate"]
    rob_share: float = CFG["combat"]["rob"]["share"]
    rob_cap: int = CFG["combat"]["rob"]["cap"]
    robbers: int = 10
    robs_each: int = CFG["combat"]["rob"]["per_human_per_day"]
    material_discount: float = CFG["materials"]["discount"]
    material_cap_value: float = 0       # 0 = 不设上限，只统计
    # ⚠ 估计值：游戏里丹药没有标价
    pill_price: dict = field(default_factory=lambda: dict(CFG["pill_price"]))
    jobs_per_day: int = CFG["materials"]["jobs_per_day"]
    # 击杀：`hunters` 个真人，每人每天击杀 `kills_each` 个机器人（默认 0 = 不建模）
    hunters: int = 0
    kills_each: int = 0
    kill_share: float = CFG["combat"]["kill"]["share"]
    kill_cap: int = CFG["combat"]["kill"]["cap"]
    kill_global: int = CFG["combat"]["kill"]["global_per_day"]      # 全服每天最多被击杀几个

    def config(self) -> dict:
        """喂给 bot_economy 公式的配置：以文件为底，命令行 / 测试改过的覆盖上去。"""
        cfg = be.load_config()
        cfg["income"], cfg["speed"], cfg["pill_price"], cfg["refill_rate"] = (
            dict(self.income), dict(self.speed), dict(self.pill_price), self.refill_rate)
        cfg["materials"].update(discount=self.material_discount, jobs_per_day=self.jobs_per_day)
        return cfg


@dataclass
class Bot:
    id: int
    tier: str
    archetype: str
    stats: dict
    realm: str
    cultivation: float
    lifespan: float
    lifespan_max: int
    carry: float
    bank: float = 0.0
    born_day: int = 0
    first_gate_day: int | None = None
    spawn_idx: int = 0           # 出生时的境界下标（测试用：突破不能把人推过天花板）


def _roll_bot(rng: random.Random, serial: int, day: int, ceiling: int, tier: str | None = None) -> Bot:
    tier = tier or bot_world.roll_tier(rng)
    f = bot_world.roll_player_fields(rng, tier, f"sim{serial}", f"sim{serial}", 0.0, ceiling)
    arche = generate_personality(rng)["archetype"]
    keys = ("comprehension", "physique", "fortune", "bone", "soul", "spirit_root_type")
    return Bot(id=serial, tier=tier, archetype=arche, stats={k: f[k] for k in keys}, realm=f["realm"],
               cultivation=f["cultivation"], lifespan=f["lifespan"], lifespan_max=f["lifespan_max"],
               carry=f["spirit_stones"], born_day=day, spawn_idx=get_realm_index(f["realm"]))


def _ceiling_index(human_top: str) -> int:
    """机器人最高能到的境界下标（含）。人类最高大境的最后一个小境；"无" = 不限。"""
    if human_top in ("无", "", None):
        return len(REALMS) - 1
    last = [r for m, subs in REALM_GROUPS if m == human_top for r in subs][-1]
    return get_realm_index(last)


class Sim:
    def __init__(self, p: Params):
        self.p = p
        random.seed(p.seed)                                           # 游戏规则函数用的是全局 random
        self.rng = random.Random(p.seed)
        self.cfg = p.config()
        self.serial = 0
        self.bots: list[Bot] = []
        self.ceiling = _ceiling_index(p.human_top)
        self.flow = Counter()                                         # 累计账目
        self.deaths = Counter()
        self.daily: list[dict] = []
        self.gate_wait_days = 0
        for _ in range(p.bots):
            self._spawn(0, initial=True)

    # ---- 账 -----------------------------------------------------------------
    def _spawn(self, day: int, initial: bool = False):
        self.serial += 1
        bot = _roll_bot(self.rng, self.serial, day, self.ceiling)
        self.bots.append(bot)
        self.flow["endowment"] += bot.carry                           # 出生自带的灵石也是新钱
        if get_realm_index(bot.realm) > self.ceiling:
            self.flow["spawn_above_ceiling"] += 1                     # 出生就超过天花板（bot_world 的档位表没看天花板）
        return bot

    def money_in_bots(self) -> float:
        return sum(b.carry + b.bank for b in self.bots)

    # ---- 一天 ---------------------------------------------------------------
    def step(self, day: int) -> dict:
        p, rng = self.p, self.rng
        rec = defaultdict(float, dict.fromkeys(
            ("income_wanted", "income_paid", "upkeep", "pills", "robbed", "mat_count", "mat_value",
             "breakthroughs", "bt_failures", "deaths", "refill", "kill_reward", "killed"), 0.0))

        # 1. 收入（全服上限按比例缩减）
        wants = {b.id: be.daily_income(b.tier, self.cfg, rng) for b in self.bots}
        total_want = sum(wants.values())
        cap = p.cap_stones or self.cfg["daily_cap_per_bot"] * len(self.bots)
        scale = min(1.0, cap / total_want) if total_want else 1.0
        rec["income_wanted"] = total_want
        for b in self.bots:
            paid = wants[b.id] * scale
            carry_ratio = self.cfg["money"][b.archetype]["carry"]
            b.carry += paid * carry_ratio
            b.bank += paid * (1 - carry_ratio)
            rec["income_paid"] += paid
        self.flow["income"] += rec["income_paid"]

        # 2. 修炼 / 寿元 / 突破
        dead: list[tuple[Bot, str]] = []
        for b in self.bots:
            years = DAY_YEARS * p.speed[b.tier]
            gain = be.cultivation_gain(years, b.stats)
            need = cultivation_needed(b.realm)
            b.cultivation = min(b.cultivation + gain, need * 2)
            b.lifespan -= years
            if b.lifespan <= 0:
                dead.append((b, "寿元耗尽"))
                continue
            cause = self._try_breakthrough(b, day, rec)
            if cause:
                dead.append((b, cause))

        # 3. 日常开销（只从随身扣）
        for b in self.bots:
            if any(b is d for d, _ in dead):
                continue
            spend = b.carry * self.cfg["money"][b.archetype]["spend"]
            b.carry -= spend
            self.flow["upkeep"] += spend
            rec["upkeep"] += spend

        # 4. 劫财：真人各自劫若干个不同的机器人
        alive = [b for b in self.bots if not any(b is d for d, _ in dead)]
        for _ in range(p.robbers):
            for victim in rng.sample(alive, min(p.robs_each, len(alive))):
                take = min(victim.carry * p.rob_share, p.rob_cap)
                victim.carry -= take
                self.flow["robbed"] += take
                rec["robbed"] += take

        # 4b. 击杀：随身的一部分给击杀者，其余（随身剩下的 + 钱庄）随人消失
        killed = []
        for _ in range(p.hunters):
            pool = [b for b in alive if not any(b is k for k in killed)]
            room = max(0, p.kill_global - len(killed))
            for victim in rng.sample(pool, min(p.kills_each, len(pool), room)):
                reward = min(victim.carry * p.kill_share, p.kill_cap)
                victim.carry -= reward
                self.flow["kill_reward"] += reward
                rec["kill_reward"] += reward
                killed.append(victim)
        for victim in killed:
            self.flow["estate_lost"] += victim.carry + victim.bank
            self.deaths[(victim.tier, "被击杀")] += 1
            self.bots.remove(victim)
        alive = [b for b in alive if not any(b is k for k in killed)]
        rec["killed"] = len(killed)

        # 5. 材料
        mat_count = mat_value = 0.0
        for b in alive:
            drops = be.material_roll(b.realm, self.cfg, random)
            mat_count += len(drops)
            mat_value += sum(be.item_value(n) for n in drops)
        if p.material_cap_value and mat_value > p.material_cap_value:
            k = p.material_cap_value / mat_value
            mat_count, mat_value = mat_count * k, p.material_cap_value
        rec["mat_count"], rec["mat_value"] = mat_count, mat_value
        self.flow["mat_value"] += mat_value

        # 6. 死亡与补员
        for b, cause in dead:
            self.flow["estate_lost"] += b.carry + b.bank
            self.deaths[(b.tier, cause)] += 1
            self.bots.remove(b)
        rec["deaths"] = len(dead)
        refill = min(max(0, p.bots - len(self.bots)), be.refill_cap(p.bots, self.cfg))
        for _ in range(refill):
            self._spawn(day)
        rec["refill"] = refill
        rec["pop"] = len(self.bots)
        rec["carry_total"] = sum(b.carry for b in self.bots)
        rec["bank_total"] = sum(b.bank for b in self.bots)
        self.daily.append(dict(rec, day=day))
        return rec

    def _try_breakthrough(self, b: Bot, day: int, rec) -> str | None:
        """尝试突破。返回死因（死了）或 None。"""
        p = self.p
        need = cultivation_needed(b.realm)
        nxt = next_realm(b.realm)
        if b.cultivation < need or not nxt or get_realm_index(nxt) > self.ceiling:
            return None
        player = dict(b.stats, realm=b.realm, cultivation=b.cultivation)
        if b.realm in GATES:
            pill, rate_fn = GATES[b.realm]
            price = p.pill_price[pill]
            if b.carry + b.bank < price:
                self.gate_wait_days += 1
                return None                                           # 买不起丹，继续等
            paid_carry = min(b.carry, price)
            b.carry -= paid_carry
            b.bank -= price - paid_carry
            self.flow["pills"] += price
            rec["pills"] += price
            if b.first_gate_day is None:
                b.first_gate_day = day
            success = random.random() * 100 < min(95, rate_fn(player, use_pill=True))
            outcome = None if success else roll_failure_outcome(b.realm)
        else:
            success, outcome = roll_breakthrough(b.realm, b.stats["physique"], b.stats["bone"], b.cultivation)
        if success:
            overflow = max(0, b.cultivation - need)
            new_max = lifespan_max_for_realm(nxt)
            b.lifespan += max(0, new_max - b.lifespan_max)
            b.lifespan_max, b.realm, b.cultivation = new_max, nxt, overflow
            rec["breakthroughs"] += 1
            return None
        b.cultivation, b.lifespan, _ = apply_failure(b.cultivation, b.lifespan, outcome)
        rec["bt_failures"] += 1
        return "突破失败而死" if b.lifespan <= 0 else None

    def run(self) -> "Sim":
        for day in range(1, self.p.days + 1):
            self.step(day)
        return self

    # ---- 守恒校验 -----------------------------------------------------------
    def ledger_gap(self) -> float:
        """账目差额，应当 ≈ 0：
        新钱（收入 + 出生自带） = 现存 + 开销 + 丹药 + 被劫 + 死者遗产消失。"""
        issued = self.flow["income"] + self.flow["endowment"]
        sinks = (self.flow["upkeep"] + self.flow["pills"] + self.flow["robbed"] + self.flow["estate_lost"]
                 + self.flow["kill_reward"])
        return issued - (self.money_in_bots() + sinks)


# ---- 战力对比 ---------------------------------------------------------------

def human_profile(realm: str, diligent: bool) -> dict:
    """典型真人：用心的 = 属性 9、三件稀有装备；普通的 = 属性 6、三件精良装备。"""
    stat = 9 if diligent else 6
    quality = "稀有" if diligent else "精良"
    tier = max(0, get_realm_index(realm) // 10)
    gear = [generate_equipment(tier=tier, quality=quality, slot=s) for s in ("武器", "防具", "饰品")]
    p = dict(comprehension=stat, physique=stat, fortune=stat, bone=stat, soul=stat, realm=realm, techniques="[]",
             active_buffs="{}")
    return p, gear


def bot_profile(realm: str, tier: str) -> dict:
    lo, hi = bot_world.tier_specs()[tier]["stats"]
    s = round((lo + hi) / 2)
    return dict(comprehension=s, physique=s, fortune=s, bone=s, soul=s, realm=realm, techniques="[]", active_buffs="{}")


def power_table(realms=("炼气期5层", "筑基期1层", "筑基期10层", "结丹期初期"), samples=2000) -> list[dict]:
    rows = []
    for realm in realms:
        for diligent in (False, True):
            human, gear = human_profile(realm, diligent)
            hp = asyncio.run(calc_power(human, equipped=gear))
            for tier in bot_world.tier_specs():
                bp = asyncio.run(calc_power(bot_profile(realm, tier), equipped=[])) * (1 + CFG["combat"]["power_bonus"][tier])
                wins = sum(hp * random.uniform(0.85, 1.15) > bp * random.uniform(0.85, 1.15) for _ in range(samples))
                rows.append({"realm": realm, "human": "用心" if diligent else "普通", "tier": tier,
                             "ratio": hp / bp, "win": wins / samples})
    return rows


# ---- 报告 -------------------------------------------------------------------

def _major_of(b: Bot) -> str:
    return major_realm(b.realm) or "?"


def report(sim: Sim, power: list[dict] | None = None) -> str:
    p, out = sim.p, []
    w = out.append
    w(f"# 机器人经济离线模拟　{p.bots} 个 × {p.days} 天（种子 {p.seed}）\n")
    w("## 参数")
    w(f"- 日收入基数 {p.income}，全服上限 {(p.cap_stones or CFG["daily_cap_per_bot"] * p.bots):,.0f}/天；成长速度 {p.speed}")
    w(f"- 最高真人大境 {p.human_top}（天骄天花板）；补员每天 ≤{be.refill_cap(p.bots, p.config())} 个（目标的 {p.refill_rate:.0%}，至少 {CFG["refill_min_per_day"]}）；劫财 {p.robbers} 人 × {p.robs_each} 次/天，"
      f"拿随身 {p.rob_share:.0%}（≤{p.rob_cap}）")
    w(f"- ⚠ 丹药价格（估计）{p.pill_price}；⚠ 材料折扣 ×{p.material_discount}，只统计打工掉落\n")

    days = sim.daily
    checkpoints = sorted({d for d in (7, 30, 60, 90, 120, 180, p.days) if d <= p.days})
    w("## 逐阶段（每日均值取该日前后 7 天窗口）")
    w("| 天 | 人口 | 发出新钱/天 | 想发(未封顶) | 开销/天 | 丹药/天 | 被劫/天 | 随身总额 | 钱庄总额 | 材料价值/天 |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for c in checkpoints:
        win = [d for d in days if abs(d["day"] - c) <= 3] or [days[c - 1]]
        avg = lambda k: statistics.mean(d[k] for d in win)           # noqa: E731
        w(f"| {c} | {days[c-1]['pop']:.0f} | {avg('income_paid'):,.0f} | {avg('income_wanted'):,.0f} | {avg('upkeep'):,.0f} | "
          f"{avg('pills'):,.0f} | {avg('robbed'):,.0f} | {days[c-1]['carry_total']:,.0f} | {days[c-1]['bank_total']:,.0f} | "
          f"{avg('mat_value'):,.0f} |")

    f = sim.flow
    w("\n## 全程账目（灵石）")
    issued = f["income"] + f["endowment"]
    w(f"- 新钱合计 **{issued:,.0f}**（日收入 {f['income']:,.0f} + 出生自带 {f['endowment']:,.0f}）")
    for label, key in (("日常开销（消失）", "upkeep"), ("买丹（消失）", "pills"), ("被真人劫走（流回真人）", "robbed"),
                       ("被击杀时给击杀者（流回真人）", "kill_reward"), ("死者遗产（消失）", "estate_lost")):
        w(f"- {label}：{f[key]:,.0f}（{f[key] / issued:.0%}）")
    w(f"- 仍在机器人手里：{sim.money_in_bots():,.0f}（随身 {sum(b.carry for b in sim.bots):,.0f} / 钱庄 {sum(b.bank for b in sim.bots):,.0f}）")
    w(f"- 账目差额 {sim.ledger_gap():.4f}（应为 0）")
    steady = days[-30:] if len(days) >= 30 else days
    net = statistics.mean(d["income_paid"] - d["upkeep"] - d["pills"] for d in steady)
    w(f"- 最后 30 天：平均每天发出 {statistics.mean(d['income_paid'] for d in steady):,.0f}，"
      f"消耗回收 {statistics.mean(d['upkeep'] + d['pills'] for d in steady):,.0f}，"
      f"流回真人 {statistics.mean(d['robbed'] for d in steady):,.0f}，**净增加机器人手里的钱 {net:,.0f}/天**（几乎全进钱庄囤积）")

    per_robber = f["robbed"] / max(1, p.days * p.robbers)
    w(f"- **每个劫匪每天从机器人身上拿到约 {per_robber:,.0f} 灵石**（{p.robs_each} 次/天），"
      f"对比：一个真人每天 3 次低阶打工 ≈ 200~250；劫机器人相当于另一份{'**超过**' if per_robber > 225 else '约占'}打工的收入")

    w("\n## 材料（打工掉落，已打折）")
    mv = [d["mat_value"] for d in days]
    mc = [d["mat_count"] for d in days]
    w(f"- 每天 {statistics.mean(mc):,.0f} 件，价值均值 {statistics.mean(mv):,.0f}、最高 {max(mv):,.0f}（建议全服每日材料价值上限 ≈ P95 = "
      f"{sorted(mv)[int(len(mv) * 0.95) - 1]:,.0f}）")

    w("\n## 终局人口（第 %d 天）" % p.days)
    by_tier = defaultdict(Counter)
    for b in sim.bots:
        by_tier[b.tier][_major_of(b)] += 1
    for tier in ("炮灰", "正常", "天骄"):
        dist = "　".join(f"{m} {by_tier[tier][m]}" for m in MAJORS if by_tier[tier][m])
        w(f"- {tier}（{sum(by_tier[tier].values())} 人）：{dist or '—'}")
    top = max(sim.bots, key=lambda b: get_realm_index(b.realm))
    w(f"- 最高境界：{top.realm}（{top.tier}）")
    over = int(sim.flow["spawn_above_ceiling"])
    if over:
        w(f"- ⚠ 出生就超过天花板（{p.human_top}）的机器人：{over} 个 —— 档位表（bot_world.tier_specs()）没看天花板，生成 / 补员时需要夹到天花板以内")
    w("\n## 死亡与更替")
    tot_dead = sum(sim.deaths.values())
    w(f"- 共 {tot_dead} 人死亡，平均每天 {tot_dead / p.days:.1f} 人（占目标 {tot_dead / p.days / p.bots:.1%}/天）")
    for (tier, cause), n in sorted(sim.deaths.items()):
        w(f"  - {tier} · {cause}：{n}")
    w(f"- 因买不起丹而卡关的机器人 · 天：{sim.gate_wait_days}")
    w(f"- 补员总数 {sum(d['refill'] for d in days):.0f}；补员日均 {statistics.mean(d['refill'] for d in days):.1f}（上限 {be.refill_cap(p.bots, p.config())}/天）")

    if power:
        w("\n## 同境界战力对比（真人 ÷ 机器人，设计目标：用心真人 vs 正常机器人 ≥ 1.35）")
        w("| 境界 | 真人 | 机器人档位 | 战力比 | 真人胜率 | 机器人还能加多少虚拟加成 |")
        w("|---|---|---|---|---|---|")
        for r in power:
            mark = " ✅" if r["human"] == "用心" and r["tier"] == "正常" and r["ratio"] >= 1.35 else (
                " ❌" if r["human"] == "用心" and r["tier"] == "正常" else "")
            room = f"+{(r['ratio'] / 1.35 - 1):.0%}" if mark.strip() else ""
            w(f"| {r['realm']} | {r['human']} | {r['tier']} | {r['ratio']:.2f}{mark} | {r['win']:.0%} | {room} |")
        w(f"（真人：用心 = 属性 9 + 三件稀有装备；普通 = 属性 6 + 三件精良装备；机器人：该档属性中值，另有按档位的虚拟加成 {CFG['combat']['power_bonus']}）")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    d = Params()
    ap.add_argument("--bots", type=int, default=d.bots)
    ap.add_argument("--days", type=int, default=d.days)
    ap.add_argument("--seed", type=int, default=d.seed)
    ap.add_argument("--cap-stones", type=float, default=d.cap_stones, help="全服每日产出上限；0 = 按配置的每机器人上限 × 人口")
    ap.add_argument("--human-top", default=d.human_top, help="最高真人所在大境；写「无」表示不设天花板")
    ap.add_argument("--robbers", type=int, default=d.robbers)
    ap.add_argument("--robs-each", type=int, default=d.robs_each)
    ap.add_argument("--hunters", type=int, default=d.hunters, help="每天击杀机器人的真人数")
    ap.add_argument("--kills-each", type=int, default=d.kills_each)
    ap.add_argument("--rob-share", type=float, default=d.rob_share)
    ap.add_argument("--rob-cap", type=int, default=d.rob_cap)
    ap.add_argument("--refill-rate", type=float, default=d.refill_rate)
    ap.add_argument("--material-discount", type=float, default=d.material_discount)
    ap.add_argument("--pill-price", type=float, nargs=3, metavar=("筑基丹", "凝丹丹", "化婴丹"))
    ap.add_argument("--no-power", action="store_true", help="不跑战力对比")
    ap.add_argument("--json", help="把逐日数据另存为 JSON")
    a = ap.parse_args(argv)
    p = Params(bots=a.bots, days=a.days, seed=a.seed, cap_stones=a.cap_stones, human_top=a.human_top,
               robbers=a.robbers, robs_each=a.robs_each, material_discount=a.material_discount,
               rob_share=a.rob_share, rob_cap=a.rob_cap, refill_rate=a.refill_rate,
               hunters=a.hunters, kills_each=a.kills_each)
    if a.pill_price:
        p.pill_price = dict(zip(("筑基丹", "凝丹丹", "化婴丹"), a.pill_price))
    sim = Sim(p).run()
    power = None if a.no_power else power_table()
    print(report(sim, power))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump({"params": p.__dict__, "daily": sim.daily, "flow": dict(sim.flow)}, fh, ensure_ascii=False, indent=1)
    return sim


if __name__ == "__main__":
    main()
