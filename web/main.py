import json
import os
import sqlite3
import sys
import time
from datetime import datetime

try:
    from version import VERSION as _APP_VERSION
except ImportError:
    _APP_VERSION = "dev"

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

DB_PATH = os.getenv("DB_PATH", "game.db")

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


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    """Serve the service worker from the root path so it can control the entire site."""
    return FileResponse(
        os.path.join(_static_dir, "sw.js"),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


templates = Jinja2Templates(directory=_templates_dir)
# Disable cache to fix compatibility issue with Jinja2 3.1+ and Python 3.14
templates.env.cache = None
templates.env.auto_reload = True


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
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
        "index.html",
        {
            "request": request,
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
async def players(
    request: Request,
    q: str = "",
    city: str = "",
    realm: str = "",
    sort: str = "cultivation",
):
    allowed_sorts = {
        "cultivation",
        "lifespan",
        "spirit_stones",
        "realm",
        "name",
        "last_active",
    }
    if sort not in allowed_sorts:
        sort = "cultivation"
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
        sql = f"SELECT * FROM players WHERE {' AND '.join(where)} ORDER BY {sort} DESC"
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        cities = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT current_city FROM players WHERE is_dead=0 ORDER BY current_city"
            ).fetchall()
        ]
    return templates.TemplateResponse(
        "players.html",
        {
            "request": request,
            "players": rows,
            "q": q,
            "city": city,
            "realm": realm,
            "sort": sort,
            "cities": cities,
        },
    )


@app.get("/players/{discord_id}", response_class=HTMLResponse)
async def player_detail(request: Request, discord_id: str):
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
        "player_detail.html",
        {
            "request": request,
            "player": player,
            "inventory": [dict(i) for i in inventory],
            "equipment": equipment,
            "residences": [r["city"] for r in residences],
            "quest": json.loads(quests_raw) if quests_raw else None,
        },
    )


@app.get("/events", response_class=HTMLResponse)
async def events(request: Request, page: int = 1):
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
        "events.html",
        {
            "request": request,
            "events": paged,
            "page": page,
            "total_pages": total_pages,
            "total": total,
        },
    )


@app.get("/items", response_class=HTMLResponse)
async def items_page(
    request: Request, type_filter: str = "", rarity: str = "", q: str = ""
):
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from utils.items import ITEMS

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
        "items.html",
        {
            "request": request,
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
async def stats(request: Request, sort: str = "cultivation", order: str = "desc"):
    allowed = {
        "cultivation",
        "lifespan",
        "spirit_stones",
        "reputation",
        "comprehension",
        "physique",
        "fortune",
        "bone",
        "soul",
        "name",
        "realm",
        "rebirth_count",
        "stat_total",
    }
    if sort not in allowed:
        sort = "cultivation"
    direction = "DESC" if order != "asc" else "ASC"
    with get_conn() as conn:
        if sort == "stat_total":
            rows = conn.execute(
                "SELECT *, (comprehension+physique+fortune+bone+soul) as stat_total "
                f"FROM players WHERE is_dead=0 ORDER BY stat_total {direction}"
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT *, (comprehension+physique+fortune+bone+soul) as stat_total "
                f"FROM players WHERE is_dead=0 ORDER BY {sort} {direction}"
            ).fetchall()
    return templates.TemplateResponse(
        "stats.html",
        {
            "request": request,
            "players": [dict(r) for r in rows],
            "sort": sort,
            "order": order,
        },
    )


@app.get("/techniques", response_class=HTMLResponse)
async def techniques_page(
    request: Request, type_filter: str = "", grade: str = "", q: str = ""
):
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from utils.sects import (
        PCT_STATS,
        SECTS,
        STAGE_PCT_MULTIPLIER,
        STAGE_STAT_MULTIPLIER,
        TECHNIQUE_STAGES,
        TECHNIQUES,
    )

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
        "techniques.html",
        {
            "request": request,
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
async def equipment_preview(
    request: Request, slot: str = "", quality: str = "", tier: int = 0, count: int = 1
):
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from utils.equipment import (
        QUALITY_ORDER,
        SLOTS,
        STAT_NAMES,
        TIER_NAMES,
        generate_equipment,
    )

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
        "equipment_preview.html",
        {
            "request": request,
            "results": results,
            "slots": SLOTS,
            "qualities": QUALITY_ORDER,
            "tiers": tiers,
            "slot": slot,
            "quality": quality,
            "tier": tier,
            "count": count,
            "stat_names": STAT_NAMES,
        },
    )


@app.get("/dead", response_class=HTMLResponse)
async def dead_players(request: Request):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM players WHERE is_dead=1 ORDER BY last_active DESC"
        ).fetchall()
    return templates.TemplateResponse(
        "dead.html",
        {
            "request": request,
            "players": [dict(r) for r in rows],
        },
    )


@app.get("/world", response_class=HTMLResponse)
async def world_page(request: Request):
    import os
    import sys

    _utils = (
        os.path.normpath(os.path.join(_base, ".."))
        if _base != os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    if _utils not in sys.path:
        sys.path.insert(0, _utils)
    from utils.sects import SECTS
    from utils.world import CITIES, SPECIAL_REGIONS

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
        "world.html",
        {
            "request": request,
            "cities_by_region": cities_by_region,
            "regions_order": regions_order,
            "special_regions": SPECIAL_REGIONS,
            "sects_by_alignment": sects_by_alignment,
            "alignment_order": alignment_order,
            "city_counts": city_counts,
            "sect_counts": sect_counts,
        },
    )
