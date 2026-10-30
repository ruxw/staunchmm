import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import escape as esc  # noqa: F401  (re-exported)
from zoneinfo import ZoneInfo

import config


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


_USERNAME_RE = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{4,31})$")


def parse_username(text: str):
    m = _USERNAME_RE.match(text.strip())
    return m.group(1) if m else None


def parse_amount(text: str) -> str:
    """Accepts '60', '₹60', '60 INR', '1,500', '$20.5'. Rejects anything ambiguous."""
    nums = re.findall(r"\d[\d,]*(?:\.\d+)?|\.\d+", text)
    if len(nums) != 1:
        raise ValueError("❌ Please enter just the amount as a number (e.g. 500 or ₹500).")
    try:
        val = Decimal(nums[0].replace(",", ""))
    except InvalidOperation:
        raise ValueError("❌ Please enter just the amount as a number (e.g. 500 or ₹500).")
    if val <= 0:
        raise ValueError("❌ The amount must be greater than zero.")
    return format(val.normalize(), "f")


_UNITS = {
    "d": 86400, "day": 86400, "days": 86400,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
}
_TAT_TOKEN = re.compile(r"\s*(\d+(?:\.\d+)?)\s*([a-z]*)\s*")
_TAT_HELP = (
    "❌ Invalid TAT duration.\n\n"
    "<b>Usage Examples:</b>\n"
    "• <code>15m</code> or <code>15mins</code>\n"
    "• <code>1h</code> or <code>2hours</code>\n"
    "• <code>1d</code> or <code>3days</code>\n"
    "• <code>1d 12h</code>"
)

MIN_TAT_SECONDS = 60  # Allow down to 1 minute as requested
MAX_TAT_SECONDS = 30 * 24 * 3600


def parse_tat(text: str) -> int:
    s = text.strip().lower().replace(",", " ").replace(" and ", " ")
    if not s:
        raise ValueError(_TAT_HELP)
    pos, total = 0, 0.0
    while pos < len(s):
        m = _TAT_TOKEN.match(s, pos)
        if not m or m.end() == pos:
            raise ValueError(_TAT_HELP)
        num, unit = m.groups()
        unit = unit or "h"
        if unit not in _UNITS:
            raise ValueError(_TAT_HELP)
        val = float(num)
        if val <= 0:
            raise ValueError("❌ TAT duration must be greater than zero.")
        total += val * _UNITS[unit]
        pos = m.end()
    secs = int(total)
    if secs < MIN_TAT_SECONDS:
        raise ValueError("❌ TAT is too short. The minimum is 1 minute (1m).")
    if secs > MAX_TAT_SECONDS:
        raise ValueError("❌ TAT is too long. The maximum is 30 days.")
    return secs


def fmt_duration(seconds) -> str:
    seconds = int(seconds)
    parts = []
    for name, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        n, seconds = divmod(seconds, size)
        if n:
            parts.append(f"{n} {name}{'s' if n != 1 else ''}")
    return " ".join(parts) or "less than a minute"


def fmt_dt(dt: datetime) -> str:
    return dt.astimezone(ZoneInfo(config.DISPLAY_TZ)).strftime("%d %b %Y, %I:%M %p %Z")


def get_currency_symbol(curr: str) -> str:
    c = (curr or "").strip().upper()
    mapping = {
        "USD": "$",
        "$": "$",
        "INR": "₹",
        "₹": "₹",
        "RS": "₹",
        "EUR": "€",
        "€": "€",
        "GBP": "£",
        "£": "£",
        "USDT": "USDT",
        "BTC": "BTC",
        "ETH": "ETH",
        "SOL": "SOL",
        "TON": "TON",
    }
    return mapping.get(c, c or "$")


def user_mention(user_id: int, username: str = None, first_name: str = None) -> str:
    """Returns @username or clickable HTML user link if no username."""
    if username:
        return f"@{esc(username.lstrip('@'))}"
    name = esc(first_name or f"User {user_id}")
    return f'<a href="tg://user?id={user_id}">{name}</a>'


class _SafeDict(dict):
    def __missing__(self, key):
        return f"{{{key}}}"


def safe_format(template: str, **kwargs) -> str:
    """Formats string safely without throwing KeyError for missing or unknown placeholders."""
    try:
        return template.format_map(_SafeDict(**kwargs))
    except Exception:
        # Fallback regex substitution
        out = template
        for k, v in kwargs.items():
            out = out.replace(f"{{{k}}}", str(v))
        return out
