from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from pathlib import Path

from .config import DB_PATH, IMAGES_DIR, ensure_dirs
from .image_meta import is_landscape

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS editions (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY,
    official_id INTEGER UNIQUE,
    card_code TEXT NOT NULL,
    name TEXT NOT NULL,
    rarity TEXT NOT NULL DEFAULT '',
    card_type TEXT,
    subtype TEXT,
    color TEXT,
    attributes TEXT NOT NULL DEFAULT '[]',
    aptitudes TEXT NOT NULL DEFAULT '[]',
    cost INTEGER,
    power INTEGER,
    strike INTEGER,
    effect TEXT,
    image_path TEXT,
    image_url TEXT,
    landscape INTEGER,
    source_url TEXT,
    edition_id INTEGER REFERENCES editions(id),
    search_blob TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(card_code, rarity)
);

CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name);
CREATE INDEX IF NOT EXISTS idx_cards_type ON cards(card_type);
CREATE INDEX IF NOT EXISTS idx_cards_color ON cards(color);
CREATE INDEX IF NOT EXISTS idx_cards_rarity ON cards(rarity);
CREATE INDEX IF NOT EXISTS idx_cards_edition ON cards(edition_id);
CREATE INDEX IF NOT EXISTS idx_cards_code ON cards(card_code);

CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
    name,
    card_code,
    rarity,
    card_type,
    subtype,
    color,
    attributes,
    aptitudes,
    effect,
    search_blob,
    content='cards',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    filename TEXT,
    stored_path TEXT,
    text TEXT,
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS cards_ai AFTER INSERT ON cards BEGIN
    INSERT INTO cards_fts(
        rowid, name, card_code, rarity, card_type, subtype, color,
        attributes, aptitudes, effect, search_blob
    ) VALUES (
        new.id, new.name, new.card_code, new.rarity, new.card_type, new.subtype,
        new.color, new.attributes, new.aptitudes, new.effect, new.search_blob
    );
END;

CREATE TRIGGER IF NOT EXISTS cards_ad AFTER DELETE ON cards BEGIN
    INSERT INTO cards_fts(cards_fts, rowid, name, card_code, rarity, card_type, subtype, color,
        attributes, aptitudes, effect, search_blob)
    VALUES (
        'delete', old.id, old.name, old.card_code, old.rarity, old.card_type, old.subtype,
        old.color, old.attributes, old.aptitudes, old.effect, old.search_blob
    );
END;

CREATE TRIGGER IF NOT EXISTS cards_au AFTER UPDATE ON cards BEGIN
    INSERT INTO cards_fts(cards_fts, rowid, name, card_code, rarity, card_type, subtype, color,
        attributes, aptitudes, effect, search_blob)
    VALUES (
        'delete', old.id, old.name, old.card_code, old.rarity, old.card_type, old.subtype,
        old.color, old.attributes, old.aptitudes, old.effect, old.search_blob
    );
    INSERT INTO cards_fts(
        rowid, name, card_code, rarity, card_type, subtype, color,
        attributes, aptitudes, effect, search_blob
    ) VALUES (
        new.id, new.name, new.card_code, new.rarity, new.card_type, new.subtype,
        new.color, new.attributes, new.aptitudes, new.effect, new.search_blob
    );
