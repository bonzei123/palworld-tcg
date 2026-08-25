from __future__ import annotations

import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.texticons import IMG_DIR, icon_key, refresh_index, save_name_for  # noqa: E402

HEADERS = {"User-Agent": "PalworldTCG-Katalog/1.0"}
HTML_DIRS = [ROOT / "cardlists", ROOT]


def collect_icons() -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    files: list[Path] = []
    for folder in HTML_DIRS:
        if folder.is_dir():
            files.extend(folder.glob("*.html"))
    for path in files:
        soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "lxml")
        for img in soup.select(".detail-txt img, .detail-img img"):
            src = (img.get("src") or "").strip()
            alt = (img.get("alt") or "").strip()
            if not src or "texticon" not in src:
                continue
            key = icon_key(alt or Path(src).stem)
            if key and key not in found:
                found[key] = (alt, src)
    return found


def main() -> None:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    existing = {p.name for p in IMG_DIR.iterdir() if p.is_file()}
    print("existing", sorted(existing))
    icons = collect_icons()
    print("unique icons", len(icons))
    downloaded = 0
    skipped = 0
    with httpx.Client(timeout=30.0, follow_redirects=True, headers=HEADERS) as client:
        for key, (alt, src) in sorted(icons.items()):
            name = save_name_for(alt, src)
            dest = IMG_DIR / name
            if dest.exists() or any(icon_key(Path(n).stem) == key for n in existing):
                skipped += 1
                print("skip", key, name)
                continue
            res = client.get(src)
            res.raise_for_status()
            dest.write_bytes(res.content)
            downloaded += 1
            existing.add(name)
            print("saved", key, name, dest.stat().st_size)
    refresh_index()
    print("done", "downloaded", downloaded, "skipped", skipped, "index", refresh_index())


if __name__ == "__main__":
    main()
