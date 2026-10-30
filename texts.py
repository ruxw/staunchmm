from html import escape as esc

import config
import emojis
import settings
from utils import fmt_dt, fmt_duration, get_currency_symbol, user_mention

MM = f"@{config.MM_USERNAME}"


def deal_label(deal) -> str:
    return f"#{config.DEAL_ID_PREFIX}{deal['deal_no']}"


def welcome() -> str:
    return (
        f"{emojis.EMOJI_SHIELD} <b>Welcome to {MM}'s Official Middleman Service</b>\n\n"
        f"{emojis.EMOJI_HOLD} Protect Your Funds, Safe and Smoothly with {MM}\n\n"
        "• Tap <b>Start Deal</b> or send /deal to initiate a deal.\n"
        "• Tap <b>Chat (if limited)</b> to message Middleman directly."
    )


def _amount(d) -> str:
    cur = str(d.get("currency", "")).strip()
    amt = str(d.get("amount", "")).strip()
    if cur:
        return f"{esc(amt)} ({esc(cur)})"
    return esc(amt)


def summary_text(d) -> str:
    return (
        f"{emojis.EMOJI_DOC} <b>Deal Summary (P2P)</b>\n\n"
        f"Buyer: @{esc(d['buyer_username'])}\n"
        f"Seller: @{esc(d['seller_username'])}\n"
        f"Item: {esc(d['purpose'])}\n"
        f"TAT: {fmt_duration(d['tat_seconds'])}\n"
        f"Amount: {_amount(d)}\n"
        f"Conditions: {esc(d['conditions'])}\n\n"
        "Note: The seller/buyer both parties must have started the bot."
    )


def request_text(d) -> str:
    role = "Buyer" if d["initiator_role"] == "buyer" else "Seller"
    return (
        "<b>New Deal Request</b>\n\n"
        f"Initiator: @{esc(d['initiator_username'])} ({role})\n\n"
        f"Deal for: {esc(d['purpose'])}\n\n"
        f"TAT: {fmt_duration(d['tat_seconds'])}\n\n"
        f"Amount: {_amount(d)}\n\n"
        f"Conditions: {esc(d['conditions'])}\n\n"
        "Do you accept this deal?"
    )


def pinned_text(d) -> str:
    deadline_str = f" (ends {fmt_dt(d['tat_deadline'])})" if d.get("tat_deadline") else ""
    return (
        f"<b>Deal {deal_label(d)}</b>\n\n"
        f"{emojis.EMOJI_BUYER} <b>Buyer:</b> @{esc(str(d.get('buyer_username', '')))}\n"
        f"{emojis.EMOJI_SELLER} <b>Seller:</b> @{esc(str(d.get('seller_username', '')))}\n\n"
        f"📦 <b>Deal for:</b> {esc(str(d.get('purpose') or d.get('deal_type') or ''))}\n\n"
        f"{emojis.EMOJI_CLOCK} <b>TAT:</b> {fmt_duration(d.get('tat_seconds', 0))}{deadline_str}\n"
        f"{emojis.EMOJI_MONEY} <b>Amount:</b> {_amount(d)}\n"
        f"📜 <b>Conditions:</b> {esc(str(d.get('conditions', 'None')))}\n\n"
        f"Note: {MM}’s middleman fee is charged separately on Deal Amount!"
    )


def mm_dm_text(d) -> str:
    return (
        "Deal has been initiated for\n\n"
        f"Buyer: @{esc(d['buyer_username'])}\n\n"
        f"Seller: @{esc(d['seller_username'])}\n\n"
        f"Deal for: {esc(d['purpose'])}\n\n"
        f"Conditions: {esc(d['conditions'])}\n\n"
        f"GC Link: {esc(d['invite_link'])}"
    )


def gc_created_text(link: str) -> str:
    return (
        f"{emojis.EMOJI_CELEBRATE} <b>Deal GC Created</b>\n\n"
        f"{emojis.EMOJI_LINK} <b>Link:</b> {esc(link)}\n\n"
        "Please share the link with both parties and have them join to proceed."
    )


