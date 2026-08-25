from __future__ import annotations

import json
import random
import re
import sqlite3
from collections import Counter, defaultdict
from typing import Any

from .db import get_db, get_setting, row_to_card, set_setting

CARD_SELECT = """
SELECT cards.*, editions.code AS edition_code, editions.name AS edition_name
FROM cards
LEFT JOIN editions ON editions.id = cards.edition_id
"""

CONDITIONS = ("NM", "LP", "MP", "HP", "Played")
TAG_PRESETS = ("Staple", "Tech", "Bulk", "Trade", "Pet")
CODE_BASE_RE = re.compile(r"^([A-Z0-9]+-\d+)", re.I)
PAL_SPLIT_RE = re.compile(r"\s+[–—-]\s+")


def base_code(code: str | None) -> str:
    raw = (code or "").strip().upper()
    m = CODE_BASE_RE.match(raw)
    return m.group(1) if m else raw


def pal_line(name: str | None) -> str:
    text = (name or "").strip()
    if not text:
        return ""
    parts = PAL_SPLIT_RE.split(text, maxsplit=1)
    return parts[0].strip()


COLORLESS = {"", "colorless", "farblos", "none", "null", "-", "—"}


def is_soul(card: dict[str, Any]) -> bool:
    kind = (card.get("card_type") or "").strip().lower()
    name = (card.get("name") or "").strip().lower()
    return kind == "soul" or name == "soul"


def is_colorless(color: str | None) -> bool:
    return (color or "").strip().casefold() in COLORLESS


def copy_limit(card: dict[str, Any]) -> int:
    if is_soul(card):
        return 10
    kind = (card.get("card_type") or "").strip().lower()
    if kind == "energy":
        return 99
    return 4


def is_lucky(card: dict[str, Any]) -> bool:
    blob = f"{card.get('subtype') or ''} {card.get('card_type') or ''}".lower()
    return "lucky" in blob or "partner" in blob


def banned_codes(conn=None) -> set[str]:
    def read(c) -> set[str]:
        raw = get_setting(c, "banned_codes") or ""
        codes = {base_code(x) for x in raw.replace(",", "\n").split() if x.strip()}
        extra = []
        try:
            extra = c.execute(
                "SELECT card_code FROM cards WHERE IFNULL(banned, 0) = 1"
            ).fetchall()
        except sqlite3.OperationalError:
            extra = []
        codes.update(base_code(r["card_code"]) for r in extra)
        return {c for c in codes if c}

    if conn is not None:
        return read(conn)
    with get_db() as c:
        return read(c)


def errata_text() -> str:
    with get_db() as conn:
        row = conn.execute("SELECT text FROM errata WHERE id = 1").fetchone()
    return (row["text"] or "") if row else ""


def errata_excerpt(card: dict[str, Any], errata: str | None = None) -> str:
    errata = errata if errata is not None else errata_text()
    if not errata:
        return ""
    needles = []
    full = (card.get("card_code") or "").strip()
    code = base_code(card.get("card_code"))
    name = (card.get("name") or "").strip()
    if full:
        needles.append(full)
    if code and code.casefold() != full.casefold():
        needles.append(code)
    if name:
        needles.append(name)
    lower = errata.casefold()
    idx = -1
    matched_len = 0
    for needle in needles:
        if not needle:
            continue
        pos = lower.find(needle.casefold())
        if pos >= 0:
            idx = pos
            matched_len = len(needle)
            break
    if idx < 0:
        return ""
    start = errata.rfind("\n\n", 0, idx)
    start = 0 if start < 0 else start + 2
    end = errata.find("\n\n", idx + matched_len)
    if end < 0:
        end = min(len(errata), idx + 700)
    snippet = errata[start:end].strip()
    if len(snippet) > 900:
        snippet = snippet[:900].rsplit(" ", 1)[0] + "…"
    return snippet


def card_flags(card: dict[str, Any], banned: set[str] | None = None, errata: str | None = None) -> dict[str, Any]:
    banned = banned if banned is not None else banned_codes()
    errata = errata if errata is not None else errata_text()
    code = base_code(card.get("card_code"))
    full = (card.get("card_code") or "").upper()
    hay = errata.upper()
    has_errata = bool(errata and (code in hay or full in hay or (card.get("name") or "").upper() in hay))
    return {
        "banned": code in banned or bool(card.get("banned")),
        "has_errata": has_errata,
        "base_code": code,
        "pal_line": pal_line(card.get("name")),
        "copy_limit": copy_limit(card),
    }


