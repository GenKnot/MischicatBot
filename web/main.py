import base64
import binascii
import json
import logging
import os
import secrets
import sys
import time
from datetime import datetime

try:
    from version import VERSION as _APP_VERSION
except ImportError:
    _APP_VERSION = "dev"

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               PlainTextResponse, RedirectResponse, Response)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from utils.config import DB_PATH
from utils.db import get_conn
from utils.items import ITEMS
from utils.sects import (
    PCT_STATS,
    SECTS,
    STAGE_PCT_MULTIPLIER,
    STAGE_STAT_MULTIPLIER,
    TECHNIQUE_STAGES,
    TECHNIQUES,
)
from utils.equipment import (
    QUALITY_ORDER,
    SLOTS,
    STAT_NAMES as EQ_STAT_NAMES,
    TIER_NAMES,
    generate_equipment,
)
from utils.realms import REALM_GROUPS, lifespan_max_for_realm
from utils.world import CITIES, SPECIAL_REGIONS

# PyInstaller onefile: 资源在 sys._MEIPASS；main.py 会设置 MISCHICAT_BASE 供子进程
_base = os.environ.get("MISCHICAT_BASE")
if not _base:
    try:
        _base = sys._MEIPASS
    except AttributeError:
        _base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_static_dir = os.path.normpath(os.path.join(_base, "web", "static"))
_templates_dir = os.path.normpath(os.path.join(_base, "web", "templates"))

app = FastAPI(title="Mischicat Admin")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

log = logging.getLogger("mischicat.web")

# 面板会显示每个玩家的 discord_id 和作息，默认要挡住。
# 设了 WEB_PASS 强制鉴权；没设时本地放行、k8s 里直接停用（生产不能裸奔）。
WEB_USER = os.getenv("WEB_USER", "admin")
WEB_PASS = os.getenv("WEB_PASS") or ""
IN_KUBERNETES = os.getenv("KUBERNETES_SERVICE_HOST") is not None

# 探针必须在未鉴权状态下可访问，否则 k8s 会一直判定 pod 不健康
_OPEN_PATHS = frozenset({"/health", "/ready", "/robots.txt", "/sw.js"})

if not WEB_PASS:
    if IN_KUBERNETES:
        log.error("未设置 WEB_PASS，Web 面板已停用（生产环境不允许无鉴权对外暴露）")
    else:
        log.warning("未设置 WEB_PASS，Web 面板当前无鉴权；若要对公网暴露请先设置")


def _basic_auth_ok(header: str | None) -> bool:
    """校验 Authorization: Basic 头。用固定时间比较，避免时序侧信道。"""
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, IndexError):
        return False
    user, sep, password = decoded.partition(":")
    if not sep:
        return False
    # 两个比较都要跑完，不能短路，否则用户名是否正确会从耗时上泄露
    user_ok = secrets.compare_digest(user, WEB_USER)
    pass_ok = secrets.compare_digest(password, WEB_PASS)
    return user_ok and pass_ok


