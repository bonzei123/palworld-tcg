from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from .db import get_db, get_setting, set_setting

AUTH_URL = "https://palworldcard.com/api/collections/users/auth-with-password"
ADMIN_AUTH_URL = "https://palworldcard.com/api/admins/auth-with-password"
RECORDS_URL = "https://palworldcard.com/api/collections/cards/records"

CODE_KEYS = ("card_number", "code", "card_code", "number", "cardNumber")


def money_to_cents(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.replace("€", "").replace("$", "").replace(",", ".").strip()
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _norm_code(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _item_code(item: dict[str, Any]) -> str:
    for key in CODE_KEYS:
        raw = item.get(key)
        if raw:
            return str(raw).strip().upper()
    return ""


def _is_official(item: dict[str, Any]) -> bool:
    return str(item.get("source") or "").strip().casefold() == "official"


def _auth_token(client: httpx.Client, identity: str, password: str) -> str:
    payload = {"identity": identity, "password": password}
    last_error = "Anmeldung fehlgeschlagen."
    for url in (AUTH_URL, ADMIN_AUTH_URL):
        try:
            res = client.post(url, json=payload)
        except httpx.HTTPError as exc:
            last_error = str(exc)
            continue
        if res.status_code >= 400:
            try:
                detail = res.json()
                last_error = str(detail.get("message") or detail.get("error") or res.text[:240])
            except Exception:
                last_error = res.text[:240] or f"HTTP {res.status_code}"
            continue
        data = res.json()
        token = data.get("token") or (data.get("data") or {}).get("token")
        if token:
            return str(token)
        last_error = "Antwort ohne Token."
    raise RuntimeError(last_error)


def _fetch_records(client: httpx.Client, token: str) -> list[dict[str, Any]]:
    headers = {"Authorization": token}
    items: list[dict[str, Any]] = []
    page = 1
    while page <= 200:
        res = client.get(
            RECORDS_URL,
            params={"page": page, "perPage": 500, "skipTotal": 1},
            headers=headers,
        )
        if res.status_code == 401:
            res = client.get(
                RECORDS_URL,
                params={"page": page, "perPage": 500, "skipTotal": 1},
                headers={"Authorization": f"Bearer {token}"},
            )
        res.raise_for_status()
        data = res.json()
        batch = data.get("items") or data.get("data") or []
        if not isinstance(batch, list) or not batch:
            break
        items.extend(item for item in batch if isinstance(item, dict))
        page += 1
    return items


def sync_official_prices() -> dict[str, Any]:
    with get_db() as conn:
        identity = (get_setting(conn, "palworldcard_identity") or "").strip()
        password = get_setting(conn, "palworldcard_password") or ""
    if not identity or not password:
        raise RuntimeError("Palworldcard-Zugangsdaten fehlen. Unter Admin eintragen.")

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        token = _auth_token(client, identity, password)
        remote = _fetch_records(client, token)

    official = [item for item in remote if _is_official(item)]
    with get_db() as conn:
        ours = conn.execute("SELECT id, card_code FROM cards").fetchall()
        by_code: dict[str, list[int]] = {}
        for row in ours:
            compact = _norm_code(row["card_code"])
            if not compact:
                continue
            by_code.setdefault(compact, []).append(int(row["id"]))
            dashed = str(row["card_code"] or "").strip().upper()
            if dashed and dashed != compact:
                by_code.setdefault(_norm_code(dashed), []).append(int(row["id"]))

        updated_ids: set[int] = set()
        skipped = 0
        for item in official:
            code = _item_code(item)
            compact = _norm_code(code)
            ids = by_code.get(compact) or []
            if not ids:
                skipped += 1
                continue
            payload = {
                "price_cents": money_to_cents(item.get("price")),
                "price_3d_cents": money_to_cents(item.get("3_day_price")),
                "price_7d_cents": money_to_cents(item.get("7_day_price")),
                "price_30d_cents": money_to_cents(item.get("30_day_price")),
                "price_daily_swing": as_float(item.get("daily_swing")),
                "price_3d_swing": as_float(item.get("3_day_swing")),
                "price_7d_swing": as_float(item.get("7_day_swing")),
                "active_listing_count": as_int(item.get("active_listing_count")),
                "prices_json": json.dumps(item, ensure_ascii=False, default=str),
            }
            for card_id in ids:
                conn.execute(
                    """
                    UPDATE cards SET
                        price_cents = :price_cents,
                        price_3d_cents = :price_3d_cents,
                        price_7d_cents = :price_7d_cents,
                        price_30d_cents = :price_30d_cents,
                        price_daily_swing = :price_daily_swing,
                        price_3d_swing = :price_3d_swing,
                        price_7d_swing = :price_7d_swing,
                        active_listing_count = :active_listing_count,
                        prices_json = :prices_json,
                        updated_at = datetime('now')
                    WHERE id = :id
                    """,
                    {**payload, "id": card_id},
                )
                updated_ids.add(card_id)

        synced_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        summary = {
            "updated": len(updated_ids),
            "skipped": skipped,
            "official": len(official),
            "fetched": len(remote),
            "synced_at": synced_at,
        }
        set_setting(conn, "prices_synced_at", synced_at)
        set_setting(conn, "prices_sync_summary", json.dumps(summary, ensure_ascii=False))
    return summary
