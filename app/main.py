from __future__ import annotations

import json
import queue
import re
import secrets
import shutil
import threading
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pypdf import PdfReader
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .auth import (
    can_open_admin,
    current_user,
    grant_admin,
    list_users,
    require_rules,
    set_user_flags,
    template_globals,
)
from .chat import ask_gemini
from .config import (
    ADMIN_PASSWORD,
    GEMINI_DEFAULT_MODEL,
    HTTPS_ONLY,
    IMAGES_DIR,
    RULES_DIR,
    SECRET_KEY,
    SEED_DIR,
    ensure_dirs,
)
from .game import (
    CONDITIONS,
    TAG_PRESETS,
    attach_flags,
    errata_excerpt,
    pal_family,
    save_banlist,
    user_notes,
)
from .player import attach_collection, printings_for
from .routes_player import register_player_routes
from .db import (
    FOIL_RARITIES,
    delete_card,
    delete_edition,
    get_db,
    get_setting,
    init_db,
    landscape_flag,
    row_to_card,
    set_setting,
    update_card,
    upsert_card,
    upsert_edition,
    wipe_catalog,
)
from .importer import archive_cardlist, attach_images_from_zip, import_cards
from .keywords import term_pill, terms_for_client
from .texticons import render_effect

APP_DIR = Path(__file__).resolve().parent
ensure_dirs()
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.filters["effect_icons"] = render_effect
templates.env.filters["term_pill"] = term_pill
templates.env.globals["glossary_json"] = json.dumps(terms_for_client(), ensure_ascii=False)

app = FastAPI(title="Palworld TCG", docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    same_site="lax",
    https_only=HTTPS_ONLY,
    max_age=60 * 60 * 24 * 14,
)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")


def page(request: Request, name: str, **ctx: Any) -> HTMLResponse:
    return templates.TemplateResponse(
        name,
        {
            "request": request,
            **template_globals(request),
            **ctx,
        },
    )


