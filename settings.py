"""Dynamic settings and configurable templates module for Middleman Bot.
Stored in MongoDB 'settings' collection and cached in-memory for instant access.
All values and templates can be edited, previewed, and reset by the middleman via /settings.
"""
import logging
from typing import Any, Dict

import config
import emojis
from utils import get_currency_symbol, safe_format

log = logging.getLogger(__name__)

# List of 26 Supported Cryptocurrencies & Networks
CRYPTO_NETWORKS = {
    "usdt_trc20": {"name": "USDT", "network": "Tron (TRC-20)", "symbol": "USDT-TRC20"},
    "usdt_bep20": {"name": "USDT", "network": "BNB Smart Chain (BEP-20)", "symbol": "USDT-BEP20"},
    "usdt_erc20": {"name": "USDT", "network": "Ethereum (ERC-20)", "symbol": "USDT-ERC20"},
    "usdt_ton": {"name": "USDT", "network": "TON Network", "symbol": "USDT-TON"},
    "usdt_sol": {"name": "USDT", "network": "Solana (SPL)", "symbol": "USDT-SOL"},
    "btc": {"name": "Bitcoin", "network": "Bitcoin Core", "symbol": "BTC"},
    "eth": {"name": "Ethereum", "network": "Ethereum Mainnet", "symbol": "ETH"},
    "sol": {"name": "Solana", "network": "Solana Mainnet", "symbol": "SOL"},
    "ton": {"name": "Toncoin", "network": "TON Mainnet", "symbol": "TON"},
    "ltc": {"name": "Litecoin", "network": "Litecoin Core", "symbol": "LTC"},
    "trx": {"name": "Tron", "network": "Tron Network", "symbol": "TRX"},
    "bnb": {"name": "BNB", "network": "BNB Smart Chain (BEP-20)", "symbol": "BNB"},
    "xrp": {"name": "Ripple", "network": "XRP Ledger", "symbol": "XRP"},
    "doge": {"name": "Dogecoin", "network": "Dogecoin Network", "symbol": "DOGE"},
    "matic": {"name": "Polygon (POL)", "network": "Polygon PoS", "symbol": "POL/MATIC"},
    "avax": {"name": "Avalanche", "network": "AVAX C-Chain", "symbol": "AVAX"},
    "xmr": {"name": "Monero", "network": "Monero Network", "symbol": "XMR"},
    "ada": {"name": "Cardano", "network": "Cardano Network", "symbol": "ADA"},
    "dot": {"name": "Polkadot", "network": "Polkadot Relay", "symbol": "DOT"},
    "near": {"name": "NEAR Protocol", "network": "NEAR Mainnet", "symbol": "NEAR"},
    "bch": {"name": "Bitcoin Cash", "network": "Bitcoin Cash", "symbol": "BCH"},
    "sui": {"name": "Sui", "network": "Sui Mainnet", "symbol": "SUI"},
    "apt": {"name": "Aptos", "network": "Aptos Mainnet", "symbol": "APT"},
    "arb": {"name": "Arbitrum", "network": "Arbitrum One (ERC-20)", "symbol": "ARB"},
    "base": {"name": "Base ETH", "network": "Base Network", "symbol": "BASE"},
    "usdc": {"name": "USDC", "network": "Multi-Chain (ERC-20/SPL)", "symbol": "USDC"},
}

GC_NAME_PRESETS = [
    "Deal {label} | @{mm}",
    "🤝 {label} • @{buyer} x @{seller}",
    "🛡️ Escrow {label} | @{mm}",
    "Deal {label} ({amount}) | @{mm}",
    "Deal #{startno} | @{mm}",
]

