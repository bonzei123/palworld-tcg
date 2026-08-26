from __future__ import annotations

import json
from typing import Any

from .db import get_db

KEEP = 2000
SHOW = 200


def _label(conn, card_id: int | None) -> str:
    if not card_id:
        return ""
    row = conn.execute(
        "SELECT card_code, name FROM cards WHERE id = ?",
        (card_id,),
    ).fetchone()
    if not row:
        return f"Karte #{card_id}"
    return f"{row['card_code']} · {row['name']}"


def _deck_name(conn, deck_id: int | None) -> str:
    if not deck_id:
        return "Deck"
    row = conn.execute("SELECT name FROM decks WHERE id = ?", (deck_id,)).fetchone()
    return (row["name"] if row else "Deck") or "Deck"


def log_activity(
    user_id: int,
    action: str,
    summary: str,
    *,
    card_id: int | None = None,
    deck_id: int | None = None,
    foil: int = 0,
    detail: dict[str, Any] | None = None,
    conn=None,
) -> None:
    blob = json.dumps(detail, ensure_ascii=False) if detail else None

    def _write(c) -> None:
        c.execute(
            """
            INSERT INTO activity(user_id, action, summary, card_id, deck_id, foil, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, action, summary[:400], card_id, deck_id, int(foil or 0), blob),
        )
        c.execute(
            """
            DELETE FROM activity
            WHERE user_id = ?
              AND id NOT IN (
                  SELECT id FROM activity WHERE user_id = ? ORDER BY id DESC LIMIT ?
              )
            """,
            (user_id, user_id, KEEP),
        )

    if conn is not None:
        _write(conn)
        return
    with get_db() as c:
        _write(c)


def list_activity(user_id: int, limit: int = SHOW) -> list[dict[str, Any]]:
    limit = max(1, min(500, int(limit)))
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT activity.id, activity.created_at, activity.action, activity.summary,
                   activity.card_id, activity.deck_id, activity.foil,
                   cards.card_code, cards.name, cards.image_path, cards.rarity
            FROM activity
            LEFT JOIN cards ON cards.id = activity.card_id
            WHERE activity.user_id = ?
            ORDER BY activity.id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["foil"] = bool(row["foil"])
        path = row["image_path"]
        item["image_url"] = "/images/" + str(path).replace("\\", "/") if path else None
        items.append(item)
    return items


def card_label(card_id: int | None, conn=None) -> str:
    if conn is not None:
        return _label(conn, card_id)
    with get_db() as c:
        return _label(c, card_id)


def deck_label(deck_id: int | None, conn=None) -> str:
    if conn is not None:
        return _deck_name(conn, deck_id)
    with get_db() as c:
        return _deck_name(c, deck_id)
