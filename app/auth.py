from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Any

from fastapi import HTTPException, Request

from .db import get_db

USER_RE = re.compile(r"^[A-Za-z0-9_\-]{3,32}$")
PBKDF2_ROUNDS = 210_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ROUNDS)
    return f"pbkdf2${PBKDF2_ROUNDS}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt, digest = stored.split("$", 3)
        if algo != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(rounds)
        )
        return hmac.compare_digest(dk.hex(), digest)
    except (ValueError, TypeError):
        return False


def current_user(request: Request) -> dict[str, Any] | None:
    uid = request.session.get("user_id")
    if not uid:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, username, created_at FROM users WHERE id = ?", (uid,)
        ).fetchone()
    return dict(row) if row else None


def require_user(request: Request) -> dict[str, Any]:
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Bitte anmelden.")
    return user


def register_user(username: str, password: str) -> tuple[int | None, str | None]:
    username = (username or "").strip()
    if not USER_RE.match(username):
        return None, "Benutzername: 3–32 Zeichen, nur Buchstaben, Zahlen, _ und -."
    if len(password or "") < 8:
        return None, "Passwort mindestens 8 Zeichen."
    with get_db() as conn:
        exists = conn.execute(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
        if exists:
            return None, "Benutzername ist schon vergeben."
        cur = conn.execute(
            "INSERT INTO users(username, password_hash) VALUES (?, ?)",
            (username, hash_password(password)),
        )
        return int(cur.lastrowid), None


def login_user(username: str, password: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ? COLLATE NOCASE",
            ((username or "").strip(),),
        ).fetchone()
    if not row or not verify_password(password or "", row["password_hash"]):
        return None
    return {"id": row["id"], "username": row["username"]}