def expiry_text(d) -> str:
    tat_dur = fmt_duration(d.get("tat_seconds", 0))
    b_un = d.get("buyer_username")
    s_un = d.get("seller_username")
    buyer_m = f"@{esc(b_un)}" if b_un else user_mention(d.get("buyer_id", 0), "Buyer")
    seller_m = f"@{esc(s_un)}" if s_un else user_mention(d.get("seller_id", 0), "Seller")
    mm_m = f"@{esc(config.MM_USERNAME.lstrip('@'))}"
    dno = d.get("deal_no", "")

    return (
        f"{emojis.EMOJI_CLOCK} <b>TAT is Over!</b>\n\n"
        f"The turnaround time ({esc(tat_dur)}) for <b>Deal #{config.DEAL_ID_PREFIX}{dno}</b> has expired.\n\n"
        f"{emojis.EMOJI_BUYER} <b>Buyer:</b> {buyer_m}\n"
        f"{emojis.EMOJI_SELLER} <b>Seller:</b> {seller_m}\n"
        f"{emojis.EMOJI_SHIELD} <b>Middleman:</b> {mm_m}\n\n"
        f"{buyer_m}, please confirm if {seller_m} has delivered the product/service. {mm_m} please review and take necessary action."
    )


# ------------------------------------------------------------- Live Chat
def livechat_welcome() -> str:
    return (
        f"{emojis.EMOJI_CHAT} <b>Direct Chat with Middleman</b>\n\n"
        f"For users with restricted Telegram accounts, send your message directly\n\n"
        f"Your message will be forwarded to the middleman, and replies will be delivered here."
    )


def livechat_user_msg_alert(sender_name: str, username: str, user_id: int, text: str) -> str:
    u = f"@{esc(username)}" if username else "No username"
    return (
        "💬 <b>New Chat Message</b>\n"
        f"👤 From: <b>{esc(sender_name)}</b> ({u}) [<code>{user_id}</code>]\n\n"
        f"📝 <b>Message:</b>\n{esc(text)}"
    )


# ------------------------------------------------------------- Instant /mm Deal GC
def instant_deal_details_prompt(tos_url: str = None) -> str:
    return (
        f"{emojis.EMOJI_DOC} <b>Deal Details Required</b>\n\n"
        "• <b>Deal Type:</b>\n"
        "• <b>TAT:</b>\n"
        "• <b>Conditions:</b> (if any)\n"
        "• <b>Amount</b> (MM fee charged separately)\n"
        "• <b>Currency:</b> INR / USD / USDT\n"
        "• <b>Payment Network:</b> UPI / Crypto network\n\n"
        "Please reply in the same format."
    )


def instant_deal_summary(d: dict, buyer_tag: str, seller_tag: str) -> str:
    amt = str(d.get("amount", "0")).strip()
    curr = str(d.get("currency", "INR")).strip()
    sym = get_currency_symbol(curr)
    if sym in ("₹", "$", "€", "£"):
        amt_str = f"{sym}{amt}"
    elif curr:
        amt_str = f"{amt} {curr}"
    else:
        amt_str = amt

    dno = d.get("deal_no", "")
    deal_type = esc(str(d.get("deal_type", "N/A")))
    tat = esc(str(d.get("tat", "24h")))
    payment = esc(str(d.get("payment_network", "UPI")))
    conditions = esc(str(d.get("conditions", "None")))

    return (
        f"<b>Deal #{config.DEAL_ID_PREFIX}{dno}</b>\n\n"
        f"Buyer: {buyer_tag}\n"
        f"Seller: {seller_tag}\n"
        f"Middleman: {MM}\n\n"
        f"<b>Type:</b> {deal_type} | <b>TAT:</b> {tat}\n"
        f"<b>Amount:</b> {amt_str} + MM fee\n"
        f"<b>Payment:</b> {payment}\n"
        f"<b>Conditions:</b> {conditions}\n\n"
        f"{buyer_tag}, review and confirm this."
    )


def buyer_confirmed_wait_mm_text(buyer_tag: str) -> str:
    mm_tag = f"@{config.MM_USERNAME.lstrip('@')}"
    return (
        f"{emojis.EMOJI_SUCCESS} {buyer_tag} confirmed the deal.\n\n"
        f"{mm_tag}, please review and confirm to proceed for payment."
    )


def proceeding_to_payment_text() -> str:
    return f"{emojis.EMOJI_HOURGLASS} Proceeding to payment..."