END;
"""


def connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row_to_card(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for key in ("attributes", "aptitudes"):
        raw = data.get(key) or "[]"
        try:
            data[key] = json.loads(raw)
        except json.JSONDecodeError:
            data[key] = []
    data["remote_image_url"] = data.get("image_url")
    if data.get("image_path"):
        data["image_url"] = "/images/" + str(data["image_path"]).replace("\\", "/")
    else:
        data["image_url"] = None
    code = data.get("card_code") or data.get("card_code")
    data["card_code"] = code
    data["card_code"] = code
    data["image_url"] = data.get("image_url")
    data["card_type"] = data.get("card_type") or data.get("card_type")
    data["edition_code"] = data.get("edition_code") or data.get("edition_code")
    data["landscape"] = bool(int(data["landscape"] or 0)) if data.get("landscape") is not None else False
    data["banned"] = bool(int(data.get("banned") or 0))
    data["price_cents"] = data.get("price_cents")
    chart = []
    for label, key in (
        ("30T", "price_30d_cents"),
        ("7T", "price_7d_cents"),
        ("3T", "price_3d_cents"),
        ("Jetzt", "price_cents"),
    ):
        raw = data.get(key)
        if raw is None or raw == "":
            continue
        try:
            chart.append((label, int(raw)))
        except (TypeError, ValueError):
            continue
    data["price_chart_labels"] = ",".join(p[0] for p in chart)
    data["price_chart_cents"] = ",".join(str(p[1]) for p in chart)
    return data


def landscape_flag(rel: str | None) -> int:
    if not rel:
        return 0
    return int(is_landscape(IMAGES_DIR / Path(rel)))


def set_card_landscape(conn: sqlite3.Connection, card_id: int, rel: str | None) -> int:
    flag = landscape_flag(rel)
    conn.execute("UPDATE cards SET landscape = ? WHERE id = ?", (flag, card_id))
    return flag


def refresh_landscapes(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT id, image_path FROM cards WHERE image_path IS NOT NULL AND image_path != ''"
    ).fetchall()
    for row in rows:
        set_card_landscape(conn, row["id"], row["image_path"])
    return len(rows)


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return default if row is None else row["value"]


def set_setting(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    if value is None:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        return
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def upsert_edition(conn: sqlite3.Connection, code: str, name: str | None = None) -> int:
    existing = conn.execute("SELECT id, name FROM editions WHERE code = ?", (code,)).fetchone()
    if existing:
        if name and name != existing["name"] and name != code:
            conn.execute("UPDATE editions SET name = ? WHERE id = ?", (name, existing["id"]))
        return int(existing["id"])
    cur = conn.execute("INSERT INTO editions(code, name) VALUES (?, ?)", (code, name or code))
    return int(cur.lastrowid)


def upsert_card(conn: sqlite3.Connection, card: dict[str, Any]) -> tuple[int, str]:
    sparse = bool(card.pop("_sparse", False))
    attrs = card.get("attributes") or []
    apts = card.get("aptitudes") or []
    if not isinstance(attrs, list):
        attrs = json.loads(attrs) if attrs else []
    if not isinstance(apts, list):
        apts = json.loads(apts) if apts else []
    attrs_json = json.dumps(attrs, ensure_ascii=False)
    apts_json = json.dumps(apts, ensure_ascii=False)
    rarity = card.get("rarity") or ""

    search_blob = " ".join(
        str(part)
        for part in (
            card.get("name"),
            card.get("card_code"),
            rarity,
            card.get("card_type"),
            card.get("subtype"),
            card.get("color"),
            " ".join(attrs),
            " ".join(apts),
            card.get("effect") or "",
            card.get("edition_code") or "",
            card.get("official_id") or "",
        )
        if part
    )

    payload = {
        "official_id": card.get("official_id"),
        "card_code": card["card_code"],
        "name": card["name"],
        "rarity": rarity,
        "card_type": card.get("card_type"),
        "subtype": card.get("subtype"),
        "color": card.get("color"),
        "attributes": attrs_json,
        "aptitudes": apts_json,
        "cost": card.get("cost"),
        "power": card.get("power"),
        "strike": card.get("strike"),
        "effect": card.get("effect"),
        "image_path": card.get("image_path"),
        "image_url": card.get("image_url"),
        "landscape": card.get("landscape"),
        "source_url": card.get("source_url"),
        "edition_id": card.get("edition_id"),
        "search_blob": search_blob,
    }

    existing = conn.execute(
        "SELECT id, image_path, card_code FROM cards WHERE card_code = ? AND rarity = ?",
        (payload["card_code"], payload["rarity"]),
    ).fetchone()
    if existing is None and payload["official_id"] is not None:
        existing = conn.execute(
            "SELECT id, image_path, card_code FROM cards WHERE official_id = ?",
            (payload["official_id"],),
        ).fetchone()
        if existing and existing["card_code"] != payload["card_code"]:
            existing = None
            payload["official_id"] = None

    if existing and not payload["image_path"]:
        payload["image_path"] = existing["image_path"]
    if payload.get("landscape") is None and payload.get("image_path"):
        payload["landscape"] = landscape_flag(payload["image_path"])

    if existing and sparse:
        prev = conn.execute("SELECT * FROM cards WHERE id = ?", (existing["id"],)).fetchone()
        if prev:
            for key in ("card_type", "subtype", "color", "cost", "power", "strike", "effect"):
                if payload.get(key) in (None, ""):
                    payload[key] = prev[key]
            if payload.get("attributes") == "[]" and prev["attributes"] not in (None, "", "[]"):
                payload["attributes"] = prev["attributes"]
            if payload.get("aptitudes") == "[]" and prev["aptitudes"] not in (None, "", "[]"):
                payload["aptitudes"] = prev["aptitudes"]

    if existing:
        conn.execute(
            """
            UPDATE cards SET
                official_id = COALESCE(:official_id, official_id),
                name = :name,
                card_type = COALESCE(:card_type, card_type),
                subtype = COALESCE(:subtype, subtype),
                color = COALESCE(:color, color),
                attributes = :attributes,
                aptitudes = :aptitudes,
                cost = COALESCE(:cost, cost),
                power = COALESCE(:power, power),
                strike = COALESCE(:strike, strike),
                effect = COALESCE(:effect, effect),
                image_path = COALESCE(:image_path, image_path),
                image_url = :image_url,
                landscape = COALESCE(:landscape, landscape),
                source_url = :source_url,
                edition_id = :edition_id,
                search_blob = :search_blob,
                updated_at = datetime('now')
            WHERE id = :id
            """,
            {**payload, "id": existing["id"]},
        )
        return int(existing["id"]), "updated"

    cur = conn.execute(
        """
        INSERT INTO cards (
            official_id, card_code, name, rarity, card_type, subtype, color,
            attributes, aptitudes, cost, power, strike, effect,
            image_path, image_url, landscape, source_url, edition_id, search_blob
        ) VALUES (
            :official_id, :card_code, :name, :rarity, :card_type, :subtype, :color,
            :attributes, :aptitudes, :cost, :power, :strike, :effect,
            :image_path, :image_url, :landscape, :source_url, :edition_id, :search_blob
        )
        """,
        payload,
    )
    return int(cur.lastrowid), "inserted"


def rebuild_search_blob(card: dict[str, Any]) -> str:
    attrs = card.get("attributes") or []
    apts = card.get("aptitudes") or []
    if isinstance(attrs, str):
        try:
            attrs = json.loads(attrs)
        except json.JSONDecodeError:
            attrs = [attrs]
    if isinstance(apts, str):
        try:
            apts = json.loads(apts)
        except json.JSONDecodeError:
            apts = [apts]
    return " ".join(
        str(part)
        for part in (
            card.get("name"),
            card.get("card_code"),
            card.get("rarity") or "",
            card.get("card_type"),
            card.get("subtype"),
            card.get("color"),
            " ".join(attrs) if isinstance(attrs, list) else attrs,
            " ".join(apts) if isinstance(apts, list) else apts,
            card.get("effect") or "",
            card.get("edition_code") or "",
            card.get("official_id") or "",
        )
        if part
    )


def update_card(conn: sqlite3.Connection, card_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    if not row:
        return None
    current = dict(row)
    attrs = fields.get("attributes", current["attributes"])
    apts = fields.get("aptitudes", current["aptitudes"])
    if isinstance(attrs, list):
        attrs = json.dumps(attrs, ensure_ascii=False)
    if isinstance(apts, list):
        apts = json.dumps(apts, ensure_ascii=False)
    merged = {
        **current,
        **fields,
        "attributes": attrs,
        "aptitudes": apts,
    }
    merged["search_blob"] = rebuild_search_blob(merged)
    conn.execute(
        """
        UPDATE cards SET
            official_id = :official_id,
            card_code = :card_code,
            name = :name,
            rarity = :rarity,
            card_type = :card_type,
            subtype = :subtype,
            color = :color,
            attributes = :attributes,
            aptitudes = :aptitudes,
            cost = :cost,
            power = :power,
            strike = :strike,
            effect = :effect,
            edition_id = :edition_id,
            banned = :banned,
            price_cents = :price_cents,
            search_blob = :search_blob,
            updated_at = datetime('now')
        WHERE id = :id
        """,
        {
            **merged,
            "id": card_id,
            "rarity": merged.get("rarity") or "",
            "banned": int(bool(merged.get("banned"))),
            "price_cents": merged.get("price_cents"),
        },
    )
    return row_to_card(
        conn.execute(
            """
            SELECT cards.*, editions.code AS edition_code, editions.name AS edition_name
            FROM cards LEFT JOIN editions ON editions.id = cards.edition_id
            WHERE cards.id = ?
            """,
            (card_id,),
        ).fetchone()
    )


def delete_card(conn: sqlite3.Connection, card_id: int) -> tuple[bool, str | None]:
    row = conn.execute("SELECT image_path FROM cards WHERE id = ?", (card_id,)).fetchone()
    if not row:
        return False, None
    path = row["image_path"]
    conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
    return True, path


def delete_edition(conn: sqlite3.Connection, code: str) -> list[str] | None:
    edition = conn.execute("SELECT id FROM editions WHERE code = ?", (code,)).fetchone()
    if not edition:
        return None
    paths = [
        r["image_path"]
        for r in conn.execute(
            "SELECT image_path FROM cards WHERE edition_id = ? AND image_path IS NOT NULL",
            (edition["id"],),
        ).fetchall()
        if r["image_path"]
    ]
    conn.execute("DELETE FROM cards WHERE edition_id = ?", (edition["id"],))
    conn.execute("DELETE FROM editions WHERE id = ?", (edition["id"],))
    return paths


def wipe_catalog(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM cards")
    conn.execute("DELETE FROM editions")


EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS collection (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    owned INTEGER NOT NULL DEFAULT 0,
    wanted INTEGER NOT NULL DEFAULT 0,
    condition TEXT DEFAULT 'NM',
    location TEXT DEFAULT '',
    for_trade INTEGER DEFAULT 0,
    notes TEXT DEFAULT '',
    PRIMARY KEY (user_id, card_id)
);
CREATE INDEX IF NOT EXISTS idx_collection_user ON collection(user_id);

CREATE TABLE IF NOT EXISTS decks (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_decks_user ON decks(user_id);

CREATE TABLE IF NOT EXISTS deck_cards (
    deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    qty INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (deck_id, card_id)
);

CREATE TABLE IF NOT EXISTS chat_cache (
    qhash TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    model TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS errata (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    filename TEXT,
    stored_path TEXT,
    text TEXT,
    uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS card_notes (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    notes TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (user_id, card_id)
);

CREATE TABLE IF NOT EXISTS pulls (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'Display',
    qty INTEGER NOT NULL DEFAULT 1,
    foil INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pulls_user ON pulls(user_id);

CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    action TEXT NOT NULL,
    summary TEXT NOT NULL,
    card_id INTEGER REFERENCES cards(id) ON DELETE SET NULL,
    deck_id INTEGER,
    foil INTEGER NOT NULL DEFAULT 0,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_activity_user ON activity(user_id, id DESC);
"""


