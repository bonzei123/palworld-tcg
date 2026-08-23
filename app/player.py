from __future__ import annotations

import csv
import io
from collections import Counter
from typing import Any

from .db import get_db, row_to_card

CARD_SELECT = """
SELECT cards.*, editions.code AS edition_code, editions.name AS edition_name
FROM cards
LEFT JOIN editions ON editions.id = cards.edition_id
"""


def collection_map(user_id: int) -> dict[int, dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT card_id, owned, wanted,
                   IFNULL(condition, 'NM') AS condition,
                   IFNULL(location, '') AS location,
                   IFNULL(for_trade, 0) AS for_trade,
                   IFNULL(notes, '') AS notes
            FROM collection WHERE user_id = ?
            """,
            (user_id,),
        ).fetchall()
    return {
        int(r["card_id"]): {
            "owned": int(r["owned"]),
            "wanted": int(r["wanted"]),
            "condition": r["condition"] or "NM",
            "location": r["location"] or "",
            "for_trade": bool(r["for_trade"]),
            "notes": r["notes"] or "",
        }
        for r in rows
    }


def attach_collection(items: list[dict[str, Any]], user_id: int | None) -> list[dict[str, Any]]:
    if not user_id or not items:
        for item in items:
            item.setdefault("owned", 0)
            item.setdefault("wanted", 0)
            item.setdefault("condition", "NM")
            item.setdefault("location", "")
            item.setdefault("for_trade", False)
        return items
    cmap = collection_map(user_id)
    for item in items:
        rec = cmap.get(item["id"], {"owned": 0, "wanted": 0, "condition": "NM", "location": "", "for_trade": False, "notes": ""})
        item.update(rec)
    return items


def set_collection(
    user_id: int,
    card_id: int,
    owned: int | None,
    wanted: int | None,
    *,
    condition: str | None = None,
    location: str | None = None,
    for_trade: bool | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    cmap = collection_map(user_id)
    prev = cmap.get(card_id, {"owned": 0, "wanted": 0, "condition": "NM", "location": "", "for_trade": False, "notes": ""})
    owned_n = max(0, min(99, int(owned if owned is not None else prev["owned"])))
    wanted_n = max(0, min(99, int(wanted if wanted is not None else prev["wanted"])))
    cond = (condition if condition is not None else prev["condition"]) or "NM"
    if cond not in {"NM", "LP", "MP", "HP", "Played"}:
        cond = "NM"
    loc = (location if location is not None else prev["location"]) or ""
    loc = loc.strip()[:80]
    trade = prev["for_trade"] if for_trade is None else bool(for_trade)
    note = (notes if notes is not None else prev["notes"]) or ""
    note = note.strip()[:500]
    with get_db() as conn:
        exists = conn.execute("SELECT id FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not exists:
            raise KeyError("card")
        if owned_n == 0 and wanted_n == 0 and not trade and not loc and not note:
            conn.execute(
                "DELETE FROM collection WHERE user_id = ? AND card_id = ?",
                (user_id, card_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO collection(user_id, card_id, owned, wanted, condition, location, for_trade, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, card_id) DO UPDATE SET
                    owned = excluded.owned,
                    wanted = excluded.wanted,
                    condition = excluded.condition,
                    location = excluded.location,
                    for_trade = excluded.for_trade,
                    notes = excluded.notes
                """,
                (user_id, card_id, owned_n, wanted_n, cond, loc, int(trade), note),
            )
    return {
        "owned": owned_n,
        "wanted": wanted_n,
        "condition": cond,
        "location": loc,
        "for_trade": trade,
        "notes": note,
    }


def collection_rows(user_id: int, status: str = "") -> list[dict[str, Any]]:
    sql = """
        SELECT cards.*, editions.code AS edition_code, editions.name AS edition_name,
               collection.owned AS owned, collection.wanted AS wanted,
               IFNULL(collection.condition, 'NM') AS condition,
               IFNULL(collection.location, '') AS location,
               IFNULL(collection.for_trade, 0) AS for_trade,
               IFNULL(collection.notes, '') AS notes
        FROM collection
        JOIN cards ON cards.id = collection.card_id
        LEFT JOIN editions ON editions.id = cards.edition_id
        WHERE collection.user_id = ?
    """
    params: list[Any] = [user_id]
    if status == "have":
        sql += " AND collection.owned > 0"
    elif status == "need":
        sql += " AND collection.wanted > 0"
    elif status == "missing":
        sql += " AND collection.wanted > collection.owned"
    sql += " ORDER BY editions.code, cards.card_code, cards.rarity"
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    items = []
    for row in rows:
        card = row_to_card(row)
        card["owned"] = int(row["owned"] or 0)
        card["wanted"] = int(row["wanted"] or 0)
        card["condition"] = row["condition"] or "NM"
        card["location"] = row["location"] or ""
        card["for_trade"] = bool(row["for_trade"])
        card["notes"] = row["notes"] or ""
        items.append(card)
    from .game import attach_flags

    return attach_flags(items)


def collection_summary(user_id: int) -> dict[str, int]:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS rows,
                IFNULL(SUM(owned), 0) AS owned,
                IFNULL(SUM(wanted), 0) AS wanted,
                SUM(CASE WHEN owned > 0 THEN 1 ELSE 0 END) AS have,
                SUM(CASE WHEN wanted > owned THEN 1 ELSE 0 END) AS missing
            FROM collection WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
    return {k: int(row[k] or 0) for k in ("rows", "owned", "wanted", "have", "missing")}


