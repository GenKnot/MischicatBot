import json
import os
import sqlite3
import time
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

DB_PATH = os.getenv("DB_PATH", "game.db")

app = FastAPI(title="Mischicat Admin")
app.mount("/static", StaticFiles(directory="web/static"), name="static")
templates = Jinja2Templates(directory="web/templates")


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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM players WHERE is_dead=0").fetchone()[0]
        dead = conn.execute("SELECT COUNT(*) FROM players WHERE is_dead=1").fetchone()[0]
        cultivating = conn.execute(
            "SELECT COUNT(*) FROM players WHERE cultivating_until > ? AND is_dead=0", (time.time(),)
        ).fetchone()[0]
        events = conn.execute(
            "SELECT * FROM public_events ORDER BY started_at DESC LIMIT 5"
        ).fetchall()
        events = [dict(e) for e in events]
    return templates.TemplateResponse("index.html", {
        "request": request,
        "total": total, "dead": dead, "cultivating": cultivating,
        "events": events,
    })


@app.get("/players", response_class=HTMLResponse)
async def players(request: Request, q: str = "", city: str = "", realm: str = "", sort: str = "cultivation"):
    allowed_sorts = {"cultivation", "lifespan", "spirit_stones", "realm", "name", "last_active"}
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
        cities = [r[0] for r in conn.execute("SELECT DISTINCT current_city FROM players WHERE is_dead=0 ORDER BY current_city").fetchall()]
    return templates.TemplateResponse("players.html", {
        "request": request, "players": rows,
        "q": q, "city": city, "realm": realm, "sort": sort,
        "cities": cities,
    })


@app.get("/players/{discord_id}", response_class=HTMLResponse)
async def player_detail(request: Request, discord_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM players WHERE discord_id = ?", (discord_id,)).fetchone()
        if not row:
            raise HTTPException(404, "玩家不存在")
        player = dict(row)
        inventory = conn.execute(
            "SELECT item_id, quantity FROM inventory WHERE discord_id = ? ORDER BY item_id",
            (discord_id,)
        ).fetchall()
        equipment = conn.execute(
            "SELECT * FROM equipment WHERE discord_id = ? ORDER BY equipped DESC, tier DESC",
            (discord_id,)
        ).fetchall()
        residences = conn.execute(
            "SELECT city FROM residences WHERE discord_id = ?", (discord_id,)
        ).fetchall()
        quests_raw = player.get("active_quest")
    player["techniques"] = json.loads(player.get("techniques") or "[]")
    equipment = [dict(e) for e in equipment]
    for e in equipment:
        e["stats"] = json.loads(e.get("stats") or "{}")
    return templates.TemplateResponse("player_detail.html", {
        "request": request, "player": player,
        "inventory": [dict(i) for i in inventory],
        "equipment": equipment,
        "residences": [r["city"] for r in residences],
        "quest": json.loads(quests_raw) if quests_raw else None,
    })


@app.get("/events", response_class=HTMLResponse)
async def events(request: Request):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM public_events ORDER BY started_at DESC"
        ).fetchall()
        events = []
        for r in rows:
            e = dict(r)
            e["data"] = json.loads(e.get("data") or "{}")
            participants = conn.execute(
                "SELECT ep.discord_id, ep.contribution, ep.activity, p.name "
                "FROM public_event_participants ep "
                "LEFT JOIN players p ON ep.discord_id = p.discord_id "
                "WHERE ep.event_id = ? ORDER BY ep.contribution DESC",
                (e["event_id"],)
            ).fetchall()
            e["participants"] = [dict(p) for p in participants]
            events.append(e)
    return templates.TemplateResponse("events.html", {
        "request": request, "events": events,
    })


@app.get("/dead", response_class=HTMLResponse)
async def dead_players(request: Request):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM players WHERE is_dead=1 ORDER BY last_active DESC"
        ).fetchall()
    return templates.TemplateResponse("dead.html", {
        "request": request, "players": [dict(r) for r in rows],
    })