def attach_flags(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        return items
    banned = banned_codes()
    errata = errata_text()
    for item in items:
        item.update(card_flags(item, banned, errata))
    return items


def save_banlist(text: str) -> None:
    lines = [base_code(x) for x in text.replace(",", "\n").splitlines() if x.strip()]
    with get_db() as conn:
        set_setting(conn, "banned_codes", "\n".join(dict.fromkeys(lines)))


def pal_family(card_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT name FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not row:
            return []
        line = pal_line(row["name"])
        if not line:
            return []
        rows = conn.execute(
            f"""
            {CARD_SELECT}
            WHERE cards.name = ?
               OR cards.name LIKE ?
               OR cards.name LIKE ?
               OR cards.name LIKE ?
            ORDER BY editions.code, cards.card_code, cards.rarity
            """,
            (line, f"{line} –%", f"{line} —%", f"{line} -%"),
        ).fetchall()
    return attach_flags([row_to_card(r) for r in rows])


def owned_by_base(user_id: int) -> dict[str, int]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT cards.card_code, collection.owned
            FROM collection
            JOIN cards ON cards.id = collection.card_id
            WHERE collection.user_id = ? AND collection.owned > 0
            """,
            (user_id,),
        ).fetchall()
    totals: dict[str, int] = defaultdict(int)
    for row in rows:
        totals[base_code(row["card_code"])] += int(row["owned"] or 0)
    return dict(totals)


def analyze_deck(cards: list[dict[str, Any]], user_id: int | None = None) -> dict[str, Any]:
    colors: Counter[str] = Counter()
    costs: Counter[int] = Counter()
    by_base: Counter[str] = Counter()
    total = 0
    souls = 0
    lucky_names: set[str] = set()
    banned = banned_codes()
    errata = errata_text()
    owned = owned_by_base(user_id) if user_id else {}
    missing: list[dict[str, Any]] = []
    illegal: list[str] = []

    for card in cards:
        qty = int(card.get("qty") or 0)
        flags = card_flags(card, banned, errata)
        card.update(flags)
        soul = is_soul(card)
        card["is_soul"] = soul
        color = (card.get("color") or "").strip() or "Colorless"
        if soul:
            souls += qty
        else:
            total += qty
            colors[color] += qty
            cost = card.get("cost")
            bucket = 10 if cost is None or cost >= 10 else max(0, int(cost))
            costs[bucket] += qty
        code = flags["base_code"]
        by_base[code] += qty
        if is_lucky(card):
            lucky_names.add(pal_line(card.get("name")) or card.get("name") or code)
        have = owned.get(code, 0)
        need = qty
        card["owned_base"] = have
        card["can_play"] = have >= need
        if have < need:
            missing.append(
                {
                    "card_id": card.get("id"),
                    "card_code": card.get("card_code"),
                    "name": card.get("name"),
                    "need": need - have,
                    "have": have,
                }
            )
        limit = flags["copy_limit"]
        if qty > limit:
            illegal.append(f"{card.get('card_code')}: {qty}/{limit} Kopien")
            card["illegal"] = True
        elif flags["banned"]:
            illegal.append(f"{card.get('card_code')}: gebannt")
            card["illegal"] = True
        else:
            card["illegal"] = False

    for code, n in by_base.items():
        sample = next((c for c in cards if base_code(c.get("card_code")) == code), None)
        limit = copy_limit(sample or {})
        if n > limit:
            illegal.append(f"{code}: {n} Kopien über alle Drucke (max. {limit})")

    chromatic = [name for name in colors if not is_colorless(name)]
    warnings: list[str] = []
    if total and total < 50:
        warnings.append(f"Nur {total} Karten im Deck — Palworld-Decks sind 50 Karten plus 10 Souls.")
    if total > 50:
        warnings.append(f"{total} Karten im Deck — über dem 50er-Limit (Souls zählen extra).")
        illegal.append("Mehr als 50 Karten im Hauptdeck")
    if souls != 10:
        warnings.append(f"Soul-Stack: {souls} / 10.")
    if souls > 10:
        illegal.append("Mehr als 10 Souls")
    if len(chromatic) > 2:
        warnings.append("Maximal zwei Farben plus Colorless.")
        illegal.append("Mehr als zwei Farben (Colorless zählt nicht)")
    if len(lucky_names) > 1:
        warnings.append("Mehrere Lucky/Partner-Pals: " + ", ".join(sorted(lucky_names)))

    can_build = not missing and total > 0
    curve = [{"cost": i, "count": int(costs.get(i, 0))} for i in range(0, 11)]
    color_rows = [
        {"color": name, "count": n, "share": round(100 * n / total, 1) if total else 0}
        for name, n in colors.most_common()
    ]
    return {
        "total": total,
        "curve": curve,
        "colors": color_rows,
        "warnings": warnings,
        "illegal": illegal,
        "missing": missing,
        "can_build": can_build,
        "souls": souls,
        "lucky_pals": sorted(lucky_names),
        "color_ok": len(chromatic) <= 2,
        "legal": not illegal,
    }


def set_progress(user_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        editions = conn.execute("SELECT id, code, name FROM editions ORDER BY code").fetchall()
        owned_ids = {
            int(r["card_id"])
            for r in conn.execute(
                "SELECT DISTINCT card_id FROM collection WHERE user_id = ? AND owned > 0",
                (user_id,),
            ).fetchall()
        }
        copies = {
            int(r["edition_id"]): int(r["n"] or 0)
            for r in conn.execute(
                """
                SELECT cards.edition_id, SUM(collection.owned) AS n
                FROM collection
                JOIN cards ON cards.id = collection.card_id
                WHERE collection.user_id = ? AND collection.owned > 0
                  AND cards.edition_id IS NOT NULL
                GROUP BY cards.edition_id
                """,
                (user_id,),
            ).fetchall()
        }
        rows = conn.execute(
            """
            SELECT cards.id, cards.card_code, cards.name, cards.rarity, cards.price_cents,
                   cards.edition_id, editions.code AS edition_code
            FROM cards
            LEFT JOIN editions ON editions.id = cards.edition_id
            """
        ).fetchall()
    by_ed: dict[int, dict[str, Any]] = {}
    for ed in editions:
        by_ed[int(ed["id"])] = {
            "code": ed["code"],
            "name": ed["name"],
            "total": 0,
            "have": 0,
            "copies": copies.get(int(ed["id"]), 0),
            "missing": 0,
            "gaps": [],
        }
    for row in rows:
        eid = row["edition_id"]
        if eid not in by_ed:
            continue
        bucket = by_ed[eid]
        bucket["total"] += 1
        if int(row["id"]) in owned_ids:
            bucket["have"] += 1
        else:
            bucket["missing"] += 1
            if len(bucket["gaps"]) < 8:
                bucket["gaps"].append(
                    {
                        "id": row["id"],
                        "card_code": row["card_code"],
                        "name": row["name"],
                        "rarity": row["rarity"],
                        "price_cents": row["price_cents"],
                    }
                )
    out = []
    for bucket in by_ed.values():
        if not bucket["total"]:
            continue
        bucket["gaps"].sort(key=lambda g: int(g.get("price_cents") or 0), reverse=True)
        out.append(bucket)
    return out


def collection_value(user_id: int) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT IFNULL(SUM(collection.owned * IFNULL(cards.price_cents, 0)), 0) AS cents,
                   SUM(CASE WHEN cards.price_cents IS NOT NULL THEN collection.owned ELSE 0 END) AS priced
            FROM collection
            JOIN cards ON cards.id = collection.card_id
            WHERE collection.user_id = ? AND collection.owned > 0
            """,
            (user_id,),
        ).fetchone()
    return {"cents": int(row["cents"] or 0), "priced": int(row["priced"] or 0)}


def expensive_gaps(user_id: int, limit: int = 12) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            f"""
            {CARD_SELECT}
            WHERE IFNULL(cards.price_cents, 0) > 0
              AND cards.id NOT IN (
                  SELECT card_id FROM collection WHERE user_id = ? AND owned > 0
              )
            ORDER BY cards.price_cents DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [row_to_card(r) for r in rows]


def trade_board(user_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        users = conn.execute(
            "SELECT id, username FROM users WHERE id != ? ORDER BY username",
            (user_id,),
        ).fetchall()
        mine_want = {
            int(r["card_id"])
            for r in conn.execute(
                "SELECT card_id FROM collection WHERE user_id = ? AND wanted > IFNULL(owned, 0)",
                (user_id,),
            ).fetchall()
        }
        mine_trade = {
            int(r["id"]): row_to_card(r)
            for r in conn.execute(
                f"""
                {CARD_SELECT}
                JOIN collection ON collection.card_id = cards.id
                WHERE collection.user_id = ? AND IFNULL(collection.for_trade, 0) = 1 AND collection.owned > 0
                """,
                (user_id,),
            ).fetchall()
        }
        board = []
        for other in users:
            oid = int(other["id"])
            their_trade = conn.execute(
                """
                SELECT cards.*, editions.code AS edition_code, editions.name AS edition_name
                FROM cards
                LEFT JOIN editions ON editions.id = cards.edition_id
                JOIN collection ON collection.card_id = cards.id
                WHERE collection.user_id = ? AND IFNULL(collection.for_trade, 0) = 1 AND collection.owned > 0
                """,
                (oid,),
            ).fetchall()
            their_want = {
                int(r["card_id"])
                for r in conn.execute(
                    "SELECT card_id FROM collection WHERE user_id = ? AND wanted > IFNULL(owned, 0)",
                    (oid,),
                ).fetchall()
            }
            offers = [row_to_card(r) for r in their_trade if int(r["id"]) in mine_want]
            wants = [card for cid, card in mine_trade.items() if cid in their_want]
            if offers or wants:
                board.append(
                    {
                        "user_id": oid,
                        "username": other["username"],
                        "they_offer": offers,
                        "they_want": wants,
                    }
                )
    return board


def add_pull(
    user_id: int,
    card_id: int,
    source: str,
    qty: int = 1,
    *,
    increment: bool = True,
    foil: Any = 0,
) -> dict[str, Any]:
    from .player import as_foil

    qty = max(1, min(36, int(qty)))
    source = (source or "").strip()[:80] or "Display"
    foil_n = as_foil(foil)
    with get_db() as conn:
        if not conn.execute("SELECT id FROM cards WHERE id = ?", (card_id,)).fetchone():
            raise KeyError("card")
        conn.execute(
            "INSERT INTO pulls(user_id, card_id, source, qty, foil) VALUES (?, ?, ?, ?, ?)",
            (user_id, card_id, source, qty, foil_n),
        )
        row = conn.execute(
            "SELECT owned, wanted FROM collection WHERE user_id = ? AND card_id = ? AND foil = ?",
            (user_id, card_id, foil_n),
        ).fetchone()
        owned = int(row["owned"] if row else 0)
        wanted = int(row["wanted"] if row else 0)
        if increment:
            owned += qty
            conn.execute(
                """
                INSERT INTO collection(user_id, card_id, foil, owned, wanted)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, card_id, foil) DO UPDATE SET owned = excluded.owned
                """,
                (user_id, card_id, foil_n, owned, wanted),
            )
    return {"ok": True, "owned": owned, "source": source, "foil": bool(foil_n)}


def list_pulls(user_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT pulls.id, pulls.source, pulls.qty, pulls.created_at,
                   IFNULL(pulls.foil, 0) AS foil,
                   cards.id AS card_id, cards.card_code, cards.name, cards.rarity,
                   cards.image_path
            FROM pulls
            JOIN cards ON cards.id = pulls.card_id
            WHERE pulls.user_id = ?
            ORDER BY pulls.id DESC
            LIMIT 80
            """,
            (user_id,),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["foil"] = bool(row["foil"])
        item["image_url"] = "/images/" + row["image_path"].replace("\\", "/") if row["image_path"] else None
        items.append(item)
    return items