def _pdf_text(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            chunk = page.extract_text() or ""
        except Exception:
            chunk = ""
        if chunk.strip():
            pages.append(f"--- page {i} ---\n{chunk.strip()}")
    return "\n\n".join(pages).strip()


def _store_rules_pdf(conn, filename: str, data: bytes) -> dict[str, Any]:
    dest = RULES_DIR / "rules.pdf"
    dest.write_bytes(data)
    text = _pdf_text(data)
    conn.execute("DELETE FROM rules")
    conn.execute(
        "INSERT INTO rules(id, filename, stored_path, text, uploaded_at) VALUES (1, ?, ?, ?, datetime('now'))",
        (filename, str(dest), text),
    )
    return {"filename": filename, "chars": len(text), "pages_ok": bool(text)}


def _store_errata(conn, filename: str, data: bytes) -> dict[str, Any]:
    suffix = Path(filename or "errata.txt").suffix.lower() or ".txt"
    if suffix not in {".pdf", ".txt", ".md"}:
        suffix = ".txt"
    dest = RULES_DIR / f"errata{suffix}"
    dest.write_bytes(data)
    if suffix == ".pdf":
        text = _pdf_text(data)
    else:
        text = data.decode("utf-8", errors="replace")
    conn.execute("DELETE FROM errata")
    conn.execute(
        "INSERT INTO errata(id, filename, stored_path, text, uploaded_at) VALUES (1, ?, ?, ?, datetime('now'))",
        (filename, str(dest), text),
    )
    return {"filename": filename, "chars": len(text)}


def _maybe_seed_rules(conn) -> None:
    if conn.execute("SELECT id FROM rules WHERE id = 1").fetchone():
        return
    for candidate in (SEED_DIR / "rules.pdf", Path("/seed/rules.pdf"), APP_DIR.parent / "rules.pdf"):
        if candidate.is_file():
            _store_rules_pdf(conn, candidate.name, candidate.read_bytes())
            break


@app.on_event("startup")
def on_startup() -> None:
    ensure_dirs()
    init_db()
    with get_db() as conn:
        _maybe_seed_rules(conn)


def _logged_in(request: Request) -> bool:
    return bool(request.session.get("admin"))


def _require_admin(request: Request) -> None:
    user = current_user(request)
    if not can_open_admin(user):
        raise HTTPException(403, "Kein Admin-Recht.")
    if not _logged_in(request):
        raise HTTPException(401, "Nicht angemeldet")


def _unlink_image(rel: str | None) -> None:
    if not rel:
        return
    path = (IMAGES_DIR / rel).resolve()
    if str(path).startswith(str(IMAGES_DIR.resolve())) and path.is_file():
        path.unlink()


def _filters(conn) -> dict[str, Any]:
    def col(sql: str) -> list[str]:
        return [r[0] for r in conn.execute(sql).fetchall() if r[0]]

    return {
        "types": col("SELECT DISTINCT card_type FROM cards WHERE card_type IS NOT NULL ORDER BY card_type"),
        "colors": col("SELECT DISTINCT color FROM cards WHERE color IS NOT NULL ORDER BY color"),
        "rarities": col("SELECT DISTINCT rarity FROM cards WHERE rarity IS NOT NULL AND rarity != '' ORDER BY rarity"),
        "editions": [
            {"code": r["code"], "name": r["name"]}
            for r in conn.execute("SELECT code, name FROM editions ORDER BY code").fetchall()
        ],
        "attributes": [
            r[0]
            for r in conn.execute(
                """
                SELECT DISTINCT json_each.value
                FROM cards, json_each(cards.attributes)
                WHERE json_each.value IS NOT NULL AND json_each.value != ''
                ORDER BY json_each.value
                """
            ).fetchall()
        ],
        "aptitudes": [
            r[0]
            for r in conn.execute(
                """
                SELECT DISTINCT json_each.value
                FROM cards, json_each(cards.aptitudes)
                WHERE json_each.value IS NOT NULL AND json_each.value != ''
                ORDER BY json_each.value
                """
            ).fetchall()
        ],
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    with get_db() as conn:
        stats = {
            "cards": conn.execute("SELECT COUNT(*) AS n FROM cards").fetchone()["n"],
            "editions": conn.execute("SELECT COUNT(*) AS n FROM editions").fetchone()["n"],
        }
        filters = _filters(conn)
    return page(request, "index.html", stats=stats, filters=filters)


@app.get("/glossar", response_class=HTMLResponse)
def glossar_page(request: Request) -> HTMLResponse:
    from markupsafe import Markup, escape

    from .keywords import ICON_KEYS, glossary_sections, wrap_icon

    sections = []
    for section in glossary_sections():
        items = []
        for item in section["entries"]:
            key = item["key"]
            if key in ICON_KEYS:
                inner = Markup(
                    f'<img src="/static/img/{key}.png" alt="" class="kw-img" width="28" height="28"> '
                    f"{escape(item['title'])}"
                )
                title_html = wrap_icon(inner, key)
            else:
                title_html = Markup(escape(item["title"]))
            items.append({**item, "title_html": title_html})
        sections.append({"title": section["title"], "entries": items})
    return page(request, "glossar.html", sections=sections)


@app.get("/card/{card_id}", response_class=HTMLResponse)
def card_page(request: Request, card_id: int) -> HTMLResponse:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT cards.*, editions.code AS edition_code, editions.name AS edition_name
            FROM cards
            LEFT JOIN editions ON editions.id = cards.edition_id
            WHERE cards.id = ?
            """,
            (card_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Karte nicht gefunden")
        card = row_to_card(row)
        variants = [
            row_to_card(r)
            for r in conn.execute(
                """
                SELECT cards.*, editions.code AS edition_code
                FROM cards
                LEFT JOIN editions ON editions.id = cards.edition_id
                WHERE cards.name = ? AND cards.id != ?
                ORDER BY rarity, card_code
                """,
                (card["name"], card_id),
            ).fetchall()
        ]
    attach_flags([card])
    card["errata_excerpt"] = errata_excerpt(card) if card.get("has_errata") else ""
    user = current_user(request)
    notes = {"notes": "", "tags": []}
    if user:
        attach_collection([card], user["id"])
        notes = user_notes(user["id"], card_id)
    family = [c for c in pal_family(card_id) if c["id"] != card_id]
    return page(
        request,
        "card.html",
        card=card,
        variants=variants,
        family=family,
        notes=notes,
        tag_presets=TAG_PRESETS,
        conditions=CONDITIONS,
    )


@app.get("/compare/{card_id}", response_class=HTMLResponse)
def compare_page(request: Request, card_id: int) -> HTMLResponse:
    printings = printings_for(card_id)
    if not printings:
        raise HTTPException(404, "Karte nicht gefunden")
    user = current_user(request)
    if user:
        attach_collection(printings, user["id"])
    return page(
        request,
        "compare.html",
        cards=printings,
        name=printings[0]["name"],
        card_code=printings[0]["card_code"],
    )


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request) -> HTMLResponse:
    user = current_user(request)
    if not user:
        return RedirectResponse("/konto?next=/admin", status_code=303)
    if not can_open_admin(user):
        return page(request, "admin.html", authed=False, denied=True, error=None)
    if not _logged_in(request):
        return page(request, "admin.html", authed=False, denied=False, error=None)
    with get_db() as conn:
        key = get_setting(conn, "gemini_api_key") or ""
        model = get_setting(conn, "gemini_model") or GEMINI_DEFAULT_MODEL
        rules = conn.execute(
            "SELECT filename, uploaded_at, length(text) AS chars FROM rules WHERE id = 1"
        ).fetchone()
        errata = conn.execute(
            "SELECT filename, uploaded_at, length(text) AS chars FROM errata WHERE id = 1"
        ).fetchone()
        stats = {
            "cards": conn.execute("SELECT COUNT(*) AS n FROM cards").fetchone()["n"],
            "images": conn.execute(
                "SELECT COUNT(*) AS n FROM cards WHERE image_path IS NOT NULL AND image_path != ''"
            ).fetchone()["n"],
            "editions": [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT editions.code, editions.name, COUNT(cards.id) AS n
                    FROM editions LEFT JOIN cards ON cards.edition_id = editions.id
                    GROUP BY editions.id
                    ORDER BY editions.code
                    """
                ).fetchall()
            ],
        }
        banned_codes = get_setting(conn, "banned_codes") or ""
        pw_id = get_setting(conn, "palworldcard_identity") or ""
        prices_synced_at = get_setting(conn, "prices_synced_at") or ""
    masked = (key[:4] + "…" + key[-4:]) if len(key) > 10 else ("••••" if key else "")
    pw_masked = (pw_id[:2] + "…" + pw_id[-4:]) if len(pw_id) > 8 else ("••••" if pw_id else "")
    return page(
        request,
        "admin.html",
        authed=True,
        error=None,
        api_key_masked=masked,
        has_key=bool(key),
        model=model,
        rules=dict(rules) if rules else None,
        errata=dict(errata) if errata else None,
        stats=stats,
        banned_codes=banned_codes,
        palworldcard_identity_masked=pw_masked,
        has_palworldcard=bool(pw_id),
        prices_synced_at=prices_synced_at,
        users=list_users(),
    )