@app.middleware("http")
async def access_control(request: Request, call_next):
    path = request.url.path
    if path in _OPEN_PATHS or path.startswith("/static/"):
        return await call_next(request)

    if not WEB_PASS:
        if IN_KUBERNETES:
            return PlainTextResponse(
                "Web 面板未配置 WEB_PASS，已停用。", status_code=503)
    elif not _basic_auth_ok(request.headers.get("authorization")):
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Mischicat"'},
        )

    response = await call_next(request)
    # 即便鉴权被关掉，也不希望玩家数据进搜索引擎索引
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@app.get("/robots.txt", include_in_schema=False)
async def robots():
    """明确拒绝所有爬虫。面板每一页都从导航链得到，否则会被整站抓取。"""
    return PlainTextResponse("User-agent: *\nDisallow: /\n")


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    """Serve the service worker from the root path so it can control the entire site."""
    return FileResponse(
        os.path.join(_static_dir, "sw.js"),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


# 模板缓存开着。曾经因为 Jinja2 3.1+ 配 Python 3.14 报错而被禁用过，
# 现在 3.12 和 3.14 上都验证正常，上游早就修了。
templates = Jinja2Templates(directory=_templates_dir)


# Discord bot 的运行时引用由 main.py 注入。web 与 bot 跑在同一进程的
# 同一个事件循环里（见 main.py 的 asyncio.gather），因此这里能直接读到状态。
_bot = None


def set_bot(bot) -> None:
    """由 main.py 在 bot 实例创建后调用，供 /ready 探针判断真实可用性。"""
    global _bot
    _bot = bot


@app.get("/health")
async def health():
    """K8s liveness probe：进程还能提供服务就算活着。

    刻意**不**检查 Discord 连接 —— discord.py 会自动重连，网络抖动期间
    重启 pod 只会让情况更糟。真实可用性交给 /ready。
    """
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    """K8s readiness probe：Discord 已连接时才算可对外服务。

    只配 liveness 是不够的：bot 掉线而 uvicorn 仍在响应时，
    /health 照样返回 200，pod 永远不会被替换。
    """
    connected = _bot is not None and _bot.is_ready() and not _bot.is_closed()
    if not connected:
        return JSONResponse({"status": "starting", "discord": False}, status_code=503)
    return {"status": "ok", "discord": True}


# 排序参数 → 列名。值是代码里的常量，用户传什么都只能命中这张表的键。
PLAYER_SORT_COLUMNS = {
    name: name for name in
    ("cultivation", "lifespan", "spirit_stones", "realm", "name", "last_active")
}

STATS_SORT_COLUMNS = {
    name: name for name in
    ("cultivation", "lifespan", "spirit_stones", "reputation", "comprehension",
     "physique", "fortune", "bone", "soul", "name", "realm", "rebirth_count")
}
STATS_SORT_COLUMNS["stat_total"] = "stat_total"   # SELECT 里的计算列


def ts(val):
    if not val:
        return "—"
    try:
        return datetime.fromtimestamp(float(val)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "—"


def duration_left(until):
    if not until:
        return None
    secs = float(until) - time.time()
    if secs <= 0:
        return "已结束"
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    return f"{h}h {m}m"


templates.env.globals["ts"] = ts
templates.env.globals["duration_left"] = duration_left
templates.env.globals["now"] = time.time
templates.env.globals["app_version"] = _APP_VERSION


# 下面这些页面路由刻意写成同步 def 而不是 async def。
#
# bot 和 uvicorn 共用一个事件循环（见 main.py 的 asyncio.gather），路由要是
# async 的，函数体就跑在事件循环上 —— 5000 名玩家时 /players 实测 243ms，
# 这段时间 Discord 那边完全无响应。而这里面 SQL 只占 108ms，剩下的是模板渲染
# 和行转换，改成异步查询也搬不走。
#
# FastAPI 对同步 def 会自动丢进线程池，整个函数体（含模板渲染）都不占事件循环。
# 代价是每个请求占一个线程，对这种只读面板完全够用。


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    with get_conn() as conn:
        now = time.time()
        total = conn.execute("SELECT COUNT(*) FROM players WHERE is_dead=0").fetchone()[
            0
        ]
        dead = conn.execute("SELECT COUNT(*) FROM players WHERE is_dead=1").fetchone()[
            0
        ]
        cultivating = conn.execute(
            "SELECT COUNT(*) FROM players WHERE cultivating_until > ? AND is_dead=0",
            (now,),
        ).fetchone()[0]
        on_quest = conn.execute(
            "SELECT COUNT(*) FROM players WHERE active_quest IS NOT NULL AND quest_due > ? AND is_dead=0",
            (now,),
        ).fetchone()[0]
        gathering = conn.execute(
            "SELECT COUNT(*) FROM players WHERE gathering_until > ? AND is_dead=0",
            (now,),
        ).fetchone()[0]
        events = conn.execute(
            "SELECT * FROM public_events ORDER BY started_at DESC LIMIT 5"
        ).fetchall()
        events = [dict(e) for e in events]
        realm_dist = conn.execute(
            "SELECT realm, COUNT(*) as cnt FROM players WHERE is_dead=0 GROUP BY realm ORDER BY cnt DESC"
        ).fetchall()
        realm_dist = [dict(r) for r in realm_dist]
        recent = conn.execute(
            "SELECT * FROM players WHERE is_dead=0 ORDER BY last_active DESC LIMIT 8"
        ).fetchall()
        recent = [dict(r) for r in recent]
        top_stones = conn.execute(
            "SELECT name, spirit_stones, realm, discord_id FROM players WHERE is_dead=0 ORDER BY spirit_stones DESC LIMIT 5"
        ).fetchall()
        top_stones = [dict(r) for r in top_stones]
        top_stats = conn.execute(
            "SELECT name, realm, discord_id, (comprehension+physique+fortune+bone+soul) as total "
            "FROM players WHERE is_dead=0 ORDER BY total DESC LIMIT 5"
        ).fetchall()
        top_stats = [dict(r) for r in top_stats]
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "total": total,
            "dead": dead,
            "cultivating": cultivating,
            "on_quest": on_quest,
            "gathering": gathering,
            "events": events,
            "realm_dist": realm_dist,
            "recent": recent,
            "top_stones": top_stones,
            "top_stats": top_stats,
        },
    )


