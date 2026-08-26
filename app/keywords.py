from __future__ import annotations

import re
from markupsafe import Markup, escape

# Pocketpair Official Card Game (en.palworld-official-cardgame.com), not Bushiroad.
KEYWORDS: dict[str, dict[str, str]] = {
    "act": {
        "title": "ACT",
        "tip": "Aktionsfähigkeit. Du spielst sie bewusst während deines Zuges, oft mit Kosten in eckigen Klammern.",
    },
    "auto": {
        "title": "AUTO",
        "tip": "Automatische Fähigkeit. Löst aus, sobald die beschriebene Bedingung eintritt. Du spielst sie nicht manuell.",
    },
    "cont": {
        "title": "CONT",
        "tip": "Dauerhafte Fähigkeit. Gilt, solange die Karte im Spiel ist.",
    },
    "ondeploy": {
        "title": "On Deploy",
        "tip": "Zeitpunkt: wenn diese Karte ins Spiel kommt (deployed).",
    },
    "onattack": {
        "title": "On Attack",
        "tip": "Zeitpunkt: wenn diese Karte angreift.",
    },
    "onassign": {
        "title": "On Assign",
        "tip": "Zeitpunkt: wenn diese Karte einem Gebäude zugewiesen wird (assign).",
    },
    "quick": {
        "title": "Quick",
        "tip": "Darf im Quick-Schritt gespielt werden — auch als Antwort, nicht nur in deiner normalen Aktionsphase.",
    },
    "hand": {
        "title": "Hand",
        "tip": "Die Fähigkeit wirkt aus der Hand, die Karte muss dafür nicht im Spiel liegen.",
    },
    "1turn": {
        "title": "1 Turn",
        "tip": "Einmal pro Zug. Danach erst wieder im nächsten Zug.",
    },
    "ingredient": {
        "title": "Ingredient",
        "tip": "Zutat. Eine Ressource, die du sammelst und für Kosten ausgibst.",
    },
    "material": {
        "title": "Material",
        "tip": "Material. Eine Ressource, die du sammelst und für Kosten ausgibst.",
    },
    "power": {
        "title": "Power",
        "tip": "Kampfkraft. Entscheidet Pal-gegen-Pal-Kämpfe. Bei 0 oder weniger geht die Karte ins Grab.",
    },
    "strike": {
        "title": "Strike",
        "tip": "Schlagkraft. Schaden, den ein Angriff dem gegnerischen Spieler zufügt, wenn er durchkommt.",
    },
    "damage": {
        "title": "Damage",
        "tip": "Schaden durch Fähigkeiten. Kein Kampfschaden, außer der Kartentext sagt etwas anderes.",
    },
    "assault": {
        "title": "Assault",
        "tip": "Diese Karte kann Pals im Stand-Zustand angreifen. Normalerweise sind nur gerestete Pals gültige Angriffsziele.",
    },
    "taunt": {
        "title": "Taunt",
        "tip": "Dein Gegner darf keine anderen Ziele angreifen, solange eine Karte mit Taunt als Angriffsziel gewählt werden kann.",
    },
    "stealth": {
        "title": "Stealth",
        "tip": "Diese Karte kann nicht geblockt werden.",
    },
    "interrupt": {
        "title": "Interrupt",
        "tip": "Quick aus der Hand. [①, diese Karte abwerfen] oder [diese Karte und 1 andere Karte aus der Hand abwerfen]: Die Attacke des Gegners wird zunichte, es entsteht kein Kampfschaden.",
    },
    "vigilance": {
        "title": "Vigilance",
        "tip": "Am Ende deines Zuges wird diese Karte aufgerichtet (stand). Sie kann also angreifen und danach wieder blocken.",
    },
    "breakthrough": {
        "title": "Breakthrough",
        "tip": "Wenn der gegnerische Kampf-Pal während des Angriffs dieser Karte ins Grab geht, erleidet der gegnerische Spieler zusätzlich Damage.",
    },
    "retaliate": {
        "title": "Retaliate",
        "tip": "Wenn diese Karte im Kampf ins Grab gelegt wird, kommt der gegnerische Kampf-Pal ebenfalls ins Grab.",
    },
    "brave": {
        "title": "Brave N",
        "tip": "On Attack: Diese Karte bekommt Power +N bis zum Ende des Zuges.",
    },
    "serious": {
        "title": "Serious N",
        "tip": "On Assign: Wähle 1 Pal. Er bekommt Power +N bis zum Ende des Zuges.",
    },
}