@app.post("/admin/login")
async def admin_login(request: Request, password: str = Form(...)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/konto?next=/admin", status_code=303)
    if not can_open_admin(user):
        return page(request, "admin.html", authed=False, denied=True, error=None)
    if secrets.compare_digest(password, ADMIN_PASSWORD):
        if not user.get("is_admin"):
            grant_admin(user["id"])
        request.session["admin"] = True
        return RedirectResponse("/admin", status_code=303)
    return page(request, "admin.html", authed=False, denied=False, error="Falsches Passwort.")


@app.post("/admin/logout")
async def admin_logout(request: Request):
    request.session.pop("admin", None)
    return RedirectResponse("/admin", status_code=303)


@app.get("/api/admin/users")
def admin_users(request: Request):
    _require_admin(request)
    return {"items": list_users()}


@app.patch("/api/admin/users/{user_id}")
async def admin_user_patch(request: Request, user_id: int):
    actor = current_user(request)
    _require_admin(request)
    body = await request.json()
    try:
        rec = set_user_flags(
            user_id,
            is_admin=body["is_admin"] if "is_admin" in body else None,
            can_rules=body["can_rules"] if "can_rules" in body else None,
        )
    except KeyError:
        raise HTTPException(404, "Benutzer nicht gefunden") from None
    except ValueError:
        raise HTTPException(400, "Mindestens ein Admin muss bleiben.") from None
    if actor and int(actor["id"]) == int(user_id) and not rec.get("is_admin"):
        request.session.pop("admin", None)
    return {"ok": True, **rec}


def _fts_query(q: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9]+", q or "")
    return " AND ".join(f"{t}*" for t in tokens if len(t) >= 2)


CARD_ORDER = """
ORDER BY IFNULL(editions.code, 'ZZZ') COLLATE NOCASE,
         CAST(substr(cards.card_code, instr(cards.card_code || '-', '-') + 1) AS INTEGER),
         cards.card_code COLLATE NOCASE,
         cards.rarity COLLATE NOCASE,
         cards.id
"""


@app.get("/api/cards")
def api_cards(
    request: Request,
    q: str = "",
    type: str = "",
    color: str = "",
    rarity: str = "",
    edition: str = "",
    attribute: str = "",
    aptitude: str = "",
    have: str = "",
    sort: str = "",
    page: int = 1,
    limit: int = 96,
) -> dict[str, Any]:
    page = max(1, page)
    limit = min(max(1, limit), 200)
    offset = (page - 1) * limit
    where = ["1=1"]
    params: list[Any] = []
    user = current_user(request)

    if type:
        where.append("cards.card_type = ?")
        params.append(type)
    if color:
        where.append("cards.color = ?")
        params.append(color)
    if rarity:
        where.append("cards.rarity = ?")
        params.append(rarity)
    if edition:
        where.append("editions.code = ?")
        params.append(edition)
    if attribute:
        where.append(
            "EXISTS (SELECT 1 FROM json_each(cards.attributes) WHERE json_each.value = ?)"
        )
        params.append(attribute)
    if aptitude:
        where.append(
            "EXISTS (SELECT 1 FROM json_each(cards.aptitudes) WHERE json_each.value = ?)"
        )
        params.append(aptitude)
    if have and user:
        if have == "owned":
            where.append(
                "EXISTS (SELECT 1 FROM collection WHERE collection.card_id = cards.id "
                "AND collection.user_id = ? AND collection.owned > 0)"
            )
            params.append(user["id"])
        elif have == "wanted":
            where.append(
                "EXISTS (SELECT 1 FROM collection WHERE collection.card_id = cards.id "
                "AND collection.user_id = ? AND collection.wanted > collection.owned)"
            )
            params.append(user["id"])
        elif have == "missing":
            where.append(
                "NOT EXISTS (SELECT 1 FROM collection WHERE collection.card_id = cards.id "
                "AND collection.user_id = ? AND collection.owned > 0)"
            )
            params.append(user["id"])
        elif have == "foil":
            rarities = sorted(FOIL_RARITIES)
            placeholders = ",".join("?" * len(rarities))
            where.append(
                f"UPPER(IFNULL(cards.rarity,'')) IN ({placeholders}) AND EXISTS ("
                "SELECT 1 FROM collection WHERE collection.card_id = cards.id "
                "AND collection.user_id = ? AND collection.owned > 0)"
            )
            params.extend(rarities)
            params.append(user["id"])
        elif have == "incomplete":
            where.append(
                """IFNULL((
                    SELECT SUM(collection.owned) FROM collection
                    WHERE collection.card_id = cards.id AND collection.user_id = ?
                ), 0) < CASE
                    WHEN LOWER(TRIM(IFNULL(cards.card_type,''))) = 'soul'
                      OR LOWER(TRIM(IFNULL(cards.name,''))) = 'soul' THEN 10
                    WHEN LOWER(TRIM(IFNULL(cards.card_type,''))) = 'energy' THEN 99
                    ELSE 4
                END"""
            )
            params.append(user["id"])

    fts = _fts_query(q)
    with get_db() as conn:
        join = "LEFT JOIN editions ON editions.id = cards.edition_id"
        if sort == "price":
            order = (
                "ORDER BY IFNULL(cards.price_cents, 0) DESC, IFNULL(editions.code, 'ZZZ') COLLATE NOCASE, "
                "cards.card_code COLLATE NOCASE, cards.id"
            )
        elif sort == "rarity":
            order = (
                "ORDER BY cards.rarity COLLATE NOCASE, IFNULL(editions.code, 'ZZZ') COLLATE NOCASE, "
                "cards.card_code COLLATE NOCASE, cards.id"
            )
        elif sort == "name":
            order = "ORDER BY cards.name COLLATE NOCASE, cards.card_code COLLATE NOCASE, cards.id"
        else:
            order = CARD_ORDER
        if fts:
            try:
                ids = [
                    r[0]
                    for r in conn.execute(
                        "SELECT rowid FROM cards_fts WHERE cards_fts MATCH ? ORDER BY rank",
                        (fts,),
                    ).fetchall()
                ]
            except Exception:
                ids = []
            if not ids:
                like = f"%{q.strip()}%"
                where.append(
                    "(cards.name LIKE ? OR cards.card_code LIKE ? OR IFNULL(cards.effect,'') LIKE ? "
                    "OR IFNULL(cards.search_blob,'') LIKE ?)"
                )
                params.extend([like, like, like, like])
            else:
                placeholders = ",".join("?" * len(ids))
                where.append(f"cards.id IN ({placeholders})")
                params.extend(ids)

        where_sql = " AND ".join(where)
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM cards {join} WHERE {where_sql}", params
        ).fetchone()["n"]
        rows = conn.execute(
            f"""
            SELECT cards.*, editions.code AS edition_code, editions.name AS edition_name
            FROM cards {join}
            WHERE {where_sql}
            {order}
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        items = [row_to_card(r) for r in rows]
    attach_flags(items)
    if user:
        attach_collection(items, user["id"])
    return {"items": items, "total": total, "page": page, "limit": limit}


@app.get("/api/cards/{card_id}")
def api_card(request: Request, card_id: int) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT cards.*, editions.code AS edition_code, editions.name AS edition_name
            FROM cards
            LEFT JOIN editions ON editions.id = cards.edition_id
            WHERE cards.id = ?
            """,
            (card_id,),
        ).fetchone()
    card = row_to_card(row)
    if not card:
        raise HTTPException(404, "Karte nicht gefunden")
    attach_flags([card])
    user = current_user(request)
    if user:
        attach_collection([card], user["id"])
    card["effect_html"] = str(render_effect(card.get("effect")))
    card["errata_excerpt"] = errata_excerpt(card) if card.get("has_errata") else ""
    family = [c for c in pal_family(card_id) if c["id"] != card_id]
    card["family"] = [
        {
            "id": c["id"],
            "name": c.get("name"),
            "card_code": c.get("card_code"),
            "rarity": c.get("rarity"),
            "image_url": c.get("image_url"),
            "landscape": c.get("landscape"),
        }
        for c in family
    ]
    return card