@app.get("/players", response_class=HTMLResponse)
def players(
    request: Request,
    q: str = "",
    city: str = "",
    realm: str = "",
    sort: str = "cultivation",
):
    # 用参数查表拿列名，进 SQL 的永远是这里的常量，不是用户传来的字符串。
    # 原先是校验完直接把 sort 拼进去，校验和拼接隔着十几行，改动时容易漏。
    sort_column = PLAYER_SORT_COLUMNS.get(sort)
    if sort_column is None:
        sort, sort_column = "cultivation", PLAYER_SORT_COLUMNS["cultivation"]
    with get_conn() as conn:
        where = ["is_dead = 0"]
        params = []
        if q:
            where.append("(name LIKE ? OR discord_id LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        if city:
            where.append("current_city = ?")
            params.append(city)
        if realm:
            where.append("realm LIKE ?")
            params.append(f"%{realm}%")
        sql = f"SELECT * FROM players WHERE {' AND '.join(where)} ORDER BY {sort_column} DESC"
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        cities = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT current_city FROM players WHERE is_dead=0 ORDER BY current_city"
            ).fetchall()
        ]
    return templates.TemplateResponse(
        request=request,
        name="players.html",
        context={
            "players": rows,
            "q": q,
            "city": city,
            "realm": realm,
            "sort": sort,
            "cities": cities,
        },
    )


@app.get("/players/{discord_id}", response_class=HTMLResponse)
def player_detail(request: Request, discord_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM players WHERE discord_id = ?", (discord_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "玩家不存在")
        player = dict(row)
        inventory = conn.execute(
            "SELECT item_id, quantity FROM inventory WHERE discord_id = ? ORDER BY item_id",
            (discord_id,),
        ).fetchall()
        equipment = conn.execute(
            "SELECT * FROM equipment WHERE discord_id = ? ORDER BY equipped DESC, tier DESC",
            (discord_id,),
        ).fetchall()
        residences = conn.execute(
            "SELECT city FROM residences WHERE discord_id = ?", (discord_id,)
        ).fetchall()
        quests_raw = player.get("active_quest")
    player["techniques"] = json.loads(player.get("techniques") or "[]")
    equipment = [dict(e) for e in equipment]
    for e in equipment:
        e["stats"] = json.loads(e.get("stats") or "{}")
    return templates.TemplateResponse(
        request=request,
        name="player_detail.html",
        context={
            "player": player,
            "inventory": [dict(i) for i in inventory],
            "equipment": equipment,
            "residences": [r["city"] for r in residences],
            "quest": json.loads(quests_raw) if quests_raw else None,
        },
    )


@app.get("/events", response_class=HTMLResponse)
def events(request: Request, page: int = 1):
    PAGE_SIZE = 10
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM public_events ORDER BY started_at DESC"
        ).fetchall()
        events = []
        for r in rows:
            e = dict(r)
            e["data"] = json.loads(e.get("data") or "{}")
            e["event_source"] = "spirit_rain"
            participants_raw = conn.execute(
                "SELECT ep.discord_id, MAX(ep.contribution) as contribution, "
                "GROUP_CONCAT(ep.activity, ',') as activities, p.name "
                "FROM public_event_participants ep "
                "LEFT JOIN players p ON ep.discord_id = p.discord_id "
                "WHERE ep.event_id = ? "
                "GROUP BY ep.discord_id ORDER BY contribution DESC",
                (e["event_id"],),
            ).fetchall()
            merged = []
            for p in participants_raw:
                p = dict(p)
                acts = set(a for a in (p["activities"] or "").split(",") if a)
                p["activities"] = list(acts)
                merged.append(p)
            e["participants"] = merged
            events.append(e)

        auctions = conn.execute(
            "SELECT * FROM wanbao_auctions ORDER BY started_at DESC"
        ).fetchall()
        for a in auctions:
            a = dict(a)
            lots = conn.execute(
                "SELECT wl.lot_id, wl.item_name, wl.start_price, wl.current_bid, "
                "wl.bidder_id, wl.status, p.name as bidder_name "
                "FROM wanbao_lots wl "
                "LEFT JOIN players p ON wl.bidder_id = p.discord_id "
                "WHERE wl.auction_id = ? ORDER BY wl.current_bid DESC",
                (a["auction_id"],),
            ).fetchall()
            a["lots"] = [dict(l) for l in lots]
            a["event_source"] = "wanbao"
            a["title"] = "万宝楼大型拍卖会"
            a["event_type"] = "wanbao_auction"
            a["started_at"] = a.get("started_at")
            a["ends_at"] = a.get("ends_at")
            events.append(a)

        events.sort(key=lambda e: float(e.get("started_at") or 0), reverse=True)

    total = len(events)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    paged = events[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]

    return templates.TemplateResponse(
        request=request,
        name="events.html",
        context={
            "events": paged,
            "page": page,
            "total_pages": total_pages,
            "total": total,
        },
    )