# Configurable Message Templates with Sensible Defaults
DEFAULT_TEMPLATES: Dict[str, str] = {
    "deal_creation": (
        f"{emojis.EMOJI_DEALS} <b>Welcome, everyone!</b>\n\n"
        "@{mm} will be handling this deal as the middleman.\n"
        "Please follow their instructions throughout the process."
    ),
    "payment_confirmed": (
        f"{emojis.EMOJI_SUCCESS} Payment confirmed by the middleman.\n\n"
        "Buyer and seller may now begin their respective work, either in DMs or here in the deal group."
    ),
    "tat_notification": (
        "<b>Deal Stat</b>\n\n"
        "Buyer: {buyer}\n"
        "Seller: {seller}\n"
        "Amount: {amount} {currency} | TAT: {tat}\n"
        "Timer: {timer}"
    ),
    "tat_extension": (
        f"{emojis.EMOJI_CLOCK} <b>TAT Extended by {{duration}}!</b>\n\n"
        f"{emojis.EMOJI_HOURGLASS} <b>New Deadline:</b> <b>{{deadline}}</b>\n"
        "Middleman @{mm} has updated the turnaround time."
    ),
    "tat_expiration": (
        f"{emojis.EMOJI_CLOCK} <b>TAT is Over!</b>\n\n"
        "The turnaround time ({tat}) for <b>Deal #{deal_id}</b> has expired.\n\n"
        f"{emojis.EMOJI_BUYER} <b>Buyer:</b> {{buyer}}\n"
        f"{emojis.EMOJI_SELLER} <b>Seller:</b> {{seller}}\n"
        f"{emojis.EMOJI_SHIELD} <b>Middleman:</b> @{{mm}}\n\n"
        "{{buyer}}, please confirm if {{seller}} has delivered the product/service. @{{mm}} please review and take necessary action."
    ),
    "hold": (
        f"{emojis.EMOJI_HOLD} <b>Deal Put on Hold</b>\n\n"
        "Middleman @{mm} has placed Deal #{deal_id} on hold.\n"
        "Group title updated to: <code>{title}</code>"
    ),
    "release": (
        f"{emojis.EMOJI_RELEASE} <b>Deal Released</b>\n\n"
        "Middleman @{mm} has released Deal #{deal_id}.\n"
        "Group title updated to: <code>{title}</code>"
    ),
    "deal_closure": (
        f"{emojis.EMOJI_CLOSE} <b>Deal Closed #{{deal_id}}</b>\n\n"
        "This deal has been formally closed by Middleman @{mm}.\n"
        "Participants have been muted and invitations revoked."
    ),
    "vouch": "Vouch @{mm} for MM'd {amount} {currency}",
}

TEMPLATE_LABELS: Dict[str, str] = {
    "deal_creation": "Deal Creation Welcome",
    "payment_confirmed": "Payment Confirmed (/begin)",
    "tat_notification": "TAT Countdown Card",
    "tat_extension": "TAT Extension Message",
    "tat_expiration": "TAT Expiration Notice",
    "hold": "Deal Hold Message (/hold)",
    "release": "Deal Release Message (/release)",
    "deal_closure": "Deal Closure Message (/close)",
    "vouch": "Vouch Format Template",
}

# In-memory cache
_cache: Dict[str, Any] = {}


def _get_defaults() -> Dict[str, Any]:
    return {
        "mm_channel_url": config.CHANNEL_URL,
        "vouch_channel_url": config.VOUCH_CHANNEL_URL,
        "tos_channel_url": config.TOS_CHANNEL_URL,
        "upi_id": config.DEFAULT_UPI_ID,
        "upi_name": f"{config.MM_USERNAME} Escrow",
        "default_fee": config.DEFAULT_MM_FEE,
        "gc_name_template": GC_NAME_PRESETS[0],
        "gc_photo_file_id": None,
        "gc_start_num": None,
        "gc_baseline_deal_no": None,
        "templates": dict(DEFAULT_TEMPLATES),
        "crypto_wallets": {},
        "active_ad": {"text": "", "enabled": False},
    }


async def init_settings():
    """Load settings from MongoDB into cache, backfilled with defaults."""
    import database as db

    defaults = _get_defaults()
    try:
        doc = await db.settings.find_one({"_id": "app_settings"})
        if not doc:
            await db.settings.replace_one({"_id": "app_settings"}, defaults, upsert=True)
            _cache.update(defaults)
        else:
            merged = {**defaults, **doc}
            # Deep merge templates
            saved_templates = dict(defaults.get("templates", {}))
            if "templates" in doc and isinstance(doc["templates"], dict):
                # Upgrade old multi-line template to concise format if not custom-edited
                old_vouch = doc["templates"].get("vouch", "")
                if "Vouch Channel:" in old_vouch or "Completed Successfully" in old_vouch:
                    doc["templates"]["vouch"] = DEFAULT_TEMPLATES["vouch"]
                saved_templates.update(doc["templates"])
            merged["templates"] = saved_templates
            _cache.update(merged)
        log.info("Settings loaded into memory successfully")
    except Exception as e:
        log.warning("Could not load settings from DB; using defaults: %s", e)
        _cache.update(defaults)


def get(key: str, default: Any = None) -> Any:
    return _cache.get(key, default if default is not None else _get_defaults().get(key))


