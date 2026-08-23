from __future__ import annotations

import io
import json
import re
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from .config import CARDLISTS_DIR, IMAGES_DIR, PROJECT_CARDLISTS_DIR, ensure_dirs
from .db import get_db, landscape_flag, upsert_card, upsert_edition

CARD_TYPES = {"Pal", "Event", "Structure", "Soul", "Partner", "Item", "Tool", "Energy"}
ATTR_RE = re.compile(r"img_attribute-([a-z0-9]+)", re.I)
NUM_RE = re.compile(r"(\d+)")
CODE_RE = re.compile(r"^([A-Z0-9]+)-(\d+)", re.I)
STEM_RE = re.compile(r"^([A-Z0-9]+-\d+)([A-Z]*)$", re.I)
SET_FROM_URL_RE = re.compile(r"/cardlist/([A-Z0-9]+)/", re.I)
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

EDITION_NAMES = {
    "ETD01": "Trial Deck 01",
    "ETD02": "Trial Deck 02",
    "ESOUL": "Soul",
    "EBP01": "Booster Pack 01",
}

ProgressFn = Callable[[dict[str, Any]], None]


def parse_html(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    cards: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for block in soup.select("div.parts-thumb-txt"):
        card = _parse_block(block)
        if not card:
            continue
        key = (card["card_code"], card.get("rarity") or "")
        if key in seen:
            continue
        seen.add(key)
        cards.append(card)
    for item in soup.select("div.image-list__item"):
        card = _parse_image_item(item)
        if not card:
            continue
        key = (card["card_code"], card.get("rarity") or "")
        if key in seen:
            continue
        seen.add(key)
        cards.append(card)
    return cards


def _parse_block(block: Tag) -> dict[str, Any] | None:
    title = block.select_one(".parts-thumb-tit")
    subtitle = block.select_one(".parts-thumb-sub-tit")
    if not title or not subtitle:
        return None
    name = title.get_text(" ", strip=True)
    sub = subtitle.get_text(" ", strip=True)
    if not name or not sub:
        return None

    img = block.select_one(".thumb img")
    image_url = (img.get("src") or "").strip() if img else ""
    more = block.select_one("a.detail-btn") or block.select_one(".thumb a")
    source_url = (more.get("href") or "").strip() if more else ""

    rarity_el = block.select_one("li.rarity")
    rarity = rarity_el.get_text(strip=True) if rarity_el else None
    card_code, rarity = _split_code(sub, rarity)

    card_type = subtype = color = None
    attributes: list[str] = []
    aptitudes: list[str] = []
    cost = power = strike = None

    for li in block.select("ul.detail-data > li"):
        classes = set(li.get("class") or [])
        text = li.get_text(" ", strip=True)
        if "rarity" in classes:
            rarity = rarity or text
        elif "color" in classes:
            color = text or None
        elif "attribute" in classes:
            attributes = _attributes(li)
        elif "aptitude" in classes:
            aptitudes = _aptitudes(text)
        elif "cost" in classes:
            cost = _first_int(text)
        elif "combat-power" in classes:
            power = _first_int(text)
        elif "striking-power" in classes:
            strike = _first_int(text)
        elif not classes:
            if text in CARD_TYPES and not card_type:
                card_type = text
            elif text:
                subtype = text

    effect_el = block.select_one(".detail-txt")
    return {
        "official_id": _query_id(source_url),
        "card_code": card_code,
        "name": name,
        "rarity": rarity or "",
        "card_type": card_type,
        "subtype": subtype,
        "color": color,
        "attributes": attributes,
        "aptitudes": aptitudes,
        "cost": cost,
        "power": power,
        "strike": strike,
        "effect": _effect_text(effect_el) if effect_el else None,
        "edition_code": _edition_code(card_code, image_url),
        "_image_filename": Path(unquote(urlparse(image_url).path)).name if image_url else "",
        "_image_src": image_url if image_url and "img_default" not in image_url else "",
    }


def _parse_image_item(item: Tag) -> dict[str, Any] | None:
    img = item.select_one("img")
    if not img:
        return None
    src = (img.get("src") or "").strip()
    if not src or "img_default" in src:
        return None
    name = (img.get("alt") or "").strip()
    filename = Path(unquote(urlparse(src).path)).name
    stem = Path(filename).stem
    if not name or not stem:
        return None
    card_code, rarity = _code_from_stem(stem)
    link = item.select_one("a")
    href = (link.get("href") or "").strip() if link else ""
    card_type = "Soul" if name.casefold() == "soul" else None
    return {
        "official_id": _query_id(href),
        "card_code": card_code,
        "name": name,
        "rarity": rarity,
        "card_type": card_type,
        "subtype": None,
        "color": None,
        "attributes": [],
        "aptitudes": [],
        "cost": None,
        "power": None,
        "strike": None,
        "effect": None,
        "edition_code": _edition_code(card_code, src),
        "_image_filename": filename,
        "_image_src": src,
        "_sparse": True,
    }


def _code_from_stem(stem: str) -> tuple[str, str]:
    m = STEM_RE.match(stem.strip())
    if not m:
        return stem.strip().upper(), ""
    return m.group(1).upper(), (m.group(2) or "").upper()


def archive_cardlist(filename: str | None, html: str) -> dict[str, str]:
    ensure_dirs()
    raw = Path(filename or "cardlist.html").name
    safe = SAFE_NAME_RE.sub("_", raw).strip("._") or "cardlist.html"
    if not safe.lower().endswith((".html", ".htm")):
        safe += ".html"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stored = f"{stamp}_{safe}"
    data_path = CARDLISTS_DIR / stored
    project_path = PROJECT_CARDLISTS_DIR / stored
    data_path.write_text(html, encoding="utf-8")
    project_path.write_text(html, encoding="utf-8")
    return {"data": str(data_path), "project": str(project_path), "filename": stored}


def save_card_image(
    edition: str,
    filename: str,
    src: str,
    client: httpx.Client | None = None,
) -> str | None:
    if not filename:
        return None
    rel = f"{edition}/{filename}".replace("\\", "/")
    dest = IMAGES_DIR / rel
    if dest.is_file() and dest.stat().st_size > 200:
        return rel
    if not src or not src.startswith("http") or "img_default" in src:
        return rel if dest.is_file() else None
    dest.parent.mkdir(parents=True, exist_ok=True)
    own = client is None
    if own:
        client = httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "PalworldTCG-Katalog/1.0"},
        )
    try:
        res = client.get(src)
        if res.status_code != 200 or len(res.content) < 200:
            return None
        ctype = (res.headers.get("content-type") or "").lower()
        if ctype and "image" not in ctype and "octet-stream" not in ctype:
            return None
        dest.write_bytes(res.content)
        return rel
    except httpx.HTTPError:
        return None
    finally:
        if own:
            client.close()