@app.get("/items", response_class=HTMLResponse)
def items_page(
    request: Request, type_filter: str = "", rarity: str = "", q: str = ""
):
    TYPE_LABEL = {
        "pill": "丹药",
        "ore": "矿石",
        "wood": "灵木",
        "fish": "灵鱼",
        "herb": "草药",
        "tool": "工具",
    }
    RARITY_ORDER = {"普通": 0, "稀有": 1, "珍贵": 2, "绝世": 3}
    all_items = list(ITEMS.values())
    if q:
        all_items = [i for i in all_items if q in i["name"] or q in i.get("desc", "")]
    if type_filter:
        all_items = [i for i in all_items if i.get("type") == type_filter]
    if rarity:
        all_items = [i for i in all_items if i.get("rarity") == rarity]
    all_items.sort(
        key=lambda i: (
            RARITY_ORDER.get(i.get("rarity", "普通"), 0),
            i.get("sell_price", 0),
        ),
        reverse=True,
    )
    by_type = {}
    for item in all_items:
        t = TYPE_LABEL.get(item.get("type", ""), item.get("type", "其他"))
        by_type.setdefault(t, []).append(item)
    types = list(TYPE_LABEL.values())
    rarities = ["普通", "稀有", "珍贵", "绝世"]
    return templates.TemplateResponse(
        request=request,
        name="items.html",
        context={
            "by_type": by_type,
            "type_map": TYPE_LABEL,
            "rarities": rarities,
            "type_filter": type_filter,
            "rarity": rarity,
            "q": q,
            "total": len(all_items),
        },
    )


@app.get("/stats", response_class=HTMLResponse)
def stats(request: Request, sort: str = "cultivation", order: str = "desc"):
    sort_column = STATS_SORT_COLUMNS.get(sort)
    if sort_column is None:
        sort, sort_column = "cultivation", STATS_SORT_COLUMNS["cultivation"]
    direction = "DESC" if order != "asc" else "ASC"
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT *, (comprehension+physique+fortune+bone+soul) as stat_total "
            f"FROM players WHERE is_dead=0 ORDER BY {sort_column} {direction}"
        ).fetchall()
    return templates.TemplateResponse(
        request=request,
        name="stats.html",
        context={
            "players": [dict(r) for r in rows],
            "sort": sort,
            "order": order,
        },
    )