@app.post("/api/admin/settings")
async def admin_settings(request: Request):
    _require_admin(request)
    body = await request.json()
    with get_db() as conn:
        if body.get("clear_key"):
            set_setting(conn, "gemini_api_key", None)
        elif "gemini_api_key" in body:
            key = (body.get("gemini_api_key") or "").strip()
            if key:
                set_setting(conn, "gemini_api_key", key)
        if "gemini_model" in body:
            set_setting(conn, "gemini_model", (body.get("gemini_model") or GEMINI_DEFAULT_MODEL).strip())
        if "edition_rename" in body:
            item = body["edition_rename"]
            conn.execute(
                "UPDATE editions SET name = ? WHERE code = ?",
                (item.get("name"), item.get("code")),
            )
        if "banned_codes" in body:
            save_banlist(str(body.get("banned_codes") or ""))
        if body.get("clear_palworldcard"):
            set_setting(conn, "palworldcard_identity", None)
            set_setting(conn, "palworldcard_password", None)
        else:
            if "palworldcard_identity" in body:
                ident = (body.get("palworldcard_identity") or "").strip()
                if ident:
                    set_setting(conn, "palworldcard_identity", ident)
            if "palworldcard_password" in body:
                pwd = body.get("palworldcard_password") or ""
                if str(pwd).strip():
                    set_setting(conn, "palworldcard_password", str(pwd))
    return {"ok": True}


