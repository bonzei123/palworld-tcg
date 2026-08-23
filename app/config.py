from pathlib import Path
import os
import secrets

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR") or os.environ.get("DATA_DIR") or (BASE_DIR / "data"))
IMAGES_DIR = DATA_DIR / "images"
RULES_DIR = DATA_DIR / "rules"
CARDLISTS_DIR = DATA_DIR / "cardlists"
PROJECT_CARDLISTS_DIR = BASE_DIR / "cardlists"
DB_PATH = DATA_DIR / "palworld.db"
SEED_DIR = Path(os.environ.get("SEED_DIR", BASE_DIR))

SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "palworld")
HTTPS_ONLY = os.environ.get("HTTPS_ONLY", "").lower() in {"1", "true", "yes"}

GEMINI_DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    RULES_DIR.mkdir(parents=True, exist_ok=True)
    CARDLISTS_DIR.mkdir(parents=True, exist_ok=True)
    PROJECT_CARDLISTS_DIR.mkdir(parents=True, exist_ok=True)
