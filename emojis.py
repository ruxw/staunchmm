"""Centralized Telegram custom emoji configuration.
Supports custom emoji IDs formatted via Telegram HTML: <tg-emoji emoji-id="...">fallback</tg-emoji>
If an emoji ID is not configured (empty or None), gracefully falls back to standard Unicode emoji.
"""
from typing import Dict, Optional

# Custom Emoji IDs (Telethon / Telegram Bot API custom emoji document IDs)
CUSTOM_EMOJI_IDS: Dict[str, str] = {
    "SUCCESS": "5206607081334906820",
    "WARNING": "5447644880824181073",
    "CLOCK": "5382194935057372936",
    "HOLD": "5429405838345265327",
    "RELEASE": "5291873529464122510",
    "SETTINGS": "5258096772776991776",
    "CLOSE": "5472163152604975299",
    "BUYER": "6192946892091956588",
    "SELLER": "5445221832074483553",
    "MONEY": "5409048419211682843",
    "PIN": "5397782960512444700",
    "SHIELD": "5197288647275071607",
    "CHANNEL": "5424818078833715060",
    "VOUCH": "5438496463044752972",
    "STATS": "5231200819986047254",
    "REF": "5469741319330996757",
    "CHECK": "5355136748466747648",
    "CROSS": "5210952531676504517",
    "DEALS": "5357080225463149588",
    "USERS": "6032594876506312598",
    "USER": "6032693626394382504",
    "CHAT": "5429411030960711866",


    "LINK": "5271604874419647061",
    "CARD": "5445353829304387411",
    "COIN": "5197434882321567830",
    "CASH": "5375438457579540146",
    "CELEBRATE": "5235711785482341993",
    "REFRESH": "5244758760429213978",
    "DOC": "5395444784611480792",
    "BELL": "5458603043203327669",
    "MEMO": "5395444784611480792",
    "HOURGLASS": "5175181110572745347",
    "GIFT": "5203996991054432397",
    "WAVE": "5472055112702629499",
    "POINT": "5469718869536940860",
    "SCROLL": "6041777576714702813",
    "GLOBE": "5447602197439218445",
    "INBOX": "5116187449839584152",

    # --- Not set yet: paste a custom emoji ID to enable. Empty = normal emoji is shown. ---
    "EDIT": "5334673106202010226",
    "BACK": "5447506720316225765",
    "NEXT": "5445350109862720603",
    "CAMERA": "5235837920081887219",
    "BOX": "5996720655360332940",
    "TROPHY": "5244590801438138696",
    "MAIL": "5472239203590888751",
    "SENT": "5350421256627838238",
    "TAG": "6334731055387378962",
    "EYE": "5431472860075943310",
    "REPLY": "5895507195524550741",
    "SKIP": "5248995135781363257",
    "EXCHANGE": "5377336227533969892",
}

# Standard Unicode Fallbacks
FALLBACK_EMOJIS: Dict[str, str] = {
    "SUCCESS": "✅",
    "WARNING": "⚠️",
    "CLOCK": "⏱️",
    "HOLD": "🔒",
    "RELEASE": "🔓",
    "SETTINGS": "⚙️",
    "CLOSE": "🚪",
    "BUYER": "🛒",
    "SELLER": "💼",
    "MONEY": "💰",
    "PIN": "📌",
    "SHIELD": "🛡️",
    "CHANNEL": "📢",
    "VOUCH": "⭐️",
    "STATS": "📊",
    "REF": "💫",
    "CHECK": "✓",
    "CROSS": "❌",
    "DEALS": "🤝",
    "USERS": "👥",
    "USER": "👤",
    "CHAT": "💬",
    "LINK": "🔗",
    "CARD": "💳",
    "COIN": "🪙",
    "CASH": "💵",
    "CELEBRATE": "🎉",
    "REFRESH": "🔄",
    "DOC": "📋",
    "BELL": "🔔",
    "MEMO": "📝",
    "HOURGLASS": "⏳",
    "GIFT": "🎁",
    "WAVE": "👋",
    "POINT": "👆",
    "SCROLL": "📜",
    "GLOBE": "🌐",
    "INBOX": "📥",
    "EDIT": "✏️",
    "BACK": "⬅️",
    "NEXT": "➡️",
    "CAMERA": "📸",
    "BOX": "📦",
    "TROPHY": "🏆",
    "MAIL": "✉️",
    "SENT": "📨",
    "TAG": "🏷️",
    "EYE": "👁️",
    "REPLY": "↩️",
    "SKIP": "⏩",
    "EXCHANGE": "💱",
}

# Extra plain emoji that should map to an existing slot (besides its own fallback)
_ALIASES: Dict[str, str] = {
    "📄": "DOC", "🛡": "SHIELD", "⏱": "CLOCK", "⭐": "VOUCH", "🌟": "VOUCH",
}


def get_emoji(name: str, fallback: Optional[str] = None) -> str:
    """Returns HTML <tg-emoji> tag if custom emoji ID is configured, else fallback Unicode."""
    fb = fallback or FALLBACK_EMOJIS.get(name, "")
    cid = CUSTOM_EMOJI_IDS.get(name, "").strip()
    if cid:
        return f'<tg-emoji emoji-id="{cid}">{fb}</tg-emoji>'
    return fb


