from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from .activity import list_activity
from .auth import current_user, login_user, register_user, require_user
from .db import get_db, get_setting
from .player import (
    collection_locations,
    collection_rows,
    collection_summary,
    collection_variant,
    create_deck,
    delete_deck,
    export_collection_csv,
    export_collection_json,
    get_deck,
    list_decks,
    rename_deck,
    set_collection,
    set_deck_card,
)
from .game import (
    TAG_PRESETS,
    add_pull as add_pull,
    apply_deck_import as apply_deck_import,
    attach_flags,
    banned_codes,
    collection_value as collection_value,
    deck_text as deck_text,
    expensive_gaps as expensive_gaps,
    find_by_code as find_by_code,
    list_pulls,
    pal_family as pal_family,
    parse_deck_text as parse_deck_text,
    prefer_foil_printing,
    random_booster as random_booster,
    save_banlist,
    save_notes,
    set_progress as set_progress,
    trade_board as trade_board,
    user_notes,
)


def register_player_routes(app, templates: Jinja2Templates) -> None:
    def page(request: Request, name: str, **ctx: Any):
        return templates.TemplateResponse(
            name,
            {
                "request": request,
                "user": current_user(request),
                "is_admin": bool(request.session.get("admin")),
                **ctx,
            },
        )

    @app.get("/konto")
    def konto_page(request: Request, next: str = "/"):
        user = current_user(request)
        history = list_activity(user["id"]) if user else []
        return page(request, "konto.html", next=next, error=None, mode="login", activity=history)

    @app.post("/konto/register")
    async def konto_register(request: Request):
        form = await request.form()
        username = str(form.get("username") or "")
        password = str(form.get("password") or "")
        next_url = str(form.get("next") or "/") or "/"
        if not next_url.startswith("/"):
            next_url = "/"
        uid, err = register_user(username, password)
        if err or uid is None:
            return page(request, "konto.html", error=err, mode="register", next=next_url)
        request.session["user_id"] = uid
        return RedirectResponse(next_url, status_code=303)

    @app.post("/konto/login")
    async def konto_login(request: Request):
        form = await request.form()
        username = str(form.get("username") or "")
        password = str(form.get("password") or "")
        next_url = str(form.get("next") or "/") or "/"
        if not next_url.startswith("/"):
            next_url = "/"
        user = login_user(username, password)
        if not user:
            return page(
                request,
                "konto.html",
                error="Benutzername oder Passwort stimmt nicht.",
                mode="login",
                next=next_url,
            )
        request.session["user_id"] = user["id"]
        return RedirectResponse(next_url, status_code=303)

    @app.post("/konto/logout")
    async def konto_logout(request: Request):
        request.session.pop("user_id", None)
        return RedirectResponse("/", status_code=303)

    @app.get("/api/me")
    def api_me(request: Request):
        user = current_user(request)
        if not user:
            return {"logged_in": False}
        return {"logged_in": True, "id": user["id"], "username": user["username"]}

    @app.get("/sammlung")
    def sammlung_page(request: Request):
        user = current_user(request)
        if not user:
            return RedirectResponse("/konto?next=/sammlung", status_code=303)
        return page(
            request,
            "collection.html",
            summary=collection_summary(user["id"]),
            value=collection_value(user["id"]),
        )

    @app.get("/api/collection")
    def api_collection(
        request: Request, status: str = "", location: str = "", condition: str = ""
    ):
        user = require_user(request)
        if status not in {"", "have", "need", "missing"}:
            status = ""
        items = collection_rows(user["id"], status, location, condition)
        return {
            "items": items,
            "summary": collection_summary(user["id"]),
            "status": status,
            "location": location,
            "condition": condition,
            "locations": collection_locations(user["id"]),
        }

    @app.put("/api/collection/{card_id}")
    async def api_collection_set(request: Request, card_id: int):
        user = require_user(request)
        body = await request.json()
        try:
            rec = set_collection(
                user["id"],
                card_id,
                body.get("owned"),
                body.get("wanted"),
                condition=body.get("condition"),
                location=body.get("location"),
                for_trade=body.get("for_trade"),
                notes=body.get("notes"),
            )
        except KeyError:
            raise HTTPException(404, "Karte nicht gefunden") from None
        return {"ok": True, **rec, "summary": collection_summary(user["id"])}

    @app.get("/api/collection/export.csv")
    def api_collection_csv(request: Request):
        user = require_user(request)
        data = export_collection_csv(user["id"])
        return Response(
            content=data,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="sammlung.csv"'},
        )

    @app.get("/api/collection/export.json")
    def api_collection_json(request: Request):
        user = require_user(request)
        return JSONResponse(
            export_collection_json(user["id"]),
            headers={"Content-Disposition": 'attachment; filename="sammlung.json"'},
        )

    @app.get("/decks")
    def decks_page(request: Request):
        user = current_user(request)
        if not user:
            return RedirectResponse("/konto?next=/decks", status_code=303)
        return page(request, "decks.html", decks=list_decks(user["id"]))

    @app.get("/decks/{deck_id}")
    def deck_builder_page(request: Request, deck_id: int):
        user = current_user(request)
        if not user:
            return RedirectResponse(f"/konto?next=/decks/{deck_id}", status_code=303)
        deck = get_deck(user["id"], deck_id)
        if not deck:
            raise HTTPException(404, "Deck nicht gefunden")
        return page(request, "deck.html", deck=deck)

    @app.get("/api/decks")
    def api_decks(request: Request):
        user = require_user(request)
        return {"items": list_decks(user["id"])}

    @app.post("/api/decks")
    async def api_decks_create(request: Request):
        user = require_user(request)
        body = await request.json()
        deck_id = create_deck(user["id"], str(body.get("name") or "Neues Deck"))
        return {"ok": True, "id": deck_id, "deck": get_deck(user["id"], deck_id)}

    @app.get("/api/decks/{deck_id}")
    def api_deck_get(request: Request, deck_id: int):
        user = require_user(request)
        deck = get_deck(user["id"], deck_id)
        if not deck:
            raise HTTPException(404, "Deck nicht gefunden")
        return deck

    @app.patch("/api/decks/{deck_id}")
    async def api_deck_patch(request: Request, deck_id: int):
        user = require_user(request)
        body = await request.json()
        if not rename_deck(user["id"], deck_id, str(body.get("name") or "")):
            raise HTTPException(404, "Deck nicht gefunden")
        return {"ok": True, "deck": get_deck(user["id"], deck_id)}

    @app.delete("/api/decks/{deck_id}")
    def api_deck_delete(request: Request, deck_id: int):
        user = require_user(request)
        if not delete_deck(user["id"], deck_id):
            raise HTTPException(404, "Deck nicht gefunden")
        return {"ok": True}

    @app.put("/api/decks/{deck_id}/cards/{card_id}")
    async def api_deck_card(request: Request, deck_id: int, card_id: int):
        user = require_user(request)
        body = await request.json()
        try:
            deck = set_deck_card(
                user["id"],
                deck_id,
                card_id,
                int(body.get("qty") or 0),
            )
        except KeyError:
            raise HTTPException(404, "Karte nicht gefunden") from None
        if not deck:
            raise HTTPException(404, "Deck nicht gefunden")
        return deck

    @app.get("/tausch")
    def trade_page(request: Request):
        user = current_user(request)
        if not user:
            return RedirectResponse("/konto?next=/tausch", status_code=303)
        return page(request, "trade.html", board=trade_board(user["id"]))

    @app.get("/booster")
    def booster_page(request: Request, edition: str = ""):
        pack = random_booster(edition or None)
        return page(request, "booster.html", pack=pack)

    @app.get("/decks/{deck_id}/proxies")
    def deck_proxies(request: Request, deck_id: int):
        user = current_user(request)
        if not user:
            return RedirectResponse(f"/konto?next=/decks/{deck_id}/proxies", status_code=303)
        deck = get_deck(user["id"], deck_id)
        if not deck:
            raise HTTPException(404, "Deck nicht gefunden")
        copies = []
        for card in deck["cards"]:
            copies.extend([card] * int(card.get("qty") or 1))
        return page(request, "proxies.html", deck=deck, copies=copies)

    @app.get("/decks/{deck_id}/export.txt")
    def deck_export_txt(request: Request, deck_id: int):
        user = require_user(request)
        deck = get_deck(user["id"], deck_id)
        if not deck:
            raise HTTPException(404, "Deck nicht gefunden")
        name = (deck.get("name") or "deck").replace(" ", "_")
        return Response(
            content=deck_text(deck),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}.txt"'},
        )

    @app.get("/decks/{deck_id}/export.json")
    def deck_export_json(request: Request, deck_id: int):
        user = require_user(request)
        deck = get_deck(user["id"], deck_id)
        if not deck:
            raise HTTPException(404, "Deck nicht gefunden")
        payload = {
            "name": deck.get("name"),
            "format": "palworld-tcg",
            "cards": [
                {
                    "qty": c.get("qty"),
                    "card_code": c.get("card_code"),
                    "name": c.get("name"),
                    "rarity": c.get("rarity"),
                    "foil": bool(c.get("foil")),
                }
                for c in deck.get("cards") or []
            ],
        }
        name = (deck.get("name") or "deck").replace(" ", "_")
        return JSONResponse(
            payload,
            headers={"Content-Disposition": f'attachment; filename="{name}.json"'},
        )

    @app.post("/api/decks/{deck_id}/import")
    async def api_deck_import(request: Request, deck_id: int):
        user = require_user(request)
        body = await request.json()
        items = parse_deck_text(str(body.get("text") or ""))
        try:
            apply_deck_import(user["id"], deck_id, items)
        except KeyError:
            raise HTTPException(404, "Deck nicht gefunden") from None
        return get_deck(user["id"], deck_id)

    @app.get("/api/collection/progress")
    def api_progress(request: Request):
        user = require_user(request)
        with get_db() as conn:
            synced = get_setting(conn, "prices_synced_at")
            raw = get_setting(conn, "prices_sync_summary") or "{}"
        try:
            sync_info = json.loads(raw)
        except json.JSONDecodeError:
            sync_info = {}
        return {
            "sets": set_progress(user["id"]),
            "value": collection_value(user["id"]),
            "gaps": expensive_gaps(user["id"]),
            "prices_synced_at": synced,
            "prices_sync": sync_info,
            "is_admin": bool(request.session.get("admin")),
        }

    @app.get("/api/lookup")
    def api_lookup(q: str = ""):
        return {"items": find_by_code(q)}

    @app.post("/api/collection/add-code")
    async def api_add_code(request: Request):
        user = require_user(request)
        body = await request.json()
        matches = find_by_code(str(body.get("code") or ""))
        if not matches:
            raise HTTPException(404, "Keine Karte zu diesem Code.")
        if len(matches) > 1 and not body.get("card_id"):
            return {"ok": False, "need_pick": True, "items": matches}
        card_id = int(body.get("card_id") or matches[0]["id"])
        foil_flag = body.get("foil")
        if foil_flag is True or foil_flag == 1 or str(foil_flag).strip().lower() in {"1", "true", "yes", "on", "foil"}:
            card_id = prefer_foil_printing(card_id)
        qty = max(1, min(99, int(body.get("owned") or 1)))
        prev = collection_variant(user["id"], card_id)
        rec = set_collection(user["id"], card_id, int(prev.get("owned") or 0) + qty, None)
        source = str(body.get("source") or "").strip()
        if source:
            add_pull(user["id"], card_id, source, qty, increment=False)
        return {"ok": True, **rec, "card": next((c for c in matches if c["id"] == card_id), matches[0])}

    @app.post("/api/pulls")
    async def api_pulls_add(request: Request):
        user = require_user(request)
        body = await request.json()
        try:
            return add_pull(
                user["id"],
                int(body.get("card_id")),
                str(body.get("source") or ""),
                int(body.get("qty") or 1),
            )
        except (KeyError, TypeError, ValueError):
            raise HTTPException(400, "Karte oder Display fehlt.") from None

    @app.get("/api/pulls")
    def api_pulls_list(request: Request):
        user = require_user(request)
        return {"items": list_pulls(user["id"])}

    @app.get("/api/trade")
    def api_trade(request: Request):
        user = require_user(request)
        return {"items": trade_board(user["id"])}

    @app.put("/api/cards/{card_id}/notes")
    async def api_card_notes(request: Request, card_id: int):
        user = require_user(request)
        body = await request.json()
        tags = body.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        return save_notes(user["id"], card_id, str(body.get("notes") or ""), list(tags))

    @app.get("/api/booster")
    def api_booster(edition: str = ""):
        return random_booster(edition or None)