def _query_id(url: str) -> int | None:
    if not url or "id=" not in url:
        return None
    try:
        return int(url.split("id=", 1)[1].split("&", 1)[0])
    except (TypeError, ValueError):
        return None


def _split_code(subtitle: str, rarity: str | None) -> tuple[str, str | None]:
    parts = subtitle.split()
    if len(parts) >= 2 and (not rarity or parts[-1].upper() == rarity.upper()):
        return parts[0], rarity or parts[-1]
    if rarity and subtitle.endswith(" " + rarity):
        return subtitle[: -len(rarity)].strip(), rarity
    return subtitle, rarity


def _edition_code(card_code: str, image_url: str) -> str:
    m = CODE_RE.match(card_code)
    if m:
        return m.group(1).upper()
    if "-" in card_code:
        return card_code.split("-", 1)[0].upper()
    m = SET_FROM_URL_RE.search(image_url or "")
    return m.group(1).upper() if m else "UNKNOWN"


def _attributes(li: Tag) -> list[str]:
    found: list[str] = []
    for img in li.select("img"):
        m = ATTR_RE.search(img.get("src") or "")
        if m:
            label = m.group(1).replace("-", " ").title()
            found.append("None" if label.lower() == "none" else label)
    return found


def _aptitudes(text: str) -> list[str]:
    found = re.findall(r"[≪«]([^≫»]+)[≫»]", text)
    if found:
        return [a.strip() for a in found if a.strip()]
    cleaned = text.strip()
    return [cleaned] if cleaned else []


def _first_int(text: str) -> int | None:
    m = NUM_RE.search(text or "")
    return int(m.group(1)) if m else None


def _effect_text(el: Tag) -> str:
    node = BeautifulSoup(str(el), "lxml")
    root = node.select_one(".detail-txt") or node
    for img in root.select("img"):
        alt = (img.get("alt") or "").strip().rstrip("@")
        img.replace_with(f"[{alt}]" if alt else "")
    for br in root.select("br"):
        br.replace_with("\n")
    lines = [" ".join(line.split()) for line in root.get_text(" ", strip=False).splitlines()]
    return "\n".join(line for line in lines if line).strip()