def buyer_confirmed_text(buyer_tag: str) -> str:
    return f"{emojis.EMOJI_SUCCESS} {buyer_tag} confirmed the deal.\n\n{emojis.EMOJI_HOURGLASS} Proceeding to payment..."


def payment_details_upi(amount: str, currency: str, fee: str, upi_id: str) -> str:
    return (
        f"{emojis.EMOJI_CASH} <b>Amount:</b> {esc(amount)} {esc(currency)} + <b>Fee:</b> {esc(fee)}\n\n"
        f"{emojis.EMOJI_PIN} <b>UPI ID:</b> <code>{esc(upi_id)}</code>\n\n"
        f"{emojis.EMOJI_MEMO} Send payment screenshot right after paying."
    )


def payment_details_crypto_prompt(amount: str, currency: str, fee: str) -> str:
    return (
        f"{emojis.EMOJI_CASH} <b>Amount:</b> {esc(amount)} {esc(currency)} + <b>Fee:</b> {esc(fee)}\n\n"
        f"{emojis.EMOJI_COIN} <b>Crypto Payment:</b>\n"
        "Choose a network below to get the deposit address.\n\n"
        f"{emojis.EMOJI_WARNING} <i>Send payment to only the selected network.</i>"
    )


def payment_verification_text(buyer_tag: str) -> str:
    return (
        f"{emojis.EMOJI_POINT} {buyer_tag} — have you sent the payment?\n\n"
        "Tap the button below once payment is done."
    )


def payment_pending_acknowledgement() -> str:
    return (
        f"{emojis.EMOJI_HOURGLASS} Middleman will confirm once payment is received.\n"
        "You may continue the deal via DMs or here."
    )


# ------------------------------------------------------------- Stats
def stats_display(s: dict) -> str:
    return (
        f"{emojis.EMOJI_STATS} <b>Statistics</b>\n\n"
        f"{emojis.EMOJI_DEALS} <b>Deals</b>\n"
        f"• Total Deals: <b>{s['total_deals']}</b>\n"
        f"• Active Deals: <b>{s['active_deals']}</b>\n"
        f"• Completed Deals: <b>{s['completed_deals']}</b>\n"
        f"• Pending/Setup Deals: <b>{s['pending_deals']}</b>\n"
        f"• Cancelled/Failed: <b>{s['cancelled_deals']}</b>\n\n"
        f"{emojis.EMOJI_USERS} <b>User Base</b>\n"
        f"• Total Users: <b>{s['total_users']}</b>\n"
        f"• New Users Today: <b>{s['users_today']}</b>\n"
        f"• Active Livechats: <b>{s['active_livechats']}</b>\n"
        f"• Referral Points in Circulation: <b>{s['total_points']} {emojis.EMOJI_VOUCH}</b>\n\n"
        f"{emojis.EMOJI_SHIELD} <b>Middleman:</b> {MM}\n"
        f"{emojis.EMOJI_SUCCESS} <b>Status:</b> All Systems Operational"
    )


def exchange_summary_text(d: dict, initiator_username: str) -> str:
    return (
        f"{emojis.EMOJI_EXCHANGE} <b>Exchange Deal Summary</b>\n\n"
        f"You (@{esc(initiator_username)}) Giving: {esc(d.get('ex_give_amount', ''))}\n"
        f"In Exchange of: {esc(d.get('ex_receive_amount', ''))}\n\n"
        f"Other Party: @{esc(d.get('ex_cp', ''))}\n"
        f"TAT: {fmt_duration(d.get('ex_tat_seconds', 3600))}\n"
        f"Conditions: {esc(str(d.get('conditions', 'None')))}\n\n"
        f"Note: {MM}'s middleman fee is charged separately."
    )


def exchange_request_text(d: dict) -> str:
    return (
        f"{emojis.EMOJI_EXCHANGE} <b>New Exchange Deal Request</b>\n\n"
        f"From: @{esc(d.get('initiator_username', ''))}\n\n"
        f"They will give: {esc(d.get('ex_give_amount', ''))}\n"
        f"In exchange of: {esc(d.get('ex_receive_amount', ''))}\n\n"
        f"TAT: {fmt_duration(d.get('tat_seconds', 3600))}\n"
        f"Conditions: {esc(str(d.get('conditions', 'None')))}\n\n"
        "Do you accept this exchange deal?"
    )