@app.post("/api/admin/prices/sync")
def admin_price_sync(request: Request):
    _require_admin(request)
    from .prices import sync_official_prices

    try:
        summary = sync_official_prices()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from None
    except Exception as exc:
        raise HTTPException(502, f"Preisabgleich fehlgeschlagen: {exc}") from None
    return {"ok": True, **summary}


@app.post("/api/admin/import")
async def admin_import(
    request: Request,
    file: UploadFile = File(...),
    edition_name: str = Form(""),
    images_zip: UploadFile | None = File(default=None),
):
    _require_admin(request)
    html = (await file.read()).decode("utf-8", errors="replace")
    archive_cardlist(file.filename, html)
    zip_bytes = b""
    if images_zip and images_zip.filename:
        zip_bytes = await images_zip.read()

    events: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def progress(event: dict[str, Any]) -> None:
        events.put(event)

    def run() -> None:
        try:
            result = import_cards(
                html,
                edition_name=edition_name.strip() or None,
                progress=progress,
            )
            if zip_bytes:
                img = attach_images_from_zip(zip_bytes, progress=progress)
                result = {**result, "images_ok": img.get("ok", 0), "images_unmatched": img.get("unmatched", 0)}
                events.put({**result, "stage": "done"})
        except Exception as exc:
            events.put({"stage": "error", "error": str(exc)})
        finally:
            events.put(None)

    threading.Thread(target=run, daemon=True).start()

    def stream():
        while True:
            item = events.get()
            if item is None:
                break
            yield json.dumps(item, ensure_ascii=False) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.post("/api/admin/rules")