def user_notes(user_id: int, card_id: int) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT notes, tags FROM card_notes WHERE user_id = ? AND card_id = ?",
            (user_id, card_id),
        ).fetchone()
    if not row:
        return {"notes": "", "tags": []}
    try:
        tags = json.loads(row["tags"] or "[]")
    except json.JSONDecodeError:
        tags = []
    return {"notes": row["notes"] or "", "tags": tags}


def save_notes(user_id: int, card_id: int, notes: str, tags: list[str]) -> dict[str, Any]:
    notes = (notes or "").strip()[:2000]
    clean = [t.strip()[:24] for t in tags if str(t).strip()][:8]
    blob = json.dumps(clean, ensure_ascii=False)
    with get_db() as conn:
        if not notes and not clean:
            conn.execute(
                "DELETE FROM card_notes WHERE user_id = ? AND card_id = ?",
                (user_id, card_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO card_notes(user_id, card_id, notes, tags)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, card_id) DO UPDATE SET
                    notes = excluded.notes, tags = excluded.tags
                """,
                (user_id, card_id, notes, blob),
            )
    return {"notes": notes, "tags": clean}


def find_by_code(query: str) -> list[dict[str, Any]]:
    q = (query or "").strip().upper()
    if not q:
        return []
    like = f"%{q}%"
    with get_db() as conn:
        rows = conn.execute(
            f"""
            {CARD_SELECT}
            WHERE UPPER(cards.card_code) = ?
               OR UPPER(cards.card_code) LIKE ?
               OR REPLACE(UPPER(cards.card_code), '-', '') = REPLACE(?, '-', '')
            ORDER BY cards.card_code, cards.rarity
            LIMIT 24
            """,
            (q, like, q),
        ).fetchall()
    return attach_flags([row_to_card(r) for r in rows])


def random_booster(edition: str | None = None, count: int = 10) -> dict[str, Any]:
    with get_db() as conn:
        editions = [r["code"] for r in conn.execute("SELECT code FROM editions ORDER BY code").fetchall()]
        code = (edition or "").strip().upper() or (editions[0] if editions else "")
        params: list[Any] = []
        sql = f"{CARD_SELECT} WHERE cards.image_path IS NOT NULL AND cards.image_path != ''"
        if code:
            sql += " AND editions.code = ?"
            params.append(code)
        rows = conn.execute(sql, params).fetchall()
    pool = [row_to_card(r) for r in rows]
    if not pool:
        with get_db() as conn:
            sql = CARD_SELECT
            params = []
            if code:
                sql += " WHERE editions.code = ?"
                params.append(code)
            pool = [row_to_card(r) for r in conn.execute(sql, params).fetchall()]
    random.shuffle(pool)
    rares = [c for c in pool if (c.get("rarity") or "").upper() in {"RR", "SR", "OSR", "SSP", "SP", "SAR"}]
    rest = [c for c in pool if c not in rares]
    pack: list[dict[str, Any]] = []
    if rares:
        pack.append(rares[0])
    pack.extend(rest[: max(0, count - len(pack))])
    if len(pack) < count:
        pack.extend(pool[: count - len(pack)])
    return {"edition": code, "editions": editions, "cards": attach_flags(pack[:count])}


def deck_text(deck: dict[str, Any]) -> str:
    lines = [f"# {deck.get('name') or 'Deck'}"]
    for card in deck.get("cards") or []:
        foil = " (Foil)" if card.get("foil") else ""
        lines.append(f"{card.get('qty') or 1} {card.get('card_code')} {card.get('name')}{foil}")
    return "\n".join(lines) + "\n"


def parse_deck_text(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, str | int | bool]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        foil = bool(re.search(r"\(foil\)|\*foil\*|✦", line, re.I))
        line = re.sub(r"\s*(\(foil\)|\*foil\*)\s*", " ", line, flags=re.I).strip()
        m = re.match(r"^(?:(\d+)\s*[x×]?\s+)?([A-Z0-9]+-\d+[A-Z]*)(?:\s+.*)?$", line, re.I)
        if m:
            items.append({"qty": int(m.group(1) or 1), "card_code": m.group(2).upper(), "foil": foil})
            continue
        m = re.match(r"^(\d+)\s+(.+)$", line)
        if m:
            items.append({"qty": int(m.group(1)), "name": m.group(2).strip(), "foil": foil})
    return items


def apply_deck_import(user_id: int, deck_id: int, items: list[dict[str, Any]]) -> None:
    with get_db() as conn:
        owned = conn.execute(
            "SELECT id FROM decks WHERE id = ? AND user_id = ?",
            (deck_id, user_id),
        ).fetchone()
        if not owned:
            raise KeyError("deck")
        conn.execute("DELETE FROM deck_cards WHERE deck_id = ?", (deck_id,))
        for item in items:
            row = None
            if item.get("card_code"):
                row = conn.execute(
                    "SELECT id FROM cards WHERE UPPER(card_code) = ? ORDER BY id LIMIT 1",
                    (str(item["card_code"]).upper(),),
                ).fetchone()
            if not row and item.get("name"):
                row = conn.execute(
                    "SELECT id FROM cards WHERE LOWER(name) = LOWER(?) ORDER BY id LIMIT 1",
                    (item["name"],),
                ).fetchone()
            if not row:
                continue
            qty = max(1, min(99, int(item.get("qty") or 1)))
            foil = 1 if item.get("foil") else 0
            conn.execute(
                """
                INSERT INTO deck_cards(deck_id, card_id, foil, qty) VALUES (?, ?, ?, ?)
                ON CONFLICT(deck_id, card_id, foil) DO UPDATE SET qty = qty + excluded.qty
                """,
                (deck_id, int(row["id"]), foil, qty),
            )
        conn.execute("UPDATE decks SET updated_at = datetime('now') WHERE id = ?", (deck_id,))