async def set_setting(key: str, value: Any):
    import database as db

    _cache[key] = value
    try:
        await db.settings.update_one(
            {"_id": "app_settings"},
            {"$set": {key: value}},
            upsert=True,
        )
    except Exception as e:
        log.error("Failed to persist setting '%s': %s", key, e)


# ---------------------------------------------------------------- Advertisements
def get_ad() -> Dict[str, Any]:
    return _cache.get("active_ad") or {"text": "", "enabled": False}


async def set_ad(text: str, enabled: bool = True):
    val = {"text": (text or "").strip(), "enabled": bool(enabled)}
    await set_setting("active_ad", val)


# ---------------------------------------------------------------- Templates
def get_template(name: str) -> str:
    templates = _cache.get("templates", {})
    return templates.get(name) or DEFAULT_TEMPLATES.get(name, "")


async def set_template(name: str, content: str):
    templates = dict(_cache.get("templates", {}))
    templates[name] = content
    await set_setting("templates", templates)


async def reset_template(name: str):
    default_tmpl = DEFAULT_TEMPLATES.get(name, "")
    await set_template(name, default_tmpl)


def render_template(name: str, **kwargs) -> str:
    raw = get_template(name)
    kwargs.setdefault("mm", config.MM_USERNAME)
    kwargs.setdefault("channel_url", get("mm_channel_url", config.CHANNEL_URL))
    kwargs.setdefault("vouch_channel", get("vouch_channel_url", config.CHANNEL_URL))
    return safe_format(raw, **kwargs)


def preview_template(name: str) -> str:
    sample_data = {
        "deal_id": "1042",
        "deal_no": "1042",
        "buyer": "@buyer_sample",
        "seller": "@seller_sample",
        "currency": "$",
        "amount": "250",
        "tat": "24 hours",
        "deadline": "24 Oct 2026, 06:00 PM IST",
        "timer": "23h 59m",
        "duration": "1 hour",
        "title": "MM 1042 $ hold",
        "deal_type": "Instagram Account 50k",
        "mm": config.MM_USERNAME,
        "vouch_channel": get("vouch_channel_url", config.CHANNEL_URL),
        "channel_url": get("mm_channel_url", config.CHANNEL_URL),
    }
    return render_template(name, **sample_data)


# ---------------------------------------------------------------- Cryptos
async def set_crypto_wallet(coin_key: str, address: str):
    wallets = dict(_cache.get("crypto_wallets", {}))
    wallets[coin_key] = address.strip()
    await set_setting("crypto_wallets", wallets)


def get_crypto_wallet(coin_key: str) -> str:
    wallets = _cache.get("crypto_wallets", {})
    return wallets.get(coin_key, "")


# ---------------------------------------------------------------- Helpers
def render_gc_title(
    label: str = "",
    buyer: str = "Buyer",
    seller: str = "Seller",
    amount: str = "",
    deal_no: Any = None,
    **kwargs,
) -> str:
    import re
    tmpl = get("gc_name_template", GC_NAME_PRESETS[0])

    # Determine internal deal_no
    internal_no = None
    if isinstance(deal_no, int):
        internal_no = deal_no
    elif isinstance(deal_no, str) and deal_no.isdigit():
        internal_no = int(deal_no)
    elif label:
        m = re.search(r"\d+", label)
        if m:
            internal_no = int(m.group(0))

    start_num = get("gc_start_num")
    baseline = get("gc_baseline_deal_no")
    if start_num is not None and baseline is not None and internal_no is not None:
        diff = max(0, internal_no - baseline)
        display_num = start_num + diff
    else:
        display_num = internal_no if internal_no is not None else 1

    title = safe_format(
        tmpl,
        label=label or f"#{internal_no or 1}",
        mm=config.MM_USERNAME,
        buyer=buyer.lstrip("@"),
        seller=seller.lstrip("@"),
        amount=amount,
        startno=display_num,
        **kwargs,
    )
    return title[:120]


def render_vouch(deal: dict) -> str:
    amt = str(deal.get("amount", "0"))
    curr = str(deal.get("currency") or "").strip()
    return render_template(
        "vouch",
        deal_id=str(deal.get("deal_no", "")),
        deal_type=deal.get("purpose") or deal.get("deal_type") or "P2P Deal",
        amount=amt,
        currency=curr,
        curr_sym=get_currency_symbol(curr or "$"),
        buyer=deal.get("buyer_username") or "Anonymous",
        seller=deal.get("seller_username") or "Anonymous",
        vouch_channel=get("vouch_channel_url", config.CHANNEL_URL),
        mm=config.MM_USERNAME,
    )
