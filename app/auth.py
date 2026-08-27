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
USER_SELECT = (
    "SELECT id, username, created_at, "
    "IFNULL(is_admin, 0) AS is_admin, IFNULL(can_rules, 0) AS can_rules "
    "FROM users"
)


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


def _user_from_row(row) -> dict[str, Any]:
    data = dict(row)
    data["is_admin"] = bool(data.get("is_admin"))
    data["can_rules"] = bool(data.get("can_rules"))
    return data


def current_user(request: Request) -> dict[str, Any] | None:
    uid = request.session.get("user_id")
    if not uid:
        return None
    with get_db() as conn:
        row = conn.execute(f"{USER_SELECT} WHERE id = ?", (uid,)).fetchone()
    return _user_from_row(row) if row else None


def require_user(request: Request) -> dict[str, Any]:
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Bitte anmelden.")
    return user


def any_admin_exists() -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE IFNULL(is_admin, 0) = 1 LIMIT 1"
        ).fetchone()
    return bool(row)


def admin_count() -> int:
    with get_db() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE IFNULL(is_admin, 0) = 1"
            ).fetchone()["n"]
        )


def can_open_admin(user: dict[str, Any] | None) -> bool:
    if not user:
        return False
    return bool(user.get("is_admin")) or not any_admin_exists()


def require_rules(request: Request) -> dict[str, Any]:
    user = require_user(request)
    if not user.get("can_rules"):
        raise HTTPException(403, "Kein Recht für den Regel-Chat.")
    return user


def grant_admin(user_id: int) -> None:
    with get_db() as conn:
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user_id,))


def list_users() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(f"{USER_SELECT} ORDER BY username COLLATE NOCASE").fetchall()
    return [_user_from_row(r) for r in rows]


def set_user_flags(user_id: int, *, is_admin: bool | None = None, can_rules: bool | None = None) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute(f"{USER_SELECT} WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise KeyError("user")
        admin = bool(row["is_admin"]) if is_admin is None else bool(is_admin)
        rules = bool(row["can_rules"]) if can_rules is None else bool(can_rules)
        if row["is_admin"] and not admin:
            others = conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE IFNULL(is_admin, 0) = 1 AND id != ?",
                (user_id,),
            ).fetchone()["n"]
            if int(others or 0) == 0:
                raise ValueError("last_admin")
        conn.execute(
            "UPDATE users SET is_admin = ?, can_rules = ? WHERE id = ?",
            (int(admin), int(rules), user_id),
        )
        updated = conn.execute(f"{USER_SELECT} WHERE id = ?", (user_id,)).fetchone()
    return _user_from_row(updated)


def delete_user(user_id: int, *, actor_id: int) -> None:
    if int(user_id) == int(actor_id):
        raise ValueError("self")
    with get_db() as conn:
        row = conn.execute(f"{USER_SELECT} WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise KeyError("user")
        if row["is_admin"]:
            others = conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE IFNULL(is_admin, 0) = 1 AND id != ?",
                (user_id,),
            ).fetchone()["n"]
            if int(others or 0) == 0:
                raise ValueError("last_admin")
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def reset_user_password(user_id: int, password: str | None = None) -> str:
    pw = (password or "").strip()
    if not pw:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
        pw = "".join(secrets.choice(alphabet) for _ in range(12))
    elif len(pw) < 8:
        raise ValueError("short")
    with get_db() as conn:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise KeyError("user")
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(pw), user_id),
        )
    return pw


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
            "INSERT INTO users(username, password_hash, is_admin, can_rules) VALUES (?, ?, 0, 0)",
            (username, hash_password(password)),
        )
        return int(cur.lastrowid), None


def login_user(username: str, password: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT id, username, created_at, password_hash,
                   IFNULL(is_admin, 0) AS is_admin, IFNULL(can_rules, 0) AS can_rules
            FROM users WHERE username = ? COLLATE NOCASE
            """,
            ((username or "").strip(),),
        ).fetchone()
    if not row or not verify_password(password or "", row["password_hash"]):
        return None
    data = _user_from_row(row)
    data.pop("password_hash", None)
    return data


def template_globals(request: Request) -> dict[str, Any]:
    user = current_user(request)
    return {
        "user": user,
        "is_admin": bool(request.session.get("admin")),
        "can_rules": bool(user and user.get("can_rules")),
        "show_admin": bool(user and user.get("is_admin")),
        "admin_setup": bool(user) and not any_admin_exists(),
    }