# Card-face labels (types, colors, elements, work suitability) from Comprehensive Rules 1.00.
# Catalog aliases: Thunder=Electric, Earth=Ground, None=Neutral.
TERMS: dict[str, dict[str, str]] = {
    "pal": {
        "title": "Pal",
        "tip": "Kartentyp. Kreaturen, die du auf die Base bringst — zum Helfen oder zum Angreifen. Ohne Extra-Zone meint „Pal“ eine Pal-Karte auf der Base. Limit: 5 Pals auf der Base.",
    },
    "luckypal": {
        "title": "Lucky Pal",
        "tip": "Pal mit Subtyp Lucky — zählt gleichzeitig als Pal und Lucky Pal. Maximal 8 Karten mit Lucky-Pal-Icon im 50er-Hauptdeck. Wenn Spielerschaden Karten vom Deck ins Grab legt und eine davon das Lucky-Pal-Icon hat, endet die Auflösung: der Schaden wird auf 0 gesetzt.",
    },
    "normalpal": {
        "title": "Normal Pal",
        "tip": "Pal mit Subtyp Normal — zählt gleichzeitig als Pal und Normal Pal. Das ist der Standard-Pal ohne Lucky-Icon.",
    },
    "structure": {
        "title": "Structure",
        "tip": "Kartentyp. Gebäude, die du auf deine Base bringst, um dir oder deinen Pals zu helfen. Power heißt bei Structures Durability. Pals auf der Base kannst du einer Structure zuweisen (Assign).",
    },
    "gear": {
        "title": "Gear",
        "tip": "Kartentyp. Ausrüstung, die du ins Spiel bringst, um deine Pals zu unterstützen. Ohne Extra-Zone meint „Gear“ eine Gear-Karte auf der Base.",
    },
    "event": {
        "title": "Event",
        "tip": "Kartentyp. Einmalkarten mit eigenem Effekt. Nach dem Auflösen gehen sie ins Grab, sofern nichts anderes auf der Karte steht.",
    },
    "soul": {
        "title": "Soul",
        "tip": "Kartentyp. Ressourcen, mit denen du Aktionen im Spiel bezahlst. Zu Spielbeginn bis zu 10 Souls. Souls liegen nicht im 50er-Hauptdeck.",
    },
    "red": {
        "title": "Red",
        "tip": "Kartenfarbe. Die vier Farben sind Rot, Blau, Grün und Lila. Die Farbe siehst du an der Hintergrundfarbe der Cost.",
    },
    "blue": {
        "title": "Blue",
        "tip": "Kartenfarbe. Die vier Farben sind Rot, Blau, Grün und Lila. Die Farbe siehst du an der Hintergrundfarbe der Cost.",
    },
    "green": {
        "title": "Green",
        "tip": "Kartenfarbe. Die vier Farben sind Rot, Blau, Grün und Lila. Die Farbe siehst du an der Hintergrundfarbe der Cost.",
    },
    "purple": {
        "title": "Purple",
        "tip": "Kartenfarbe. Die vier Farben sind Rot, Blau, Grün und Lila. Die Farbe siehst du an der Hintergrundfarbe der Cost.",
    },
    "colorless": {
        "title": "Colorless",
        "tip": "Keine Farbe zugewiesen. Colorless ist keine eigene Farbe — die Karte hat schlicht keine der vier Farben Rot, Blau, Grün, Lila.",
    },
    "neutral": {
        "title": "Neutral",
        "tip": "Element (im Katalog oft „None“). Neutral ist ein Element, nicht „kein Element“.",
    },
    "fire": {
        "title": "Fire",
        "tip": "Element. Wird als Icon gedruckt. Karteneffekte können ein Element nennen oder vergleichen.",
    },
    "water": {
        "title": "Water",
        "tip": "Element. Wird als Icon gedruckt. Karteneffekte können ein Element nennen oder vergleichen.",
    },
    "grass": {
        "title": "Grass",
        "tip": "Element. Wird als Icon gedruckt. Karteneffekte können ein Element nennen oder vergleichen.",
    },
    "electric": {
        "title": "Electric",
        "tip": "Element (im Katalog oft „Thunder“). Wird als Icon gedruckt. Karteneffekte können ein Element nennen oder vergleichen.",
    },
    "ground": {
        "title": "Ground",
        "tip": "Element (im Katalog oft „Earth“). Wird als Icon gedruckt. Karteneffekte können ein Element nennen oder vergleichen.",
    },
    "ice": {
        "title": "Ice",
        "tip": "Element. Wird als Icon gedruckt. Karteneffekte können ein Element nennen oder vergleichen.",
    },
    "dark": {
        "title": "Dark",
        "tip": "Element. Wird als Icon gedruckt. Karteneffekte können ein Element nennen oder vergleichen.",
    },
    "dragon": {
        "title": "Dragon",
        "tip": "Element. Wird als Icon gedruckt. Karteneffekte können ein Element nennen oder vergleichen.",
    },
    "worksuitability": {
        "title": "Work Suitability",
        "tip": "Arbeitseignung des Pals. Steht ein Name in ≪Klammern≫ oder Anführungszeichen im Effekt, ist genau diese Eignung gemeint.",
    },
}

_WORK_NAMES = (
    "Kindling", "Watering", "Planting", "Generating Electricity", "Handiwork",
    "Gathering", "Lumbering", "Mining", "Medicine Production", "Cooling",
    "Transporting", "Farming", "Collecting", "Crafting", "Electricity", "Harvesting",
)
for _name in _WORK_NAMES:
    _key = re.sub(r"[^a-z0-9]+", "", _name.casefold())
    TERMS[_key] = {
        "title": _name,
        "tip": (
            f"Work Suitability ≪{_name}≫. Karteneffekte, die diesen Namen in Klammern oder "
            "Anführungszeichen nennen, meinen genau diese Eignung."
        ),
    }