@app.get("/techniques", response_class=HTMLResponse)
def techniques_page(
    request: Request, type_filter: str = "", grade: str = "", q: str = ""
):
    tech_to_sect = {}
    for sect_name, sect_info in SECTS.items():
        for t in sect_info["techniques"]:
            tech_to_sect[t] = sect_name

    GRADE_ORDER = {
        "黄级下品": 0,
        "黄级中品": 1,
        "黄级上品": 2,
        "玄级下品": 3,
        "玄级中品": 4,
        "玄级上品": 5,
        "地级下品": 6,
        "地级中品": 7,
        "地级上品": 8,
        "天级下品": 9,
        "天级中品": 10,
        "天级上品": 11,
    }
    STAT_NAMES = {
        "physique": "体魄",
        "bone": "根骨",
        "soul": "神识",
        "comprehension": "悟性",
        "fortune": "机缘",
        "cultivation_speed": "修炼速度",
        "escape_rate": "逃跑率",
        "lifespan_bonus": "寿元上限",
    }

    all_techs = []
    for name, info in TECHNIQUES.items():
        if q and q not in name and q not in info.get("desc", ""):
            continue
        if type_filter and info.get("type") != type_filter:
            continue
        if grade and info.get("grade") != grade:
            continue

        stages = []
        for stage in TECHNIQUE_STAGES:
            bonuses = {}
            for stat, val in info.get("stat_bonus", {}).items():
                if stat in PCT_STATS:
                    mult = STAGE_PCT_MULTIPLIER.get(stage, 1)
                    bonuses[STAT_NAMES.get(stat, stat)] = (
                        f"+{val * mult:.0%}"
                        if stat == "cultivation_speed"
                        else f"+{val * mult:.1f}"
                    )
                else:
                    mult = STAGE_STAT_MULTIPLIER.get(stage, 1)
                    bonuses[STAT_NAMES.get(stat, stat)] = f"+{val * mult:.0f}"
            stages.append({"stage": stage, "bonuses": bonuses})

        all_techs.append(
            {
                "name": name,
                "type": info.get("type", ""),
                "grade": info.get("grade", ""),
                "desc": info.get("desc", ""),
                "stat_bonus": info.get("stat_bonus", {}),
                "stages": stages,
                "grade_order": GRADE_ORDER.get(info.get("grade", ""), 99),
                "sect": tech_to_sect.get(name, ""),
            }
        )

    all_techs.sort(key=lambda t: (t["grade_order"], t["name"]))

    by_grade = {}
    for t in all_techs:
        by_grade.setdefault(t["grade"], []).append(t)

    grade_order_keys = sorted(by_grade.keys(), key=lambda g: GRADE_ORDER.get(g, 99))
    ordered_by_grade = {g: by_grade[g] for g in grade_order_keys}

    types = ["修炼", "攻击", "防御", "辅助", "特殊"]
    grades = list(GRADE_ORDER.keys())

    return templates.TemplateResponse(
        request=request,
        name="techniques.html",
        context={
            "by_grade": ordered_by_grade,
            "types": types,
            "grades": grades,
            "type_filter": type_filter,
            "grade": grade,
            "q": q,
            "total": len(all_techs),
            "stat_names": STAT_NAMES,
            "stages": TECHNIQUE_STAGES,
        },
    )


@app.get("/equipment-preview", response_class=HTMLResponse)
def equipment_preview(
    request: Request, slot: str = "", quality: str = "", tier: int = 0, count: int = 1
):
    QUALITY_COLORS = {
        "普通": "#888888",
        "精良": "#2ecc71",
        "稀有": "#3498db",
        "史诗": "#9b59b6",
        "传说": "#f1c40f",
    }
    QUALITY_BADGE_BG = {
        "普通": "#555",
        "精良": "#27ae60",
        "稀有": "#2980b9",
        "史诗": "#8e44ad",
        "传说": "#d4ac0d",
    }

    count = max(1, min(count, 10))
    results = []
    rolled = (
        "count" in request.query_params
        or "slot" in request.query_params
        or "quality" in request.query_params
        or "tier" in request.query_params
    )
    if rolled:
        for _ in range(count):
            eq = generate_equipment(
                tier=tier,
                quality=quality if quality else None,
                slot=slot if slot else None,
            )
            eq["color"] = QUALITY_COLORS.get(eq["quality"], "#888")
            eq["badge_bg"] = QUALITY_BADGE_BG.get(eq["quality"], "#555")
            eq["tier_label"] = TIER_NAMES[min(eq["tier"], len(TIER_NAMES) - 1)]
            results.append(eq)

    tiers = [{"val": i, "label": TIER_NAMES[i]} for i in range(len(TIER_NAMES))]

    return templates.TemplateResponse(
        request=request,
        name="equipment_preview.html",
        context={
            "results": results,
            "slots": SLOTS,
            "qualities": QUALITY_ORDER,
            "tiers": tiers,
            "slot": slot,
            "quality": quality,
            "tier": tier,
            "count": count,
            "stat_names": EQ_STAT_NAMES,
        },
    )