def _ensure_column(conn: sqlite3.Connection, table: str, name: str, decl: str) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _table_pk(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in sorted((r for r in rows if r[5]), key=lambda r: int(r[5]))]


FOIL_RARITIES = frozenset({"SR", "OSR", "SP", "SSP", "SSS", "TSR", "TSP"})
_FOIL_PREF = ("TSR", "TSP", "SR", "OSR", "SSP", "SP", "SSS")
_CODE_BASE_RE = re.compile(r"^([A-Z0-9]+-\d+)", re.I)


def _base_code(code: str | None) -> str:
    raw = (code or "").strip().upper()
    m = _CODE_BASE_RE.match(raw)
    return m.group(1) if m else raw


def is_foil_printing(rarity: str | None = None, card_code: str | None = None) -> bool:
    rare = (rarity or "").strip().upper()
    if rare in FOIL_RARITIES:
        return True
    raw = (card_code or "").strip().upper()
    base = _base_code(raw)
    suffix = raw[len(base) :] if base and raw.startswith(base) else ""
    return suffix in FOIL_RARITIES


def foil_targets(conn: sqlite3.Connection) -> dict[int, int]:
    rows = conn.execute("SELECT id, card_code, rarity FROM cards").fetchall()
    by_base: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        by_base.setdefault(_base_code(row["card_code"]), []).append(row)
    out: dict[int, int] = {}
    for row in rows:
        cid = int(row["id"])
        if is_foil_printing(row["rarity"], row["card_code"]):
            out[cid] = cid
            continue
        foils = [
            sib
            for sib in by_base.get(_base_code(row["card_code"]), [])
            if is_foil_printing(sib["rarity"], sib["card_code"])
        ]
        if not foils:
            out[cid] = cid
            continue
        foils.sort(
            key=lambda sib: _FOIL_PREF.index((sib["rarity"] or "").upper())
            if (sib["rarity"] or "").upper() in _FOIL_PREF
            else 99
        )
        out[cid] = int(foils[0]["id"])
    return out