ALIASES = {
    "luckypal": "luckypal",
    "lucky pal": "luckypal",
    "normalpal": "normalpal",
    "normal pal": "normalpal",
    "thunder": "electric",
    "earth": "ground",
    "none": "neutral",
    "work suitability": "worksuitability",
    "aptitude": "worksuitability",
    "aptitudes": "worksuitability",
}

GLOSSARY_SECTIONS = (
    ("Kartentypen", ("pal", "luckypal", "normalpal", "structure", "gear", "event", "soul")),
    ("Farbe", ("red", "blue", "green", "purple", "colorless")),
    ("Element", ("neutral", "fire", "water", "grass", "electric", "ground", "ice", "dark", "dragon")),
    ("Work Suitability", ("worksuitability", "kindling", "cooling", "crafting", "electricity",
                          "farming", "harvesting", "collecting", "transporting")),
    ("Schlüsselwörter", tuple(KEYWORDS)),
)

ICON_KEYS = {
    "act", "auto", "cont", "ondeploy", "onattack", "onassign",
    "quick", "hand", "1turn", "ingredient", "material",
    "power", "strike", "damage",
}

WORD_RE = re.compile(
    r"\b(Assault|Taunt|Stealth|Interrupt|Vigilance|Breakthrough|Retaliate|"
    r"Brave(?:\s+\d+)?|Serious(?:\s+\d+)?)\b",
    re.I,
)
KEY_STRIP_RE = re.compile(r"[^a-z0-9]+")


def compact_key(label: str) -> str:
    raw = (label or "").replace("≪", "").replace("≫", "").replace("«", "").replace("»", "")
    compact = KEY_STRIP_RE.sub("", raw.casefold())
    aliased = ALIASES.get(raw.strip().casefold(), ALIASES.get(compact, compact))
    return aliased


def lookup_term(label: str) -> tuple[str, dict[str, str]] | None:
    key = compact_key(label)
    info = TERMS.get(key) or KEYWORDS.get(key)
    if not info:
        return None
    return key, info


def _kw_markup(key: str, title: str, tip: str, inner: Markup | str, extra_class: str = "") -> Markup:
    cls = "kw" + (f" {extra_class}" if extra_class else "")
    body = inner if isinstance(inner, Markup) else escape(inner)
    return Markup(
        f'<a class="{cls}" href="/glossar#{escape(key)}" data-kw="{escape(key)}" '
        f'data-title="{escape(title)}" data-tip="{escape(tip)}">{body}</a>'
    )


def wrap_term(label: str, extra_class: str = "", display: str | None = None) -> Markup:
    shown = display if display is not None else label
    found = lookup_term(label)
    if not found:
        return escape(shown)
    key, info = found
    return _kw_markup(key, info["title"], info["tip"], shown, extra_class)


def term_pill(label: str, extra_class: str = "", display: str | None = None) -> Markup:
    return wrap_term(label, extra_class=extra_class, display=display)


def terms_for_client() -> dict[str, dict[str, str]]:
    payload: dict[str, dict[str, str]] = {}
    for key, info in {**KEYWORDS, **TERMS}.items():
        item = {"key": key, "title": info["title"], "tip": info["tip"]}
        payload[key] = item
    for alias, key in ALIASES.items():
        if key in payload:
            compact = KEY_STRIP_RE.sub("", alias)
            payload[alias] = payload[key]
            if compact:
                payload[compact] = payload[key]
    return payload


def glossary_sections() -> list[dict[str, object]]:
    sections = []
    for title, keys in GLOSSARY_SECTIONS:
        items = []
        for key in keys:
            info = TERMS.get(key) or KEYWORDS.get(key)
            if not info:
                continue
            items.append({"key": key, "title": info["title"], "tip": info["tip"]})
        if items:
            sections.append({"title": title, "entries": items})
    return sections


def wrap_word(word: str) -> Markup:
    key = re.sub(r"\s+\d+$", "", word).casefold()
    info = KEYWORDS.get(key)
    if not info:
        return escape(word)
    title = info["title"]
    num = re.search(r"\d+", word)
    if num and key in ("brave", "serious"):
        title = f"{key.capitalize()} {num.group(0)}"
    return _kw_markup(key, title, info["tip"], word)


def wrap_text(text: str) -> Markup:
    parts: list[Markup | str] = []
    last = 0
    for match in WORD_RE.finditer(text):
        parts.append(escape(text[last : match.start()]))
        parts.append(wrap_word(match.group(1)))
        last = match.end()
    parts.append(escape(text[last:]))
    return Markup("").join(parts)


def wrap_icon(inner: Markup, key: str) -> Markup:
    info = KEYWORDS.get(key)
    if not info:
        return inner
    return _kw_markup(key, info["title"], info["tip"], inner, "kw-icon")