def import_cards(
    html: str,
    *,
    edition_name: str | None = None,
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    cards = parse_html(html)
    if progress:
        progress({"stage": "parse", "count": len(cards), "total": len(cards)})
    if not cards:
        return {"ok": False, "error": "Keine Karten im HTML gefunden.", "stage": "done", "total": 0}

    codes = Counter(c["edition_code"] for c in cards)
    majority = codes.most_common(1)[0][0]
    inserted = updated = images_ok = 0
    editions: dict[str, int] = {}
    http = httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "PalworldTCG-Katalog/1.0"},
    )
    try:
        with get_db() as conn:
            for i, card in enumerate(cards, start=1):
                code = card["edition_code"]
                if code not in editions:
                    if edition_name and code == majority:
                        label = edition_name
                    else:
                        label = EDITION_NAMES.get(code)
                    editions[code] = upsert_edition(conn, code, label)
                card["edition_id"] = editions[code]
                filename = card.pop("_image_filename", "")
                src = card.pop("_image_src", "")
                if filename:
                    rel = save_card_image(code, filename, src, client=http)
                    if rel:
                        card["image_path"] = rel
                        card["landscape"] = landscape_flag(rel)
                        images_ok += 1
                card["image_url"] = None
                card["source_url"] = None
                _, action = upsert_card(conn, card)
                if action == "inserted":
                    inserted += 1
                else:
                    updated += 1
                if progress and (i == len(cards) or i % 20 == 0):
                    progress({"stage": "save", "done": i, "total": len(cards)})
    finally:
        http.close()

    result = {
        "ok": True,
        "stage": "done",
        "total": len(cards),
        "inserted": inserted,
        "updated": updated,
        "images_ok": images_ok,
        "images_unmatched": 0,
        "editions": sorted(editions.keys()),
    }
    if progress:
        progress(result)
    return result


def attach_images_from_zip(
    zip_bytes: bytes,
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    ok = unmatched = 0
    with get_db() as conn:
        rows = conn.execute("SELECT id, card_code, rarity, edition_id FROM cards").fetchall()
        editions = {r["id"]: r["code"] for r in conn.execute("SELECT id, code FROM editions").fetchall()}

    by_code: dict[str, list] = {}
    by_code_rarity: dict[str, Any] = {}
    for row in rows:
        code = (row["card_code"] or "").upper()
        rarity = (row["rarity"] or "").upper()
        by_code.setdefault(code, []).append(row)
        by_code_rarity[f"{code}{rarity}"] = row
        by_code_rarity[f"{code}-{rarity}"] = row

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [
            n
            for n in zf.namelist()
            if not n.endswith("/") and "__MACOSX" not in n and not Path(n).name.startswith(".")
        ]
        total = len(names)
        for i, name in enumerate(names, start=1):
            stem = Path(name).stem.upper()
            row = by_code_rarity.get(stem)
            if row is None:
                matches = by_code.get(stem) or []
                row = matches[0] if len(matches) == 1 else None
            if row is None:
                unmatched += 1
                continue
            ext = Path(name).suffix.lower() or ".png"
            if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                unmatched += 1
                continue
            edition = editions.get(row["edition_id"]) or "misc"
            rel = f"{edition}/{row['card_code']}{ext}"
            dest = IMAGES_DIR / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(name))
            rel_norm = rel.replace("\\", "/")
            with get_db() as conn:
                conn.execute(
                    "UPDATE cards SET image_path = ?, landscape = ?, updated_at = datetime('now') WHERE id = ?",
                    (rel_norm, landscape_flag(rel_norm), row["id"]),
                )
            ok += 1
            if progress and (i == total or i % 5 == 0):
                progress({"stage": "image", "done": i, "total": total, "ok": ok, "name": Path(name).name})
    return {"ok": ok, "unmatched": unmatched, "total": ok + unmatched}


def compact_catalog(limit: int = 5000) -> str:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT card_code, name, rarity, card_type, subtype, color, attributes,
                   aptitudes, cost, power, strike, effect
            FROM cards
            ORDER BY edition_id, card_code, rarity
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    lines = []
    for row in rows:
        attrs = ", ".join(json.loads(row["attributes"] or "[]"))
        apts = ", ".join(json.loads(row["aptitudes"] or "[]"))
        bits = [
            row["card_code"],
            row["rarity"] or "",
            row["name"],
            row["card_type"] or "",
            row["subtype"] or "",
            row["color"] or "",
            f"ATTR {attrs}" if attrs else "",
            f"APT {apts}" if apts else "",
            f"Cost {row['cost']}" if row["cost"] is not None else "",
            f"Power {row['power']}" if row["power"] is not None else "",
            f"Strike {row['strike']}" if row["strike"] is not None else "",
        ]
        header = " | ".join(b for b in bits if b)
        effect = (row["effect"] or "").replace("\n", " / ")
        lines.append(header + (f" || {effect}" if effect else ""))
    return "\n".join(lines)