def _drop_foil_dimension(conn: sqlite3.Connection) -> None:
    coll_info = conn.execute("PRAGMA table_info(collection)").fetchall()
    deck_info = conn.execute("PRAGMA table_info(deck_cards)").fetchall()
    coll_cols = {r[1] for r in coll_info}
    deck_cols = {r[1] for r in deck_info}
    coll_done = coll_info and "foil" not in coll_cols and _table_pk(conn, "collection") == ["user_id", "card_id"]
    deck_done = (not deck_info) or (
        "foil" not in deck_cols and _table_pk(conn, "deck_cards") == ["deck_id", "card_id"]
    )
    if coll_done and deck_done:
        return

    targets = foil_targets(conn) if coll_info or deck_info else {}

    pulls_cols = {r[1] for r in conn.execute("PRAGMA table_info(pulls)").fetchall()}
    if "foil" in pulls_cols and targets:
        for row in conn.execute("SELECT id, card_id, foil FROM pulls").fetchall():
            if not row["foil"]:
                continue
            new_id = targets.get(int(row["card_id"]), int(row["card_id"]))
            if new_id != int(row["card_id"]):
                conn.execute("UPDATE pulls SET card_id = ? WHERE id = ?", (new_id, row["id"]))

    conn.execute("PRAGMA foreign_keys = OFF")

    if coll_info and not coll_done:
        merged: dict[tuple[int, int], dict[str, Any]] = {}
        for row in conn.execute("SELECT * FROM collection").fetchall():
            cid = int(row["card_id"])
            if "foil" in coll_cols and row["foil"]:
                cid = targets.get(cid, cid)
            key = (int(row["user_id"]), cid)
            rec = merged.get(key)
            owned = int(row["owned"] or 0)
            wanted = int(row["wanted"] or 0)
            if rec is None:
                merged[key] = {
                    "owned": owned,
                    "wanted": wanted,
                    "condition": (row["condition"] if "condition" in coll_cols else None) or "NM",
                    "location": (row["location"] if "location" in coll_cols else None) or "",
                    "for_trade": int(bool(row["for_trade"])) if "for_trade" in coll_cols else 0,
                    "notes": (row["notes"] if "notes" in coll_cols else None) or "",
                }
                continue
            rec["owned"] += owned
            rec["wanted"] = max(rec["wanted"], wanted)
            rec["for_trade"] = int(bool(rec["for_trade"] or (row["for_trade"] if "for_trade" in coll_cols else 0)))
            loc = (row["location"] if "location" in coll_cols else None) or ""
            note = (row["notes"] if "notes" in coll_cols else None) or ""
            if loc and not rec["location"]:
                rec["location"] = loc
            if note and not rec["notes"]:
                rec["notes"] = note
            cond = (row["condition"] if "condition" in coll_cols else None) or "NM"
            if rec["condition"] == "NM" and cond != "NM":
                rec["condition"] = cond
        conn.execute("ALTER TABLE collection RENAME TO collection_mig")
        conn.executescript(
            """
            CREATE TABLE collection (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                owned INTEGER NOT NULL DEFAULT 0,
                wanted INTEGER NOT NULL DEFAULT 0,
                condition TEXT DEFAULT 'NM',
                location TEXT DEFAULT '',
                for_trade INTEGER DEFAULT 0,
                notes TEXT DEFAULT '',
                PRIMARY KEY (user_id, card_id)
            );
            CREATE INDEX IF NOT EXISTS idx_collection_user ON collection(user_id);
            """
        )
        conn.executemany(
            """
            INSERT INTO collection(user_id, card_id, owned, wanted, condition, location, for_trade, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    user_id,
                    card_id,
                    rec["owned"],
                    rec["wanted"],
                    rec["condition"] or "NM",
                    rec["location"] or "",
                    int(rec["for_trade"] or 0),
                    rec["notes"] or "",
                )
                for (user_id, card_id), rec in merged.items()
                if rec["owned"] or rec["wanted"] or rec["for_trade"] or rec["location"] or rec["notes"]
            ],
        )
        conn.execute("DROP TABLE collection_mig")

    if deck_info and not deck_done:
        merged_deck: dict[tuple[int, int], int] = {}
        for row in conn.execute("SELECT * FROM deck_cards").fetchall():
            cid = int(row["card_id"])
            if "foil" in deck_cols and row["foil"]:
                cid = targets.get(cid, cid)
            key = (int(row["deck_id"]), cid)
            merged_deck[key] = merged_deck.get(key, 0) + int(row["qty"] or 0)
        conn.execute("ALTER TABLE deck_cards RENAME TO deck_cards_mig")
        conn.executescript(
            """
            CREATE TABLE deck_cards (
                deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
                card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
                qty INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (deck_id, card_id)
            );
            """
        )
        conn.executemany(
            "INSERT INTO deck_cards(deck_id, card_id, qty) VALUES (?, ?, ?)",
            [(deck_id, card_id, qty) for (deck_id, card_id), qty in merged_deck.items() if qty > 0],
        )
        conn.execute("DROP TABLE deck_cards_mig")

    conn.execute("PRAGMA foreign_keys = ON")


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        conn.executescript(TRIGGERS)
        conn.executescript(EXTRA_SCHEMA)
        _ensure_column(conn, "cards", "landscape", "INTEGER")
        _ensure_column(conn, "cards", "banned", "INTEGER DEFAULT 0")
        _ensure_column(conn, "cards", "price_cents", "INTEGER")
        _ensure_column(conn, "cards", "price_3d_cents", "INTEGER")
        _ensure_column(conn, "cards", "price_7d_cents", "INTEGER")
        _ensure_column(conn, "cards", "price_30d_cents", "INTEGER")
        _ensure_column(conn, "cards", "price_daily_swing", "REAL")
        _ensure_column(conn, "cards", "price_3d_swing", "REAL")
        _ensure_column(conn, "cards", "price_7d_swing", "REAL")
        _ensure_column(conn, "cards", "active_listing_count", "INTEGER")
        _ensure_column(conn, "cards", "prices_json", "TEXT")
        _ensure_column(conn, "collection", "condition", "TEXT DEFAULT 'NM'")
        _ensure_column(conn, "collection", "location", "TEXT DEFAULT ''")
        _ensure_column(conn, "collection", "for_trade", "INTEGER DEFAULT 0")
        _ensure_column(conn, "collection", "notes", "TEXT DEFAULT ''")
        _ensure_column(conn, "pulls", "foil", "INTEGER DEFAULT 0")
        _drop_foil_dimension(conn)
        conn.commit()
        fts_n = conn.execute("SELECT COUNT(*) AS n FROM cards_fts").fetchone()["n"]
        cards_n = conn.execute("SELECT COUNT(*) AS n FROM cards").fetchone()["n"]
        if cards_n and fts_n == 0:
            conn.execute(
                "INSERT INTO cards_fts("
                "rowid, name, card_code, rarity, card_type, subtype, color, "
                "attributes, aptitudes, effect, search_blob) "
                "SELECT id, name, card_code, rarity, card_type, subtype, color, "
                "attributes, aptitudes, effect, search_blob FROM cards"
            )
        try:
            refresh_landscapes(conn)
        except Exception:
            pass
        conn.commit()
