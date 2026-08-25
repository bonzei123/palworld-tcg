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


def wrap_word(word: str) -> Markup:
    key = re.sub(r"\s+\d+$", "", word).casefold()
    info = KEYWORDS.get(key)
    if not info:
        return escape(word)
    title = info["title"]
    num = re.search(r"\d+", word)
    if num and key in ("brave", "serious"):
        title = f"{key.capitalize()} {num.group(0)}"
    return Markup(
        f'<span class="kw" data-kw="{escape(key)}" data-title="{escape(title)}" '
        f'data-tip="{escape(info["tip"])}" tabindex="0" role="button">{escape(word)}</span>'
    )


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
    return Markup(
        f'<span class="kw kw-icon" data-kw="{escape(key)}" data-title="{escape(info["title"])}" '
        f'data-tip="{escape(info["tip"])}" tabindex="0" role="button">{inner}</span>'
    )
