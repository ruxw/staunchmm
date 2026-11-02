"""AI-powered and deterministic NLP deal details parser.
Extracts deal type, turnaround time (TAT), conditions, amount, currency, and payment network.
Supports Google Gemini REST API with robust local fallback.
"""
import json
import logging
import re
from typing import Any, Dict, Optional

import httpx

import config
from utils import parse_tat

log = logging.getLogger(__name__)

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"


async def parse_deal_details(text: str) -> Optional[Dict[str, Any]]:
    """Attempts AI parsing if GEMINI_API_KEY is configured; falls back to deterministic NLP parser."""
    if config.GEMINI_API_KEY:
        try:
            res = await _call_gemini(text)
            if res and res.get("amount") and res.get("deal_type"):
                return res
        except Exception as e:
            log.warning("Gemini AI parse failed or timed out, falling back to local NLP: %s", e)

    return _parse_locally(text)


async def _call_gemini(text: str) -> Optional[Dict[str, Any]]:
    url = f"{GEMINI_ENDPOINT}?key={config.GEMINI_API_KEY}"
    prompt = (
        "You are an escrow middleman assistant parsing deal information. "
        "Extract the deal details from the text below and return ONLY valid JSON matching this schema:\n"
        "{\n"
        '  "deal_type": "<what is being traded>",\n'
        '  "tat": "<turnaround time string, e.g. 24h, 2d, 1h>",\n'
        '  "conditions": "<terms, rules or TOS channel link, or \'None\'>",\n'
        '  "amount": "<numeric amount, e.g. 500, 1500.5>",\n'
        '  "currency": "<INR, USD, USDT, BTC, ETH, SOL, TON, or Crypto>",\n'
        '  "payment_network": "<UPI, or Crypto network like TRC20, BEP20, etc.>"\n'
        "}\n\n"
        f"Input text:\n{text}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }

    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.post(url, json=payload)
        if r.status_code == 200:
            data = r.json()
            raw_json = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(raw_json)
            _normalize_fields(parsed)
            return parsed
    return None


def _parse_locally(text: str) -> Optional[Dict[str, Any]]:
    """Smart deterministic extraction based on regex & line-by-line keywords."""
    clean = text.strip()
    if not clean:
        return None

    deal_type = None
    tat_str = "24h"
    conditions = "None"
    amount = None
    currency = "INR"
    network = "UPI"

    lines = [l.strip() for l in clean.splitlines() if l.strip()]

    for line in lines:
        lower = line.lower()

        # Deal Type
        if any(lower.startswith(k) for k in ("deal type:", "type:", "item:", "trading:", "product:", "service:")):
            deal_type = re.sub(r"^(deal type|type|item|trading|product|service):\s*", "", line, flags=re.I).strip()
        # TAT
        elif any(lower.startswith(k) for k in ("tat:", "time:", "turnaround:", "duration:")):
            tat_str = re.sub(r"^(tat|time|turnaround|duration):\s*", "", line, flags=re.I).strip()
        # Conditions
        elif any(lower.startswith(k) for k in ("conditions:", "condition:", "terms:", "tos:", "rules:")):
            conditions = re.sub(r"^(conditions|condition|terms|tos|rules):\s*", "", line, flags=re.I).strip()
        # Amount & Fees
        elif any(lower.startswith(k) for k in ("amount & fees:", "amount:", "price:", "total:")):
            raw_amt = re.sub(r"^(amount & fees|amount|price|total):\s*", "", line, flags=re.I).strip()
            # Extract currency if mentioned in the same line
            if re.search(r"\b(usdt|crypto|btc|eth|sol|ton)\b", raw_amt, re.I):
                currency = "Crypto"
            elif re.search(r"\b(inr|₹|rs)\b", raw_amt, re.I):
                currency = "INR"
            elif re.search(r"\b(usd|\$)\b", raw_amt, re.I):
                currency = "USD"
            nums = re.findall(r"\d+(?:\.\d+)?", raw_amt.replace(",", ""))
            if nums:
                amount = nums[0]
        # Currency
        elif any(lower.startswith(k) for k in ("currency:", "curr:")):
            currency = re.sub(r"^(currency|curr):\s*", "", line, flags=re.I).strip()
        # Payment Network
        elif any(lower.startswith(k) for k in ("payment network:", "network:", "payment method:", "method:", "payment:")):
            network = re.sub(r"^(payment network|network|payment method|method|payment):\s*", "", line, flags=re.I).strip()

    # Fallbacks if format wasn't exact key:value
    if not amount:
        nums = re.findall(r"\b\d+(?:\.\d+)?\b", clean)
        if nums:
            amount = nums[0]

    if not deal_type:
        # If user just sent text, grab the first non-trivial line
        for l in lines:
            if not any(k in l.lower() for k in ("tat", "amount", "payment", "currency", "conditions")):
                deal_type = l
                break

    if not deal_type or not amount:
        return None

    out = {
        "deal_type": deal_type[:200],
        "tat": tat_str,
        "conditions": conditions[:300] if conditions else "None",
        "amount": amount,
        "currency": currency,
        "payment_network": network,
    }
    _normalize_fields(out)
    return out


def normalize_currency_and_network(currency_raw: str, network_raw: str):
    """Normalize currency and payment network strings into standard representations."""
    c = (currency_raw or "").strip()
    n = (network_raw or "").strip()

    c_low = c.lower()
    n_low = n.lower()

    # Network detection from both fields
    detected_net = None
    if any(k in n_low or k in c_low for k in ("trc20", "trc-20", "trc")):
        detected_net = "TRC-20"
    elif any(k in n_low or k in c_low for k in ("bep20", "bep-20", "bep", "bsc")):
        detected_net = "BEP-20"
    elif any(k in n_low or k in c_low for k in ("erc20", "erc-20", "erc")):
        detected_net = "ERC-20"
    elif any(k in n_low or k in c_low for k in ("ton mainnet", "ton network", "ton")):
        detected_net = "TON"
    elif any(k in n_low or k in c_low for k in ("solana", "sol mainnet", "spl")):
        detected_net = "SOL"
    elif any(k in n_low or k in c_low for k in ("upi", "gpay", "paytm", "phonepe")):
        detected_net = "UPI"
    elif any(k in n_low for k in ("bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain")):
        detected_net = "Crypto"

    # Currency normalization
    norm_cur = "INR"
    if any(k in c_low for k in ("usdt", "tether", "usd-t")) or ("usdt" in n_low and "inr" not in c_low):
        norm_cur = "USDT"
    elif any(k in c_low for k in ("btc", "bitcoin")):
        norm_cur = "BTC"
    elif any(k in c_low for k in ("eth", "ethereum")):
        norm_cur = "ETH"
    elif any(k in c_low for k in ("sol", "solana")) and "usdt" not in c_low:
        norm_cur = "SOL"
    elif any(k in c_low for k in ("ton", "toncoin")) and "usdt" not in c_low:
        norm_cur = "TON"
    elif any(k in c_low for k in ("ltc", "litecoin")):
        norm_cur = "LTC"
    elif any(k in c_low for k in ("trx", "tron")) and "usdt" not in c_low and "trc" not in c_low:
        norm_cur = "TRX"
    elif any(k in c_low for k in ("bnb", "binance")) and "usdt" not in c_low:
        norm_cur = "BNB"
    elif any(k in c_low for k in ("xrp", "ripple")):
        norm_cur = "XRP"
    elif any(k in c_low for k in ("doge", "dogecoin")):
        norm_cur = "DOGE"
    elif any(k in c_low for k in ("matic", "polygon", "pol")):
        norm_cur = "POL"
    elif any(k in c_low for k in ("usd", "$", "dollar")) and "usdt" not in c_low:
        norm_cur = "USD"
    elif "crypto" in c_low or "crypto" in n_low:
        norm_cur = "Crypto"
    elif any(k in c_low for k in ("inr", "₹", "rs", "rupee", "rupees")):
        norm_cur = "INR"
    elif c:
        norm_cur = c.upper() if len(c) <= 6 else c

    # Finalize network
    if norm_cur == "INR":
        norm_net = "UPI"
    elif detected_net:
        norm_net = detected_net
    elif n:
        norm_net = n
    else:
        norm_net = "Crypto" if norm_cur in ("USDT", "BTC", "ETH", "SOL", "TON", "Crypto") else "UPI"

    return norm_cur, norm_net


def _normalize_fields(d: Dict[str, Any]):
    tat_str = str(d.get("tat", "24h"))
    try:
        secs = parse_tat(tat_str)
    except Exception:
        secs = 24 * 3600
    d["tat_seconds"] = secs
    d["amount"] = str(d.get("amount", "0")).replace(",", "").strip()
    if not d.get("conditions"):
        d["conditions"] = "None"
    cur, net = normalize_currency_and_network(d.get("currency", "INR"), d.get("payment_network", "UPI"))
    d["currency"] = cur
    d["payment_network"] = net