@app.get("/dead", response_class=HTMLResponse)
def dead_players(request: Request):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM players WHERE is_dead=1 ORDER BY last_active DESC"
        ).fetchall()
    return templates.TemplateResponse(
        request=request,
        name="dead.html",
        context={
            "players": [dict(r) for r in rows],
        },
    )


@app.get("/realms", response_class=HTMLResponse)
def realms_page(request: Request):
    """境界体系：13 个大境逐层展开，并统计各境界在世人数。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT realm, COUNT(*) AS cnt FROM players WHERE is_dead = 0 GROUP BY realm"
        ).fetchall()
        dead_total = conn.execute(
            "SELECT COUNT(*) FROM players WHERE is_dead = 1"
        ).fetchone()[0]
    counts = {r["realm"]: r["cnt"] for r in rows}

    groups = []
    for major, subs in REALM_GROUPS:
        # 键名刻意不叫 items：Jinja2 里 `g.items` 会解析成 dict 的 .items 方法
        # 而不是这个键，模板会静默拿到一个方法对象。
        stages = [
            {
                "name": name,
                "count": counts.get(name, 0),
                "lifespan": lifespan_max_for_realm(name),
            }
            for name in subs
        ]
        groups.append({
            "major": major,
            "stages": stages,
            "total": sum(st["count"] for st in stages),
        })

    living_total = sum(counts.values())
    # 落在体系之外的境界值（历史数据或写错的字面量）单独列出，不要静默吞掉
    known = {name for _m, subs in REALM_GROUPS for name in subs}
    unknown = [{"name": k, "count": v} for k, v in counts.items() if k not in known]

    highest = None
    for group in reversed(groups):
        for item in reversed(group["stages"]):
            if item["count"]:
                highest = item["name"]
                break
        if highest:
            break

    return templates.TemplateResponse(
        request=request,
        name="realms.html",
        context={
            "groups": groups,
            "living_total": living_total,
            "dead_total": dead_total,
            "major_count": len(REALM_GROUPS),
            "realm_count": sum(len(g["stages"]) for g in groups),
            "highest": highest,
            "unknown": unknown,
        },
    )


@app.get("/world", response_class=HTMLResponse)
def world_page(request: Request):
    regions_order = ["中州", "东域", "南域", "西域", "北域"]
    cities_by_region = {}
    for r in regions_order:
        cities_by_region[r] = [c for c in CITIES if c["region"] == r]

    with get_conn() as conn:
        city_counts = {
            row["current_city"]: row["cnt"]
            for row in conn.execute(
                "SELECT current_city, COUNT(*) as cnt FROM players WHERE is_dead=0 GROUP BY current_city"
            ).fetchall()
        }
        sect_counts = {
            row["sect"]: row["cnt"]
            for row in conn.execute(
                "SELECT sect, COUNT(*) as cnt FROM players WHERE is_dead=0 AND sect IS NOT NULL GROUP BY sect"
            ).fetchall()
        }

    alignment_order = ["正道", "邪道", "隐世"]
    sects_by_alignment = {}
    for a in alignment_order:
        sects_by_alignment[a] = [
            {"name": k, **v} for k, v in SECTS.items() if v["alignment"] == a
        ]

    return templates.TemplateResponse(
        request=request,
        name="world.html",
        context={
            "cities_by_region": cities_by_region,
            "regions_order": regions_order,
            "special_regions": SPECIAL_REGIONS,
            "sects_by_alignment": sects_by_alignment,
            "alignment_order": alignment_order,
            "city_counts": city_counts,
            "sect_counts": sect_counts,
        },
    )