def get_plain_emoji(name: str, fallback: Optional[str] = None) -> str:
    """Returns plain standard Unicode emoji fallback without HTML tags."""
    return fallback or FALLBACK_EMOJIS.get(name, "")


def get_custom_id(name: str) -> Optional[str]:
    """Returns the custom emoji ID for native button icon_custom_emoji_id."""
    cid = CUSTOM_EMOJI_IDS.get(name, "").strip()
    return cid or None


# Descriptive constant properties / helpers
EMOJI_SUCCESS = get_emoji("SUCCESS")
EMOJI_WARNING = get_emoji("WARNING")
EMOJI_CLOCK = get_emoji("CLOCK")
EMOJI_HOLD = get_emoji("HOLD")
EMOJI_RELEASE = get_emoji("RELEASE")
EMOJI_SETTINGS = get_emoji("SETTINGS")
EMOJI_CLOSE = get_emoji("CLOSE")
EMOJI_BUYER = get_emoji("BUYER")
EMOJI_SELLER = get_emoji("SELLER")
EMOJI_MONEY = get_emoji("MONEY")
EMOJI_PIN = get_emoji("PIN")
EMOJI_SHIELD = get_emoji("SHIELD")
EMOJI_CHANNEL = get_emoji("CHANNEL")
EMOJI_VOUCH = get_emoji("VOUCH")
EMOJI_STATS = get_emoji("STATS")
EMOJI_REF = get_emoji("REF")
EMOJI_CHECK = get_emoji("CHECK")
EMOJI_CROSS = get_emoji("CROSS")
EMOJI_DEALS = get_emoji("DEALS")
EMOJI_USERS = get_emoji("USERS")
EMOJI_USER = get_emoji("USER")
EMOJI_CHAT = get_emoji("CHAT")
EMOJI_LINK = get_emoji("LINK")
EMOJI_CARD = get_emoji("CARD")
EMOJI_COIN = get_emoji("COIN")
EMOJI_CASH = get_emoji("CASH")
EMOJI_CELEBRATE = get_emoji("CELEBRATE")
EMOJI_REFRESH = get_emoji("REFRESH")
EMOJI_DOC = get_emoji("DOC")
EMOJI_BELL = get_emoji("BELL")
EMOJI_MEMO = get_emoji("MEMO")
EMOJI_HOURGLASS = get_emoji("HOURGLASS")
EMOJI_GIFT = get_emoji("GIFT")
EMOJI_WAVE = get_emoji("WAVE")
EMOJI_POINT = get_emoji("POINT")
EMOJI_SCROLL = get_emoji("SCROLL")
EMOJI_GLOBE = get_emoji("GLOBE")
EMOJI_INBOX = get_emoji("INBOX")
EMOJI_EXCHANGE = get_emoji("EXCHANGE")


# ---------------------------------------------------------------------------
# Auto-conversion of plain emoji -> custom emoji (so no message / button is missed)
# ---------------------------------------------------------------------------
import re as _re

_VS16 = "\ufe0f"


def _norm(ch: str) -> str:
    return ch.replace(_VS16, "")


def _build_reverse() -> Dict[str, str]:
    rev: Dict[str, str] = {}
    for name, ch in FALLBACK_EMOJIS.items():
        if CUSTOM_EMOJI_IDS.get(name, "").strip():
            rev.setdefault(_norm(ch), name)
    for ch, name in _ALIASES.items():
        if CUSTOM_EMOJI_IDS.get(name, "").strip():
            rev.setdefault(_norm(ch), name)
    return rev


_REVERSE = _build_reverse()
_EMOJI_RE = _re.compile(
    r"(<tg-emoji\b.*?</tg-emoji>|<code>.*?</code>|<pre>.*?</pre>)"      # leave these untouched
    r"|(" + "|".join(_re.escape(k) for k in sorted(_REVERSE, key=len, reverse=True)) + r")" + _VS16 + "?",
    _re.S,
)


def emojify(html_text: str) -> str:
    """Turn every known plain emoji in an HTML string into its <tg-emoji> custom version."""
    if not html_text or not _REVERSE:
        return html_text

    def _sub(m):
        if m.group(1):
            return m.group(1)
        name = _REVERSE[m.group(2)]
        return f'<tg-emoji emoji-id="{CUSTOM_EMOJI_IDS[name].strip()}">{FALLBACK_EMOJIS[name]}</tg-emoji>'

    return _EMOJI_RE.sub(_sub, html_text)


def split_leading_emoji(text: str):
    """For buttons: '🤝 P2P' -> ('P2P', '<custom id>'). Returns (text, None) if no custom emoji matches."""
    t = (text or "").lstrip()
    for k in sorted(_REVERSE, key=len, reverse=True):
        if t.startswith(k):
            rest = t[len(k):].lstrip(_VS16).strip()
            if rest:
                return rest, CUSTOM_EMOJI_IDS[_REVERSE[k]].strip()
            break
    return text, None
