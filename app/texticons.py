from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse
from markupsafe import Markup, escape

from .keywords import ICON_KEYS, wrap_icon, wrap_text

IMG_DIR = Path(__file__).resolve().parent / "static" / "img"
ICON_URL = "/static/img"
SKIP_STEMS = {"favicon", "icon-512", "apple-touch-icon"}
IMAGE_EXTS = {".png", ".webp", ".svg", ".gif", ".jpg", ".jpeg"}
PREFIXES = (
    "能力_",
    "タイミング_",
    "場所_",
    "コスト_",
    "アイコン_",
    "その他_",
    "type_",
)
JP_KEYS = {
    "食材": "ingredient",
    "素材": "material",
    "戦闘力黒": "power",
    "打撃力黒": "strike",
    "turn1": "1turn",
    "on deploy": "ondeploy",
    "on attack": "onattack",
    "on assign": "onassign",
}
INNER_TOKEN_RE = re.compile(r"\[([^\[\]]+)\]")
DIAMOND_RE = re.compile(r"^[◇◆♢♦](\d+)$")
COST_RE = re.compile(r"^cost[\s_-]*(\d+)$", re.I)
_PH = "\ufffc"
_index: dict[str, str] | None = None


def _strip_prefix(stem: str) -> str:
    for prefix in PREFIXES:
        if stem.startswith(prefix):
            return stem[len(prefix) :]
        if stem.casefold().startswith(prefix.casefold()):
            return stem[len(prefix) :]
    return stem


def icon_key(raw: str) -> str:
    text = (raw or "").strip().rstrip("@")
    diamond = DIAMOND_RE.fullmatch(text)
    if diamond:
        return f"cost{diamond.group(1)}"
    cost = COST_RE.fullmatch(text)
    if cost:
        return f"cost{cost.group(1)}"
    stem = _strip_prefix(text)
    folded = stem.casefold()
    if folded in JP_KEYS:
        return JP_KEYS[folded]
    compact = re.sub(r"[\s_\-]+", "", folded)
    aliases = {
        "cont": "cont",
        "act": "act",
        "auto": "auto",
        "ondeploy": "ondeploy",
        "onattack": "onattack",
        "onassign": "onassign",
        "quick": "quick",
        "hand": "hand",
        "ingredient": "ingredient",
        "material": "material",
        "power": "power",
        "strike": "strike",
        "damage": "damage",
        "1turn": "1turn",
        "turn1": "1turn",
    }
    return aliases.get(compact, compact)


def _build_index() -> dict[str, str]:
    found: dict[str, str] = {}
    if not IMG_DIR.is_dir():
        return found
    for path in IMG_DIR.iterdir():
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
            continue
        if path.stem.casefold() in SKIP_STEMS:
            continue
        key = icon_key(path.stem)
        if key and key not in found:
            found[key] = path.name
    return found


def icon_index() -> dict[str, str]:
    global _index
    if _index is None:
        _index = _build_index()
    return _index


def refresh_index() -> dict[str, str]:
    global _index
    _index = _build_index()
    return _index


def icon_src(token: str) -> str | None:
    name = icon_index().get(icon_key(token))
    if not name:
        return None
    return f"{ICON_URL}/{name}"


def _icon_markup(token: str, src: str) -> Markup:
    key = icon_key(token)
    label = escape(token)
    img = Markup(
        f'<img class="text-icon" src="{escape(src)}" alt="{label}" title="">'
    )
    if key in ICON_KEYS:
        return wrap_icon(img, key)
    return img


def render_effect(text: str | None) -> Markup:
    if not text:
        return Markup("")
    icons: list[Markup] = []
    remaining = text
    while True:
        changed = False

        def _replace_inner(match: re.Match[str]) -> str:
            nonlocal changed
            token = match.group(1).strip()
            src = icon_src(token)
            if not src:
                return match.group(0)
            changed = True
            icons.append(_icon_markup(token, src))
            return f"{_PH}{len(icons) - 1}{_PH}"

        remaining = INNER_TOKEN_RE.sub(_replace_inner, remaining)
        if not changed:
            break

    parts: list[Markup | str] = []
    last = 0
    for match in re.finditer(rf"{_PH}(\d+){_PH}", remaining):
        parts.append(wrap_text(remaining[last : match.start()]))
        parts.append(icons[int(match.group(1))])
        last = match.end()
    parts.append(wrap_text(remaining[last:]))
    return Markup("").join(parts)


def save_name_for(alt: str, src: str) -> str:
    key = icon_key(alt)
    if key.startswith("cost") and key[4:].isdigit():
        return f"cost_{key[4:]}.png"
    pretty = {
        "act": "ACT.png",
        "auto": "AUTO.png",
        "cont": "CONT.png",
        "ondeploy": "OnDeploy.png",
        "onattack": "OnAttack.png",
        "onassign": "OnAssign.png",
        "quick": "Quick.png",
        "hand": "Hand.png",
        "ingredient": "Ingredient.png",
        "material": "Material.png",
        "power": "Power.png",
        "strike": "Strike.png",
        "damage": "Damage.png",
        "1turn": "1Turn.png",
    }
    if key in pretty:
        return pretty[key]
    raw = Path(unquote(urlparse(src).path)).name
    return raw or f"{key}.png"