async def admin_rules(request: Request, file: UploadFile = File(...)):
    _require_admin(request)
    data = await file.read()
    if not data:
        raise HTTPException(400, "Leere Datei")
    with get_db() as conn:
        info = _store_rules_pdf(conn, file.filename or "rules.pdf", data)
    return {"ok": True, **info}


@app.post("/api/admin/errata")
async def admin_errata(request: Request, file: UploadFile = File(...)):
    _require_admin(request)
    data = await file.read()
    if not data:
        raise HTTPException(400, "Leere Datei")
    with get_db() as conn:
        info = _store_errata(conn, file.filename or "errata.txt", data)
    return {"ok": True, **info}


@app.get("/api/catalog.json")
def api_catalog() -> dict[str, Any]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT cards.id, cards.card_code, cards.name, cards.rarity, cards.card_type,
                   cards.color, cards.attributes, cards.aptitudes, cards.cost, cards.image_path,
                   cards.landscape, editions.code AS edition_code
            FROM cards
            LEFT JOIN editions ON editions.id = cards.edition_id
            ORDER BY editions.code, cards.card_code, cards.rarity
            """
        ).fetchall()
    items = []
    for row in rows:
        card = row_to_card(row)
        items.append(
            {
                "id": card["id"],
                "card_code": card.get("card_code"),
                "name": card.get("name"),
                "rarity": card.get("rarity"),
                "card_type": card.get("card_type"),
                "color": card.get("color"),
                "attributes": card.get("attributes") or [],
                "aptitudes": card.get("aptitudes") or [],
                "cost": card.get("cost"),
                "edition_code": card.get("edition_code"),
                "image_url": card.get("image_url"),
                "landscape": card.get("landscape"),
            }
        )
    return {"items": items}


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    path = APP_DIR / "static" / "manifest.webmanifest"
    return FileResponse(path, media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker() -> FileResponse:
    return FileResponse(APP_DIR / "static" / "sw.js", media_type="application/javascript")


@app.get("/offline", response_class=HTMLResponse)
def offline_page(request: Request) -> HTMLResponse:
    return page(request, "offline.html")


@app.post("/api/chat")
async def api_chat(request: Request):
    require_rules(request)
    body = await request.json()
    message = (body.get("message") or "").strip()
    history = body.get("history") or []
    if not isinstance(history, list):
        history = []
    clean_hist = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "model"} and isinstance(content, str):
            clean_hist.append({"role": role, "content": content[:8000]})
    return JSONResponse(ask_gemini(message, clean_hist))


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Ungültige Zahl") from exc


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [p.strip() for p in str(value).replace(";", ",").split(",") if p.strip()]


def _price_cents(body: dict[str, Any]) -> int | None:
    if body.get("price_cents") not in (None, ""):
        return _as_int(body.get("price_cents"))
    raw = body.get("price_euros")
    if raw in (None, ""):
        return None
    try:
        return int(round(float(str(raw).replace(",", ".")) * 100))
    except (TypeError, ValueError):
        return None


def _card_payload(body: dict[str, Any], conn) -> dict[str, Any]:
    edition_code = (body.get("edition_code") or "").strip().upper()
    edition_id = None
    if edition_code:
        edition_id = upsert_edition(conn, edition_code, body.get("edition_name") or edition_code)
    elif body.get("edition_id"):
        edition_id = _as_int(body.get("edition_id"))
    name = (body.get("name") or "").strip()
    card_code = (body.get("card_code") or "").strip()
    if not name or not card_code:
        raise HTTPException(400, "Name und Kartencode sind Pflicht.")
    return {
        "official_id": _as_int(body.get("official_id")),
        "card_code": card_code,
        "name": name,
        "rarity": (body.get("rarity") or "").strip(),
        "card_type": (body.get("card_type") or "").strip() or None,
        "subtype": (body.get("subtype") or "").strip() or None,
        "color": (body.get("color") or "").strip() or None,
        "attributes": _as_list(body.get("attributes")),
        "aptitudes": _as_list(body.get("aptitudes")),
        "cost": _as_int(body.get("cost")),
        "power": _as_int(body.get("power")),
        "strike": _as_int(body.get("strike")),
        "effect": (body.get("effect") or "").strip() or None,
        "edition_id": edition_id,
        "edition_code": edition_code,
        "image_url": None,
        "source_url": None,
        "banned": 1 if body.get("banned") in (True, 1, "1", "true", "on") else 0,
        "price_cents": _price_cents(body),
    }


@app.post("/api/admin/cards")
async def admin_create_card(request: Request):
    _require_admin(request)
    body = await request.json()
    with get_db() as conn:
        payload = _card_payload(body, conn)
        card_id, action = upsert_card(conn, payload)
        conn.execute(
            "UPDATE cards SET banned = ?, price_cents = ? WHERE id = ?",
            (payload.get("banned") or 0, payload.get("price_cents"), card_id),
        )
        row = conn.execute(
            """
            SELECT cards.*, editions.code AS edition_code, editions.name AS edition_name
            FROM cards LEFT JOIN editions ON editions.id = cards.edition_id
            WHERE cards.id = ?
            """,
            (card_id,),
        ).fetchone()
    return {"ok": True, "action": action, "card": row_to_card(row)}


@app.put("/api/admin/cards/{card_id}")
async def admin_update_card(request: Request, card_id: int):
    _require_admin(request)
    body = await request.json()
    with get_db() as conn:
        payload = _card_payload(body, conn)
        card = update_card(conn, card_id, payload)
        if not card:
            raise HTTPException(404, "Karte nicht gefunden")
    return {"ok": True, "card": card}


@app.delete("/api/admin/cards/{card_id}")
def admin_delete_card(request: Request, card_id: int):
    _require_admin(request)
    with get_db() as conn:
        found, image_path = delete_card(conn, card_id)
    if not found:
        raise HTTPException(404, "Karte nicht gefunden")
    _unlink_image(image_path)
    return {"ok": True}


@app.post("/api/admin/cards/{card_id}/image")
async def admin_card_image(request: Request, card_id: int, file: UploadFile = File(...)):
    _require_admin(request)
    data = await file.read()
    if not data:
        raise HTTPException(400, "Leere Datei")
    ext = Path(file.filename or "card.png").suffix.lower() or ".png"
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        ext = ".png"
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT cards.card_code, cards.image_path, editions.code AS edition_code
            FROM cards LEFT JOIN editions ON editions.id = cards.edition_id
            WHERE cards.id = ?
            """,
            (card_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Karte nicht gefunden")
        old = row["image_path"]
        folder = row["edition_code"] or "misc"
        rel = f"{folder}/{row['card_code']}{ext}"
        dest = IMAGES_DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        rel_norm = rel.replace("\\", "/")
        conn.execute(
            "UPDATE cards SET image_path = ?, landscape = ?, updated_at = datetime('now') WHERE id = ?",
            (rel_norm, landscape_flag(rel_norm), card_id),
        )
    if old and old.replace("\\", "/") != rel.replace("\\", "/"):
        _unlink_image(old)
    return {"ok": True, "image_url": "/images/" + rel.replace("\\", "/")}


@app.delete("/api/admin/editions/{code}")
def admin_delete_edition(request: Request, code: str):
    _require_admin(request)
    with get_db() as conn:
        paths = delete_edition(conn, code)
    if paths is None:
        raise HTTPException(404, "Edition nicht gefunden")
    for rel in paths:
        _unlink_image(rel)
    folder = IMAGES_DIR / code
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
    return {"ok": True}


@app.post("/api/admin/wipe")
async def admin_wipe(request: Request):
    _require_admin(request)
    body = await request.json()
    if (body.get("confirm") or "") != "LÖSCHEN":
        raise HTTPException(400, "Bestätigung fehlt")
    with get_db() as conn:
        wipe_catalog(conn)
    if IMAGES_DIR.exists():
        shutil.rmtree(IMAGES_DIR)
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    return {"ok": True}


register_player_routes(app, templates)

app.mount("/images", StaticFiles(directory=str(IMAGES_DIR)), name="images")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
