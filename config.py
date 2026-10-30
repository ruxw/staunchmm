import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv()


def _req(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v


BOT_TOKEN = _req("BOT_TOKEN")
MONGO_URI = _req("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB", "xenie_mm").strip()

API_ID = int(_req("API_ID"))
API_HASH = _req("API_HASH")
SESSION_STRING = _req("SESSION_STRING")

MM_USERNAME = os.getenv("MM_USERNAME", "xenyy").strip().lstrip("@")
MM_USER_ID = int(os.getenv("MM_USER_ID", "0").strip() or 0)
MM_USER_IDS = set()
for _part in os.getenv("MM_USER_ID", "").replace(",", " ").split():
    try:
        MM_USER_IDS.add(int(_part))
    except ValueError:
        pass
if MM_USER_ID:
    MM_USER_IDS.add(MM_USER_ID)

CHANNEL_URL = _req("MIDDLEMAN_CHANNEL_URL")
VOUCH_CHANNEL_URL = os.getenv("VOUCH_CHANNEL_URL", CHANNEL_URL).strip()
TOS_CHANNEL_URL = os.getenv("TOS_CHANNEL_URL", CHANNEL_URL).strip()
DEFAULT_UPI_ID = os.getenv("DEFAULT_UPI_ID", "").strip()
DEFAULT_MM_FEE = os.getenv("DEFAULT_MM_FEE", "50 INR").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

DEAL_ID_PREFIX = os.getenv("DEAL_ID_PREFIX", "x")
DISPLAY_TZ = os.getenv("DISPLAY_TZ", "Asia/Kolkata")
FOLDER_NAME = os.getenv("FOLDER_NAME", "Deals")[:12]
TAT_POLL_SECONDS = int(os.getenv("TAT_POLL_SECONDS", "15"))

SESSION_TIMEOUT_SECONDS = 10 * 60
MIN_TAT_SECONDS = 5 * 60
MAX_TAT_SECONDS = 30 * 24 * 3600