def export_collection_csv(user_id: int) -> str:
    rows = collection_rows(user_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "card_code",
            "name",
            "rarity",
            "edition",
            "owned",
            "wanted",
            "have",
            "need",
            "condition",
            "location",
            "for_trade",
            "notes",
            "price_cents",
        ]
    )
    for c in rows:
        writer.writerow(
            [
                c.get("card_code"),
                c.get("name"),
                c.get("rarity"),
                c.get("edition_code"),
                c.get("owned", 0),
                c.get("wanted", 0),
                "ja" if c.get("owned", 0) > 0 else "nein",
                "ja" if c.get("wanted", 0) > c.get("owned", 0) else "nein",
                c.get("condition") or "NM",
                c.get("location") or "",
                "ja" if c.get("for_trade") else "nein",
                c.get("notes") or "",
                c.get("price_cents") or "",
            ]
        )
    return buf.getvalue()


def export_collection_json(user_id: int) -> list[dict[str, Any]]:
    rows = collection_rows(user_id)
    return [
        {
            "card_code": c.get("card_code"),
            "name": c.get("name"),
            "rarity": c.get("rarity"),
            "edition": c.get("edition_code"),
            "owned": c.get("owned", 0),
            "wanted": c.get("wanted", 0),
            "have": (c.get("owned") or 0) > 0,
            "need": (c.get("wanted") or 0) > (c.get("owned") or 0),
            "condition": c.get("condition") or "NM",
            "location": c.get("location") or "",
            "for_trade": bool(c.get("for_trade")),
            "notes": c.get("notes") or "",
            "price_cents": c.get("price_cents"),
        }
        for c in rows
    ]


def list_decks(user_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT decks.*, IFNULL(SUM(deck_cards.qty), 0) AS cards
            FROM decks
            LEFT JOIN deck_cards ON deck_cards.deck_id = decks.id
            WHERE decks.user_id = ?
            GROUP BY decks.id
            ORDER BY decks.updated_at DESC
            """,
            (user_id,),
        ).fetchall()
    decks = [dict(r) for r in rows]
    for deck in decks:
        full = get_deck(user_id, int(deck["id"]))
        analysis = (full or {}).get("analysis") or {}
        deck["can_build"] = bool(analysis.get("can_build"))
        deck["legal"] = bool(analysis.get("legal", True))
    return decks


def get_deck(user_id: int, deck_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        deck = conn.execute(
            "SELECT * FROM decks WHERE id = ? AND user_id = ?",
            (deck_id, user_id),
        ).fetchone()
        if not deck:
            return None
        rows = conn.execute(
            f"""
            {CARD_SELECT}
            JOIN deck_cards ON deck_cards.card_id = cards.id
            WHERE deck_cards.deck_id = ?
            ORDER BY cards.cost, cards.card_code
            """,
            (deck_id,),
        ).fetchall()
        qty = {
            r["card_id"]: int(r["qty"])
            for r in conn.execute(
                "SELECT card_id, qty FROM deck_cards WHERE deck_id = ?", (deck_id,)
            ).fetchall()
        }
    from .game import analyze_deck, attach_flags

    cards = []
    for row in rows:
        card = row_to_card(row)
        card["qty"] = qty.get(card["id"], 1)
        cards.append(card)
    attach_flags(cards)
    attach_collection(cards, user_id)
    data = dict(deck)
    data["cards"] = cards
    data["analysis"] = analyze_deck(cards, user_id)
    return data


def create_deck(user_id: int, name: str) -> int:
    name = (name or "").strip() or "Neues Deck"
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO decks(user_id, name) VALUES (?, ?)",
            (user_id, name[:80]),
        )
        return int(cur.lastrowid)


def rename_deck(user_id: int, deck_id: int, name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE decks SET name = ?, updated_at = datetime('now') WHERE id = ? AND user_id = ?",
            (name[:80], deck_id, user_id),
        )
        return cur.rowcount > 0


def delete_deck(user_id: int, deck_id: int) -> bool:
    with get_db() as conn:
        owned = conn.execute(
            "SELECT id FROM decks WHERE id = ? AND user_id = ?",
            (deck_id, user_id),
        ).fetchone()
        if not owned:
            return False
        conn.execute("DELETE FROM deck_cards WHERE deck_id = ?", (deck_id,))
        conn.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
        return True


def set_deck_card(user_id: int, deck_id: int, card_id: int, qty: int) -> dict[str, Any] | None:
    qty = max(0, min(99, int(qty)))
    with get_db() as conn:
        owned = conn.execute(
            "SELECT id FROM decks WHERE id = ? AND user_id = ?",
            (deck_id, user_id),
        ).fetchone()
        if not owned:
            return None
        if not conn.execute("SELECT id FROM cards WHERE id = ?", (card_id,)).fetchone():
            raise KeyError("card")
        if qty <= 0:
            conn.execute(
                "DELETE FROM deck_cards WHERE deck_id = ? AND card_id = ?",
                (deck_id, card_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO deck_cards(deck_id, card_id, qty) VALUES (?, ?, ?)
                ON CONFLICT(deck_id, card_id) DO UPDATE SET qty = excluded.qty
                """,
                (deck_id, card_id, qty),
            )
        conn.execute(
            "UPDATE decks SET updated_at = datetime('now') WHERE id = ?",
            (deck_id,),
        )
    return get_deck(user_id, deck_id)


def analyze_deck(cards: list[dict[str, Any]], user_id: int | None = None) -> dict[str, Any]:
    from .game import analyze_deck as game_analyze

    return game_analyze(cards, user_id)


def printings_for(card_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT name, card_code FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not row:
            return []
        rows = conn.execute(
            f"""
            {CARD_SELECT}
            WHERE cards.name = ? OR cards.card_code = ?
            ORDER BY cards.rarity, cards.card_code
            """,
            (row["name"], row["card_code"]),
        ).fetchall()
    return [row_to_card(r) for r in rows]
