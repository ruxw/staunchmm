import asyncio
import logging
import re
from datetime import timedelta
from html import escape as _stdlib_esc


def esc(s, quote=True) -> str:
    """Safe HTML escape that never crashes on None or non-string inputs."""
    if s is None:
        return ""
    return _stdlib_esc(str(s), quote=quote)

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError
from telegram import (
    ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
    KeyboardButtonRequestUsers, LinkPreviewOptions, MessageOriginChannel, MessageOriginChat,
    MessageOriginHiddenUser, MessageOriginUser, ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError

import ai_parser
import config
import database as db
import emojis
import service
import settings
import texts
import userbot
import utils
from utils import (
    fmt_dt, fmt_duration, get_currency_symbol, parse_amount, parse_channel_target, parse_tat,
    parse_username, safe_format, user_mention, utcnow,
)

log = logging.getLogger(__name__)
HTML = ParseMode.HTML
BLUE, GREEN, RED = "primary", "success", "danger"   # Bot API button styles
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
_tasks: set = set()

# In-memory admin settings prompt state {user_id: {"action": "...", "data": "..."}}
_admin_sessions = {}


def _spawn(coro):
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


def _clean_btn_text(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    # Strip HTML tags (e.g. <tg-emoji emoji-id="...">📢</tg-emoji> -> 📢)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def _btn(text, data=None, color=None, url=None, icon=None):
    text = _clean_btn_text(text)
    if not icon:  # "🤝 P2P" -> custom emoji icon + "P2P"
        text, icon = emojis.split_leading_emoji(text)
    api_kw = {}
    if color:
        api_kw["style"] = color
    if icon:
        api_kw["icon_custom_emoji_id"] = str(icon)
    kw = {"api_kwargs": api_kw} if api_kw else {}
    if url:
        return InlineKeyboardButton(text, url=url, **kw)
    return InlineKeyboardButton(text, callback_data=data, **kw)


def _kb(*btns):  # always one button per row
    return InlineKeyboardMarkup([[b] for b in btns])


def _is_mm(user_id: int, username: str = None) -> bool:
    if user_id in config.MM_USER_IDS:
        return True
    if config.MM_USER_ID and user_id == config.MM_USER_ID:
        return True
    if userbot.mm_user_id and user_id == userbot.mm_user_id:
        return True
    if username and username.lower().lstrip("@") == config.MM_USERNAME.lower():
        return True
    return False


def _parse_ex_value(text: str) -> str:
    """Normalise an exchange value like '500inr', '50INR', '5$usdt', '5$ usdt', '10 BTC' -> '500 INR', '5 $USDT', etc.
    Returns a cleaned, human-readable string that the user can confirm."""
    import re as _re
    text = text.strip()
    # Case: number followed by $ (or other symbol) then optional currency letters — e.g. "5$ usdt", "5$usdt"
    m0 = _re.match(r'^(\d+(?:\.\d+)?)\s*([€$₹£¥])\s*([a-zA-Z]+)?$', text)
    if m0:
        num, sym, label = m0.group(1), m0.group(2), (m0.group(3) or "").strip()
        return f"{num} {sym}{label.upper()}" if label else f"{num} {sym}"
    # Case: number followed directly by alpha currency — "500inr", "10USDT", "1BTC"
    m1 = _re.match(r'^(\d+(?:\.\d+)?)\s+([a-zA-Z]+.*)$', text)
    m1b = _re.match(r'^(\d+(?:\.\d+)?)([a-zA-Z]+.*)$', text)
    m = m1 or m1b
    if m:
        num, label = m.group(1), m.group(2).strip()
        return f"{num} {label.upper()}" if label.isalpha() else f"{num} {label}"
    # Case: currency-symbol first — "$50", "₹500", "$50 usdt"
    m2 = _re.match(r'^([€$₹£¥])(\d+(?:\.\d+)?)\s*([a-zA-Z]*)$', text)
    if m2:
        sym, num, label = m2.group(1), m2.group(2), m2.group(3).strip()
        return f"{num} {sym}{label.upper()}" if label else f"{num} {sym}"
    # Fallback: return as-is but stripped
    return text


# ------------------------------------------------------------------ /start
async def start_cmd(update, ctx):
    user = update.effective_user
    is_new = await db.upsert_user(user)
    if is_new and ctx.args and ctx.args[0].startswith("ref_"):
        await db.process_referral(user.id, ctx.args[0][4:])

    # Buttonised main menu
    kb = InlineKeyboardMarkup([
        [
            _btn("Middleman", color=BLUE, url=settings.get("mm_channel_url", config.CHANNEL_URL), icon=emojis.get_custom_id("CHANNEL")),
            _btn("Vouches", color=BLUE, url=settings.get("vouch_channel_url", config.CHANNEL_URL), icon=emojis.get_custom_id("VOUCH")),
        ],
        [
            _btn("Start Deal", "menu:start_deal", GREEN, icon=emojis.get_custom_id("DEALS")),
            _btn("Chat (if limited)", "lc:start", BLUE, icon=emojis.get_custom_id("CHAT")),
        ],
        [
            _btn("Referral Program", "ref", GREEN, icon=emojis.get_custom_id("REF")),
        ],
    ])

    await update.message.reply_text(
        texts.welcome(),
        reply_markup=kb,
        parse_mode=HTML,
        link_preview_options=NO_PREVIEW,
    )


async def menu_cb(update, ctx):
    q = update.callback_query
    await q.answer()
    if q.data == "menu:start_deal":
        user = q.from_user
        await db.upsert_user(user)
        if not user.username:
            await q.message.reply_text("⚠️ Please set a Telegram username in your profile settings, then send /deal again.")
            return
        sent = await q.message.reply_text(
            "🛡 What type of deal is this?",
            reply_markup=_kb(_btn("🤝 P2P", "d:type:p2p", BLUE), _btn("Exchange", "d:type:exchange", GREEN, icon=emojis.get_custom_id("EXCHANGE"))),
        )
        await db.start_session(user.id, [q.message.message_id, sent.message_id])
    elif q.data == "menu:stats":
        if not _is_mm(q.from_user.id, q.from_user.username):
            await q.answer("Stats are restricted to the middleman.", show_alert=True)
            return
        s = await db.get_full_stats()
        kb = _kb(_btn("🔄 Refresh Stats", "stats:refresh", BLUE))
        await q.message.reply_text(texts.stats_display(s), reply_markup=kb, parse_mode=HTML)


# ------------------------------------------------------------------ Live Chat Feature
async def livechat_cmd(update, ctx):
    user = update.effective_user
    await db.upsert_user(user)
    await db.start_livechat(user.id, user.username or "", user.first_name or "")
    kb = _kb(_btn("❌ Exit Live Chat", "lc:end", RED))
    await update.message.reply_text(texts.livechat_welcome(), reply_markup=kb, parse_mode=HTML)


async def endchat_cmd(update, ctx):
    user = update.effective_user
    await db.end_livechat(user.id)
    await update.message.reply_text(
        f"🚪 <b>Live Chat closed.</b> Send /livechat anytime to reconnect with @{config.MM_USERNAME}.",
        parse_mode=HTML,
    )


async def livechat_callback(update, ctx):
    q = update.callback_query
    await q.answer()
    user = q.from_user
    action = q.data

    if action == "lc:start":
        await db.start_livechat(user.id, user.username or "", user.first_name or "")
        kb = _kb(_btn("❌ Exit Live Chat", "lc:end", RED))
        await q.message.reply_text(texts.livechat_welcome(), reply_markup=kb, parse_mode=HTML)
    elif action == "lc:end":
        await db.end_livechat(user.id)
        await q.edit_message_text(
            f"🚪 <b>Live Chat closed.</b> Send /livechat anytime to talk to @{config.MM_USERNAME}.",
            parse_mode=HTML,
        )
    elif action.startswith("lc:reply_to:"):
        target_uid = int(action.split(":")[2])
        _admin_sessions[user.id] = {"action": "livechat_reply", "target_uid": target_uid}
        await q.message.reply_text(
            f"✏️ <b>Type your reply to user <code>{target_uid}</code>:</b>",
            parse_mode=HTML,
        )


async def reply_cmd(update, ctx):
    user = update.effective_user
    if not _is_mm(user.id, user.username):
        await update.message.reply_text("⚠️ This command is reserved for the middleman.")
        return

    if not ctx.args or len(ctx.args) < 2:
        await update.message.reply_text("Usage: <code>/reply &lt;user_id&gt; &lt;message&gt;</code>", parse_mode=HTML)
        return

    try:
        target_uid = int(ctx.args[0])
        reply_text = " ".join(ctx.args[1:])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    ok = await _relay_reply_to_user(ctx.bot, target_uid, reply_text)
    if ok:
        await update.message.reply_text(f"✅ Reply delivered to user <code>{target_uid}</code>.", parse_mode=HTML)
    else:
        await update.message.reply_text(f"❌ Failed to deliver reply to user <code>{target_uid}</code>.", parse_mode=HTML)


async def _relay_reply_to_user(bot, target_uid: int, text: str) -> bool:
    try:
        await bot.send_message(
            target_uid,
            f"💬 <b>Message from Middleman (@{config.MM_USERNAME}):</b>\n\n{esc(text)}",
            parse_mode=HTML,
        )
        return True
    except TelegramError as e:
        log.warning("Could not deliver reply to user %s: %s", target_uid, e)
        return False


# ------------------------------------------------------------------ /settings Dashboard
async def settings_cmd(update, ctx):
    user = update.effective_user
    if not _is_mm(user.id, user.username):
        await update.message.reply_text("⚠️ Unauthorized. The /settings dashboard is reserved for the middleman.")
        return

    await _show_settings_dashboard(update.message.reply_text)


async def _show_settings_dashboard(send_or_edit_fn):
    ad = settings.get_ad()
    ad_status = "🟢 Active" if ad.get("enabled") and ad.get("text") else "🔴 Disabled"

    kb = InlineKeyboardMarkup([
        [
            _btn("📝 Message Templates", "set:templates", BLUE),
            _btn("📢 Channels & Links", "set:channels", GREEN),
        ],
        [
            _btn("💳 UPI Settings", "set:upi", BLUE),
            _btn("🪙 Crypto Wallets (25+)", "set:crypto_page:0", GREEN),
        ],
        [
            _btn("🎨 GC Appearance", "set:gc_appearance", BLUE),
            _btn("💰 MM Fee", "set:fee", GREEN),
        ],
        [
            _btn("📢 Sponsored Ad", "ad:manage", BLUE),
            _btn("❌ Close Dashboard", "set:close", RED),
        ],
    ])

    has_photo = "✅ Configured" if settings.get("gc_photo_file_id") else "❌ Not set"
    text = (
        f"{emojis.EMOJI_SETTINGS} <b>@{config.MM_USERNAME} Admin Dashboard</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Configure payment channels, crypto addresses, templates, and GC styles in real-time.\n\n"
        f"• <b>Official Channel:</b> {settings.get('mm_channel_url', 'Not set')}\n"
        f"• <b>Vouch Channel:</b> {settings.get('vouch_channel_url', 'Not set')}\n"
        f"• <b>UPI ID:</b> <code>{settings.get('upi_id', 'Not set')}</code>\n"
        f"• <b>Default MM Fee:</b> <code>{settings.get('default_fee', '50 INR')}</code>\n"
        f"• <b>GC Profile Photo:</b> {has_photo}\n"
        f"• <b>Sponsored Ad:</b> {ad_status}\n"
        f"• <b>Active Templates:</b> {len(settings.DEFAULT_TEMPLATES)} customizable\n"
        f"• <b>Configured Cryptos:</b> {len(settings.get('crypto_wallets', {}))} of {len(settings.CRYPTO_NETWORKS)}\n\n"
        "Tap any button below to manage:"
    )
    await send_or_edit_fn(text, reply_markup=kb, parse_mode=HTML, link_preview_options=NO_PREVIEW)


async def settings_callback(update, ctx):
    q = update.callback_query
    user = q.from_user
    if not _is_mm(user.id, user.username):
        await q.answer("Unauthorized", show_alert=True)
        return

    data = q.data
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "close":
        await q.answer()
        await q.edit_message_text("⚙️ Settings dashboard closed.")
        return

    if action == "main":
        await q.answer()
        await _show_settings_dashboard(q.edit_message_text)
        return

    # Template list
    if action == "templates":
        await q.answer()
        btns = []
        for key, label in settings.TEMPLATE_LABELS.items():
            btns.append([_btn(f"📝 {label}", f"set:tmpl_view:{key}", BLUE)])
        btns.append([_btn("⬅️ Back to Settings", "set:main", GREEN)])
        t = (
            "📝 <b>Configurable Message Templates</b>\n\n"
            "Select any message template below to view, preview, edit, or reset to defaults:"
        )
        await q.edit_message_text(t, reply_markup=InlineKeyboardMarkup(btns), parse_mode=HTML)
        return

    # View individual template
    if action == "tmpl_view":
        await q.answer()
        tmpl_key = parts[2]
        label = settings.TEMPLATE_LABELS.get(tmpl_key, tmpl_key)
        current_content = settings.get_template(tmpl_key)

        kb = InlineKeyboardMarkup([
            [
                _btn("👁️ Preview", f"set:tmpl_prev:{tmpl_key}", BLUE),
                _btn("✏️ Edit", f"set:tmpl_edit:{tmpl_key}", GREEN),
            ],
            [
                _btn("🔄 Reset Default", f"set:tmpl_reset:{tmpl_key}", RED),
                _btn("⬅️ Back", "set:templates", BLUE),
            ],
        ])
        t = (
            f"📝 <b>Template: {label}</b>\n\n"
            f"<b>Current Template:</b>\n<code>{esc(current_content)}</code>\n\n"
            "<b>Supported Placeholders:</b>\n"
            "<code>{deal_id}</code>, <code>{buyer}</code>, <code>{seller}</code>, <code>{currency}</code>, "
            "<code>{amount}</code>, <code>{tat}</code>, <code>{deadline}</code>, <code>{mm}</code>"
        )
        await q.edit_message_text(t, reply_markup=kb, parse_mode=HTML)
        return

    # Preview template
    if action == "tmpl_prev":
        await q.answer()
        tmpl_key = parts[2]
        label = settings.TEMPLATE_LABELS.get(tmpl_key, tmpl_key)
        rendered_preview = settings.preview_template(tmpl_key)

        kb = _kb(_btn("⬅️ Back", f"set:tmpl_view:{tmpl_key}", GREEN))
        t = (
            f"👁️ <b>Preview: {label}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{rendered_preview}"
        )
        await q.edit_message_text(t, reply_markup=kb, parse_mode=HTML, link_preview_options=NO_PREVIEW)
        return

    # Reset template
    if action == "tmpl_reset":
        tmpl_key = parts[2]
        await settings.reset_template(tmpl_key)
        await q.answer("Template reset to default!", show_alert=True)
        # Refresh view
        label = settings.TEMPLATE_LABELS.get(tmpl_key, tmpl_key)
        current_content = settings.get_template(tmpl_key)
        kb = InlineKeyboardMarkup([
            [
                _btn("👁️ Preview", f"set:tmpl_prev:{tmpl_key}", BLUE),
                _btn("✏️ Edit", f"set:tmpl_edit:{tmpl_key}", GREEN),
            ],
            [
                _btn("🔄 Reset Default", f"set:tmpl_reset:{tmpl_key}", RED),
                _btn("⬅️ Back", "set:templates", BLUE),
            ],
        ])
        t = (
            f"📝 <b>Template: {label} (Reset to Default)</b>\n\n"
            f"<b>Current Template:</b>\n<code>{esc(current_content)}</code>\n\n"
            "<b>Supported Placeholders:</b>\n"
            "<code>{deal_id}</code>, <code>{buyer}</code>, <code>{seller}</code>, <code>{currency}</code>, "
            "<code>{amount}</code>, <code>{tat}</code>, <code>{deadline}</code>, <code>{mm}</code>"
        )
        await q.edit_message_text(t, reply_markup=kb, parse_mode=HTML)
        return

    # Edit template
    if action == "tmpl_edit":
        await q.answer()
        tmpl_key = parts[2]
        label = settings.TEMPLATE_LABELS.get(tmpl_key, tmpl_key)
        _admin_sessions[user.id] = {"action": "set_template", "tmpl_key": tmpl_key}
        await q.message.reply_text(
            f"✏️ <b>Editing Template: {label}</b>\n\n"
            "Please send the new template message below.\n"
            "You may use HTML formatting and supported placeholders:\n"
            "<code>{deal_id}</code>, <code>{buyer}</code>, <code>{seller}</code>, <code>{currency}</code>, <code>{amount}</code>, <code>{tat}</code>, <code>{deadline}</code>\n\n"
            "Send /cancel to abort.",
            parse_mode=HTML,
        )
        return

    if action == "channels":
        await q.answer()
        kb = InlineKeyboardMarkup([
            [_btn("✏️ Edit Official Channel", "set:edit:mm_channel_url", BLUE)],
            [_btn("✏️ Edit Vouch Channel", "set:edit:vouch_channel_url", BLUE)],
            [_btn("✏️ Edit TOS / Rules Link", "set:edit:tos_channel_url", BLUE)],
            [_btn("⬅️ Back to Settings", "set:main", GREEN)],
        ])
        t = (
            "📢 <b>Channel Links Configuration</b>\n\n"
            f"1. <b>Official MM Channel:</b>\n{settings.get('mm_channel_url')}\n\n"
            f"2. <b>Vouch Channel:</b>\n{settings.get('vouch_channel_url')}\n\n"
            f"3. <b>TOS / Rules Channel:</b>\n{settings.get('tos_channel_url')}"
        )
        await q.edit_message_text(t, reply_markup=kb, parse_mode=HTML, link_preview_options=NO_PREVIEW)

    elif action == "upi":
        await q.answer()
        kb = InlineKeyboardMarkup([
            [_btn("✏️ Update UPI ID", "set:edit:upi_id", GREEN)],
            [_btn("⬅️ Back to Settings", "set:main", BLUE)],
        ])
        t = (
            "💳 <b>UPI Payment Configuration</b>\n\n"
            f"Current UPI ID: <code>{esc(settings.get('upi_id', 'Not set'))}</code>\n"
            f"UPI Name Note: <code>{esc(settings.get('upi_name', ''))}</code>\n\n"
            "This UPI ID is shared with buyers during deal payment."
        )
        await q.edit_message_text(t, reply_markup=kb, parse_mode=HTML)

    elif action == "fee":
        await q.answer()
        kb = InlineKeyboardMarkup([
            [_btn("✏️ Set Default Fee", "set:edit:default_fee", GREEN)],
            [_btn("⬅️ Back to Settings", "set:main", BLUE)],
        ])
        t = (
            "💰 <b>Middleman Fee Configuration</b>\n\n"
            f"Current Fee: <b>{esc(settings.get('default_fee', '50 INR'))}</b>\n\n"
            "You can set this to flat rates (e.g. <code>50 INR</code>) or percentages (e.g. <code>5%</code>)."
        )
        await q.edit_message_text(t, reply_markup=kb, parse_mode=HTML)

    elif action == "gc_appearance":
        await q.answer()
        has_photo = "✅ Configured" if settings.get("gc_photo_file_id") else "❌ Not configured"
        tmpl = settings.get("gc_name_template", settings.GC_NAME_PRESETS[0])
        kb = InlineKeyboardMarkup([
            [_btn("🏷️ Configure GC Name Style", "set:gcstyle", BLUE)],
            [_btn("🖼️ Configure GC Profile Photo", "set:gc_photo_menu", GREEN)],
            [_btn("⬅️ Back to Settings", "set:main", GREEN)],
        ])
        t = (
            "🎨 <b>Group Chat Appearance</b>\n\n"
            f"• <b>GC Name Format:</b> <code>{esc(tmpl)}</code>\n"
            f"• <b>GC Profile Photo:</b> {has_photo}\n\n"
            "Select an option to configure:"
        )
        await q.edit_message_text(t, reply_markup=kb, parse_mode=HTML)

    elif action == "gc_photo_menu":
        await q.answer()
        photo_id = settings.get("gc_photo_file_id")
        btns = []
        if photo_id:
            btns.append([
                _btn("👁️ Preview Photo", "set:gc_photo_prev", BLUE),
                _btn("🔄 Replace Photo", "set:gc_photo_upload", GREEN),
            ])
            btns.append([_btn("🗑️ Remove Photo", "set:gc_photo_remove", RED)])
            status_text = "✅ <b>Configured</b>\nThis photo is automatically applied to all newly created deal groups."
        else:
            btns.append([_btn("📤 Upload Photo", "set:gc_photo_upload", GREEN)])
            status_text = "❌ <b>Not configured</b>\nNo photo is currently applied to newly created deal groups."
        btns.append([_btn("⬅️ Back to GC Appearance", "set:gc_appearance", BLUE)])
        t = (
            "🖼️ <b>GC Profile Photo Settings</b>\n\n"
            f"Status: {status_text}\n\n"
            "Choose an action below:"
        )
        await q.edit_message_text(t, reply_markup=InlineKeyboardMarkup(btns), parse_mode=HTML)

    elif action == "gc_photo_prev":
        await q.answer()
        photo_id = settings.get("gc_photo_file_id")
        if not photo_id:
            await q.answer("No photo configured.", show_alert=True)
            return
        try:
            await ctx.bot.send_photo(
                chat_id=user.id,
                photo=photo_id,
                caption="🖼️ <b>Current GC Profile Photo</b>\nThis photo is automatically applied to all newly created deal groups.",
                parse_mode=HTML,
            )
        except Exception as e:
            await q.answer(f"Could not load photo preview: {e}", show_alert=True)

    elif action == "gc_photo_upload":
        await q.answer()
        _admin_sessions[user.id] = {"action": "set_gc_photo"}
        await q.message.reply_text(
            "📸 <b>Upload GC Profile Photo</b>\n\n"
            "Please send the photo you want to use as the group profile picture for all newly created deal groups.\n\n"
            "Send /cancel to abort.",
            parse_mode=HTML,
        )

    elif action == "gc_photo_remove":
        await settings.set_setting("gc_photo_file_id", None)
        await q.answer("GC Profile Photo removed!", show_alert=True)
        kb = InlineKeyboardMarkup([
            [_btn("📤 Upload Photo", "set:gc_photo_upload", GREEN)],
            [_btn("⬅️ Back to GC Appearance", "set:gc_appearance", BLUE)],
        ])
        t = (
            "🖼️ <b>GC Profile Photo Settings</b>\n\n"
            "Status: ❌ <b>Not configured</b> (Removed)\n\n"
            "Choose an action below:"
        )
        await q.edit_message_text(t, reply_markup=kb, parse_mode=HTML)

    elif action == "gcstyle":
        await q.answer()
        btns = []
        for i, preset in enumerate(settings.GC_NAME_PRESETS):
            btns.append([_btn(f"Preset {i+1}: {preset}", f"set:gc_pick:{i}", BLUE)])
        btns.append([_btn("⬅️ Back to GC Appearance", "set:gc_appearance", GREEN)])
        t = (
            "🏷️ <b>Deal Group Chat Name Template</b>\n\n"
            f"Current Format: <code>{esc(settings.get('gc_name_template'))}</code>\n\n"
            "Select one of the presets below:"
        )
        await q.edit_message_text(t, reply_markup=InlineKeyboardMarkup(btns), parse_mode=HTML)

    elif action == "gc_pick":
        idx = int(parts[2])
        preset = settings.GC_NAME_PRESETS[idx]
        if "{startno}" in preset:
            await q.answer()
            _admin_sessions[user.id] = {"action": "set_gc_start_num", "preset_idx": idx}
            await q.message.reply_text(
                "🔢 <b>Enter Starting Deal Number</b>\n\n"
                "Enter the positive integer starting deal number for your GC naming sequence (e.g. <code>121</code>):\n\n"
                "Send /cancel to abort.",
                parse_mode=HTML,
            )
            return

        await settings.set_setting("gc_name_template", preset)
        await q.answer("GC Naming Template Updated!", show_alert=True)
        await _show_settings_dashboard(q.edit_message_text)

    elif action == "crypto_page":
        await q.answer()
        page = int(parts[2]) if len(parts) > 2 else 0
        all_coins = list(settings.CRYPTO_NETWORKS.items())
        page_size = 6
        total_pages = (len(all_coins) + page_size - 1) // page_size
        page = max(0, min(page, total_pages - 1))

        current_slice = all_coins[page * page_size : (page + 1) * page_size]
        btns = []
        wallets = settings.get("crypto_wallets", {})

        for key, info in current_slice:
            has_addr = "✅" if wallets.get(key) else "❌"
            btns.append([_btn(f"{has_addr} {info['symbol']} ({info['network']})", f"set:coin:{key}", BLUE)])

        # Pagination controls
        nav = []
        if page > 0:
            nav.append(_btn("⬅️ Prev", f"set:crypto_page:{page-1}", BLUE))
        if page < total_pages - 1:
            nav.append(_btn("Next ➡️", f"set:crypto_page:{page+1}", BLUE))
        if nav:
            btns.append(nav)
        btns.append([_btn("⬅️ Back to Settings", "set:main", GREEN)])

        t = (
            f"🪙 <b>Crypto Addresses Setup (Page {page+1}/{total_pages})</b>\n\n"
            "Tap any cryptocurrency to view or update its deposit address:"
        )
        await q.edit_message_text(t, reply_markup=InlineKeyboardMarkup(btns), parse_mode=HTML)

    elif action == "coin":
        await q.answer()
        coin_key = parts[2]
        info = settings.CRYPTO_NETWORKS.get(coin_key, {})
        current_addr = settings.get_crypto_wallet(coin_key) or "Not configured"

        kb = InlineKeyboardMarkup([
            [_btn("✏️ Edit Address", f"set:edit_coin:{coin_key}", GREEN)],
            [_btn("⬅️ Back to Cryptos", "set:crypto_page:0", BLUE)],
        ])
        t = (
            f"🪙 <b>{info.get('name', 'Crypto')} ({info.get('symbol', '')})</b>\n"
            f"🌐 <b>Network:</b> <code>{info.get('network', '')}</code>\n\n"
            f"📥 <b>Current Address:</b>\n<code>{esc(current_addr)}</code>"
        )
        await q.edit_message_text(t, reply_markup=kb, parse_mode=HTML)

    elif action == "edit_coin":
        await q.answer()
        coin_key = parts[2]
        _admin_sessions[user.id] = {"action": "set_crypto", "coin_key": coin_key}
        info = settings.CRYPTO_NETWORKS.get(coin_key, {})
        await q.message.reply_text(
            f"✏️ Send the new wallet address for <b>{info.get('name')} ({info.get('network')})</b>:",
            parse_mode=HTML,
        )

    elif action == "edit":
        await q.answer()
        field_key = parts[2]
        _admin_sessions[user.id] = {"action": "set_field", "field": field_key}
        await q.message.reply_text(
            f"✏️ Please send the new value for <b>{field_key}</b>:",
            parse_mode=HTML,
        )


# ------------------------------------------------------------------ /ad Advertisement Manager
async def ad_cmd(update, ctx):
    user = update.effective_user
    if not _is_mm(user.id, user.username):
        await update.message.reply_text("⚠️ This command is reserved for the middleman.")
        return

    ad = settings.get_ad()
    is_active = ad.get("enabled") and bool(ad.get("text"))
    status_str = "🟢 <b>Active</b>" if is_active else "🔴 <b>Disabled</b>"
    current_ad_txt = esc(ad.get("text", ""))

    content = (
        f"📢 <b>Advertisement Footer Manager</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Status:</b> {status_str}\n"
    )
    if ad.get("text"):
        content += f"• <b>Current Ad:</b>\n— \"<code>{current_ad_txt}</code>\"\n\n"
    else:
        content += "• <b>Current Ad:</b> <i>None configured</i>\n\n"

    content += (
        "When active, your ad is automatically appended as a footer to outgoing bot messages.\n"
        "Format: <code>— \"Your Ad Text\"</code>"
    )

    btns = [
        [_btn("✏️ Set / Replace Ad", "ad:set", BLUE)],
    ]
    if ad.get("text"):
        if is_active:
            btns.append([_btn("🔴 Disable Ad", "ad:disable", RED), _btn("👁 Preview Ad", "ad:preview", BLUE)])
        else:
            btns.append([_btn("🟢 Enable Ad", "ad:enable", GREEN), _btn("👁 Preview Ad", "ad:preview", BLUE)])
    else:
        btns.append([_btn("👁 Preview Sample", "ad:preview", BLUE)])

    await update.message.reply_text(content, reply_markup=InlineKeyboardMarkup(btns), parse_mode=HTML)


async def ad_callback(update, ctx):
    q = update.callback_query
    user = q.from_user
    if not _is_mm(user.id, user.username):
        await q.answer("Only the middleman can configure advertisements.", show_alert=True)
        return

    parts = q.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action in ("manage", "main"):
        await q.answer()
        ad = settings.get_ad()
        is_active = ad.get("enabled") and bool(ad.get("text"))
        status_str = "🟢 <b>Active</b>" if is_active else "🔴 <b>Disabled</b>"
        current_ad_txt = esc(ad.get("text", ""))
        content = (
            f"📢 <b>Advertisement Footer Manager</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Status:</b> {status_str}\n"
        )
        if ad.get("text"):
            content += f"• <b>Current Ad:</b>\n— \"<code>{current_ad_txt}</code>\"\n\n"
        else:
            content += "• <b>Current Ad:</b> <i>None configured</i>\n\n"

        content += (
            "When active, your ad is automatically appended as a footer to outgoing bot messages.\n"
            "Format: <code>— \"Your Ad Text\"</code>"
        )
        btns = [
            [_btn("✏️ Set / Replace Ad", "ad:set", BLUE)],
        ]
        if ad.get("text"):
            if is_active:
                btns.append([_btn("🔴 Disable Ad", "ad:disable", RED), _btn("👁 Preview Ad", "ad:preview", BLUE)])
            else:
                btns.append([_btn("🟢 Enable Ad", "ad:enable", GREEN), _btn("👁 Preview Ad", "ad:preview", BLUE)])
        else:
            btns.append([_btn("👁 Preview Sample", "ad:preview", BLUE)])
        btns.append([_btn("⬅️ Back to Settings", "set:main", GREEN)])

        await q.edit_message_text(content, reply_markup=InlineKeyboardMarkup(btns), parse_mode=HTML)
        return

    elif action == "set":
        await q.answer()
        _admin_sessions[user.id] = {"action": "set_ad"}
        await q.message.reply_text(
            "📢 <b>Set Advertisement Footer</b>\n\n"
            "Send the exact ad text you would like to display. Example:\n"
            "<code>🎰 @Rainbetcom #1 Non-KYC Crypto Casino & Sportsbook</code>\n\n"
            "<i>Telegram custom emojis and formatting are fully supported.</i>\n"
            "Send <code>/cancel</code> to abort.",
            parse_mode=HTML,
        )

    elif action == "preview":
        await q.answer()
        ad = settings.get_ad()
        ad_txt = ad.get("text") or "🎰 @Rainbetcom #1 Non-KYC Crypto Casino & Sportsbook"
        await q.message.reply_text(
            f"👁 <b>Advertisement Preview:</b>\n\n"
            f"This is a sample bot notification / deal message.\n\n"
            f"— \"{ad_txt}\"",
            parse_mode=HTML,
        )

    elif action == "disable":
        ad = settings.get_ad()
        await settings.set_ad(ad.get("text", ""), enabled=False)
        await q.answer("Ad disabled.")
        await q.message.reply_text("🔴 Advertisement footer has been disabled.")

    elif action == "enable":
        ad = settings.get_ad()
        if not ad.get("text"):
            await q.answer("No ad configured. Tap Set / Replace first.", show_alert=True)
            return
        await settings.set_ad(ad.get("text", ""), enabled=True)
        await q.answer("Ad enabled!")
        await q.message.reply_text(f"🟢 Advertisement footer is now active:\n— \"{esc(ad['text'])}\"", parse_mode=HTML)


# ------------------------------------------------------------------ /stats
async def stats_cmd(update, ctx):
    user = update.effective_user
    if not _is_mm(user.id, user.username):
        await update.message.reply_text("⚠️ Stats are restricted to the middleman.")
        return
    s = await db.get_full_stats()
    kb = _kb(_btn("🔄 Refresh Stats", "stats:refresh", BLUE))
    await update.message.reply_text(texts.stats_display(s), reply_markup=kb, parse_mode=HTML)


async def stats_callback(update, ctx):
    q = update.callback_query
    if not _is_mm(q.from_user.id, q.from_user.username):
        await q.answer("Stats are restricted to the middleman.", show_alert=True)
        return
    await q.answer("Stats updated!")
    s = await db.get_full_stats()
    kb = _kb(_btn("🔄 Refresh Stats", "stats:refresh", BLUE))
    try:
        await q.edit_message_text(texts.stats_display(s), reply_markup=kb, parse_mode=HTML)
    except BadRequest:
        pass


# ------------------------------------------------------------------ /referral, /deals, /leaderboard
async def _referral_text(ctx, uid) -> str:
    u = await db.get_user(uid)
    link = f"https://t.me/{ctx.bot.username}?start=ref_{u['ref_code']}"
    return (
        f"{emojis.EMOJI_REF} <b>Referral Program</b>\n\n"
        "Invite friends and earn <b>2 points</b> for every referral!\n\n"
        f"🔗 <b>Your Link:</b> {link}\n\n"
        f"⭐ <b>Your Points:</b> {u['points']}"
    )


async def referral_cb(update, ctx):
    q = update.callback_query
    await q.answer()
    await db.upsert_user(q.from_user)
    await q.message.reply_text(await _referral_text(ctx, q.from_user.id), parse_mode=HTML, link_preview_options=NO_PREVIEW)


async def referral_cmd(update, ctx):
    await db.upsert_user(update.effective_user)
    await update.message.reply_text(await _referral_text(ctx, update.effective_user.id), parse_mode=HTML, link_preview_options=NO_PREVIEW)


async def redeem_cmd(update, ctx):
    await db.upsert_user(update.effective_user)
    await update.message.reply_text("🎁 Redeem is coming soon.")


async def deals_cmd(update, ctx):
    user = update.effective_user
    await db.upsert_user(user)
    n = await db.count_user_deals(user.id)
    if n == 0:
        await update.message.reply_text(
            f"📋 <b>Deal History</b>\n\nYou haven't participated in any deals yet.\n\nUse /deal to get started. 🔒",
            parse_mode=HTML,
        )
    else:
        await update.message.reply_text(
            f"📋 <b>Deal History</b>\n\nYou participated in {n} deals with {texts.MM}.\n\nUse /deal to get started. 🔒",
            parse_mode=HTML,
        )


async def leaderboard_cmd(update, ctx):
    rows = await db.leaderboard(10)
    lines = ["🏆 <b>Top 10 Deal Makers of all time</b>", ""]
    if not rows:
        lines.append("No deals yet.")
    for i, (u, uid, n) in enumerate(rows, 1):
        if u and u.get("username"):
            name = f"@{esc(u['username'])}"
        else:
            name = esc((u or {}).get("first_name") or str(uid))
        lines.append(f"{i}. {name} — {n} Deal{'s' if n != 1 else ''}")
    await update.message.reply_text("\n".join(lines), parse_mode=HTML)


async def id_cmd(update, ctx):
    uid = update.effective_user.id
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("Select a user", request_users=KeyboardButtonRequestUsers(request_id=1, user_is_bot=False, max_quantity=1),
                         api_kwargs={"icon_custom_emoji_id": emojis.get_custom_id("USER")} if emojis.get_custom_id("USER") else None)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text(
        f"Your User ID: <code>{uid}</code>\n\nGet any user's ID by tapping the button below.",
        parse_mode=HTML,
        reply_markup=kb,
    )


async def _users_shared(msg):
    ids = [u.user_id for u in msg.users_shared.users]
    text = "\n".join(f"User ID: <code>{i}</code>" for i in ids) or "No user selected."
    await msg.reply_text(text, parse_mode=HTML, reply_markup=ReplyKeyboardRemove())


async def _forwarded(msg):
    o = msg.forward_origin
    if isinstance(o, MessageOriginUser):
        text = f"👤 Original sender's User ID: <code>{o.sender_user.id}</code>"
    elif isinstance(o, MessageOriginHiddenUser):
        text = f"🔒 {esc(o.sender_user_name)} has hidden their account, so Telegram doesn't share their User ID."
    elif isinstance(o, MessageOriginChat):
        text = f"💬 Original chat's Chat ID: <code>{o.sender_chat.id}</code>"
    elif isinstance(o, MessageOriginChannel):
        text = f"📢 Original chat's Chat ID: <code>{o.chat.id}</code>"
    else:
        text = "Telegram didn't provide an ID for this forwarded message."
    await msg.reply_text(text, parse_mode=HTML)


# ------------------------------------------------------------------ Standard /deal setup
async def deal_cmd(update, ctx):
    user, msg = update.effective_user, update.message
    await db.upsert_user(user)
    if not user.username:
        await msg.reply_text("⚠️ Please set a Telegram username in your profile settings, then send /deal again.")
        return
    sent = await msg.reply_text(
        "🛡 What type of deal is this?",
        reply_markup=_kb(_btn("🤝 P2P", "d:type:p2p", BLUE), _btn("Exchange", "d:type:exchange", GREEN, icon=emojis.get_custom_id("EXCHANGE"))),
    )
    await db.start_session(user.id, [msg.message_id, sent.message_id])


def _parties(d, user) -> dict:
    me = user.username
    buyer, seller = (me, d["cp"]) if d["role"] == "buyer" else (d["cp"], me)
    return {
        "buyer_username": buyer, "seller_username": seller, "purpose": d["purpose"],
        "tat_seconds": d["tat_seconds"], "amount": d["amount"], "currency": d["currency"],
        "conditions": d.get("conditions", "None"),
    }


async def _delete_msgs(bot, chat_id, ids):
    ids = list(dict.fromkeys(ids))
    for i in range(0, len(ids), 100):
        try:
            await bot.delete_messages(chat_id, ids[i:i + 100])
        except TelegramError:
            for mid in ids[i:i + 100]:
                try:
                    await bot.delete_message(chat_id, mid)
                except TelegramError:
                    pass


async def _show_summary(ctx, user, chat_id, s, extra_ids, conditions):
    d = dict(s["data"])
    d["conditions"] = conditions
    await db.update_session(user.id, data={"conditions": conditions})
    await _delete_msgs(ctx.bot, chat_id, list(s["msg_ids"]) + list(extra_ids))
    sent = await ctx.bot.send_message(
        chat_id,
        texts.summary_text(_parties(d, user)),
        parse_mode=HTML,
        reply_markup=_kb(_btn("✅ Confirm", "d:confirm", GREEN), _btn("❌ Cancel", "d:cancel", RED)),
    )
    await db.update_session(user.id, step="summary", msg_ids=[sent.message_id])


async def _session_text(update, ctx, s):
    msg, user = update.message, update.effective_user
    text, step = msg.text.strip(), s["step"]

    async def reject(err):
        sent = await msg.reply_text(err, parse_mode=HTML)
        await db.update_session(user.id, push_ids=[msg.message_id, sent.message_id])

    async def advance(prompt, next_step, data, markup=None):
        sent = await msg.reply_text(prompt, parse_mode=HTML, reply_markup=markup)
        await db.update_session(user.id, step=next_step, data=data, push_ids=[msg.message_id, sent.message_id])

    if step == "cp":
        un = parse_username(text)
        if not un:
            return await reject("❌ Invalid username. Please enter a valid Telegram username starting with @ (e.g. @username).")
        if un.lower() == (user.username or "").lower():
            return await reject("❌ That's your own username. Please enter the other party's username.")
        await advance("What is this Deal for?\n\nExample: Acc selling", "purpose", {"cp": un})

    elif step == "purpose":
        if len(text) > 200:
            return await reject("❌ That's too long. Please keep it under 200 characters.")
        await advance("Select Currency", "currency", {"purpose": text},
                      _kb(_btn("💵 INR", "d:cur:INR", BLUE), _btn("🪙 Crypto", "d:cur:Crypto", GREEN)))

    elif step == "amount":
        try:
            amount = parse_amount(text)
        except ValueError as e:
            return await reject(str(e))
        await advance("⏱ Enter the TAT (turnaround time) for this deal.\n\nExample: 24h, 2d, 90m", "tat", {"amount": amount})

    elif step == "tat":
        try:
            secs = parse_tat(text)
        except ValueError as e:
            return await reject(str(e))
        await advance("What are the terms/conditions?", "terms", {"tat_seconds": secs}, _kb(_btn("⏩ Skip", "d:skip", GREEN)))

    elif step == "terms":
        if len(text) > 500:
            return await reject("❌ That's too long. Please keep it under 500 characters.")
        await _show_summary(ctx, user, msg.chat_id, s, [msg.message_id], text)

    elif step == "ex_give":
        if len(text) > 150:
            return await reject("❌ Too long. Keep it under 150 characters.")
        # Auto-parse: user may type "500inr", "500 inr", "10usdt", "1 btc" etc.
        parsed = _parse_ex_value(text)
        confirm_text = (
            f"{emojis.EMOJI_EXCHANGE} <b>You are giving:</b> <code>{esc(parsed)}</code>\n\n"
            "Is this correct? Tap ✅ to confirm. If wrong, tap ❌ to re-enter with correct format."
        )
        await db.update_session(user.id, data={"ex_give_raw": text, "_ex_give_pending": parsed})
        sent = await msg.reply_text(
            confirm_text,
            parse_mode=HTML,
            reply_markup=_kb(
                _btn("✅ Yes, correct", "d:ex_give_ok", GREEN),
                _btn("❌ Re-enter", "d:ex_give_retry", RED),
            ),
        )
        await db.update_session(user.id, push_ids=[msg.message_id, sent.message_id])

    elif step == "ex_receive":
        if len(text) > 150:
            return await reject("❌ Too long. Keep it under 150 characters.")
        parsed = _parse_ex_value(text)
        confirm_text = (
            f"{emojis.EMOJI_EXCHANGE} <b>You are receiving:</b> <code>{esc(parsed)}</code>\n\n"
            "Is this correct? Tap ✅ to confirm. If wrong, tap ❌ to re-enter with correct format."
        )
        await db.update_session(user.id, data={"ex_receive_raw": text, "_ex_receive_pending": parsed})
        sent = await msg.reply_text(
            confirm_text,
            parse_mode=HTML,
            reply_markup=_kb(
                _btn("✅ Yes, correct", "d:ex_receive_ok", GREEN),
                _btn("❌ Re-enter", "d:ex_receive_retry", RED),
            ),
        )
        await db.update_session(user.id, push_ids=[msg.message_id, sent.message_id])

    elif step == "ex_cp":
        un = parse_username(text)
        if not un:
            return await reject("❌ Invalid username. Please enter a valid Telegram username starting with @ (e.g. @username).")
        if un.lower() == (user.username or "").lower():
            return await reject("❌ That's your own username. Please enter the other party's username.")
        await advance(
            "⏱ Enter the <b>TAT</b> (turnaround time) for this exchange.\n\nExample: <code>30m</code>, <code>1h</code>, <code>2h</code>, <code>1d</code>",
            "ex_tat", {"ex_cp": un}
        )

    elif step == "ex_tat":
        try:
            secs = parse_tat(text)
        except ValueError:
            # Could be a bare number like "330" — show a helpful error + examples
            return await reject(
                "⚠️ <b>Invalid TAT format.</b>\n\n"
                "Please use a proper duration format:\n"
                "• <code>30m</code> — 30 minutes\n"
                "• <code>1h</code> — 1 hour\n"
                "• <code>2h 30m</code> — 2 hours 30 minutes\n"
                "• <code>1d</code> — 1 day\n\n"
                "If you meant <b>minutes</b>, type: <code>330m</code>\n"
                "If you meant <b>hours</b>, type: <code>330h</code>"
            )
        # Show confirm prompt so user can verify
        confirm_text = (
            f"⏱ <b>TAT set to:</b> <code>{fmt_duration(secs)}</code>\n\n"
            "Is this correct? Tap ✅ to confirm. If wrong, tap ❌ to re-enter with correct format."
        )
        await db.update_session(user.id, data={"_ex_tat_pending": secs})
        sent = await msg.reply_text(
            confirm_text,
            parse_mode=HTML,
            reply_markup=_kb(
                _btn("✅ Yes, correct", "d:ex_tat_ok", GREEN),
                _btn("❌ Re-enter", "d:ex_tat_retry", RED),
            ),
        )
        await db.update_session(user.id, push_ids=[msg.message_id, sent.message_id])

    elif step == "ex_terms":
        if len(text) > 500:
            return await reject("❌ Too long. Keep it under 500 characters.")
        await _show_exchange_summary(ctx, user, msg.chat_id, s, [msg.message_id], text)


async def deal_callback(update, ctx):
    q, user = update.callback_query, update.callback_query.from_user
    s = await db.get_session(user.id)
    if not s:
        await q.answer("⏳ This deal setup has expired. Send /deal to start again.", show_alert=True)
        return
    parts, step, d = q.data.split(":"), s["step"], s["data"]
    action = parts[1]

    if action == "type" and step == "type":
        if parts[2] == "exchange":
            await q.answer()
            await db.update_session(user.id, step="ex_give", data={"deal_type": "exchange"})
            await q.edit_message_text(
                f"{emojis.EMOJI_EXCHANGE} <b>Exchange Deal</b>\n\n"
                "What are you <b>giving</b>?\n\n"
                "Type the <b>amount + currency</b> together.\n"
                "Example: <code>500 INR</code>, <code>10 USDT</code>, <code>1 BTC</code>, <code>5$ usdt</code>",
                parse_mode=HTML,
            )
            return
        await q.answer()
        await db.update_session(user.id, step="role")
        await q.edit_message_text(
            "🛡 Who are you in this deal?",
            reply_markup=_kb(_btn("🛒 I am Buyer", "d:role:buyer", BLUE), _btn("💼 I am Seller", "d:role:seller", GREEN)),
        )

    elif action == "role" and step == "role":
        await q.answer()
        role = parts[2]
        who = "Seller" if role == "buyer" else "Buyer"
        await db.update_session(user.id, step="cp", data={"role": role})
        await q.edit_message_text(
            f"Please enter the <b>Username</b> of <b>{who}</b>, including ⎯ @ [Please don't enter your user]",
            parse_mode=HTML,
        )

    elif action == "cur" and step == "currency":
        await q.answer()
        await db.update_session(user.id, step="amount", data={"currency": parts[2]})
        await q.edit_message_text(f"💰 Enter the deal amount.\n\nNote: {texts.MM}’s middleman fee is charged separately.")

    elif action == "skip" and step == "terms":
        await q.answer()
        await _show_summary(ctx, user, q.message.chat_id, s, [], "None")

    # ---- Exchange button callbacks ----
    elif action == "ex_give_ok" and step == "ex_give":
        await q.answer()
        s2 = await db.get_session(user.id)
        d2 = s2["data"] if s2 else {}
        confirmed_val = d2.get("_ex_give_pending", "")
        await db.update_session(user.id, step="ex_receive", data={"ex_give_amount": confirmed_val})
        await q.edit_message_text(
            f"{emojis.EMOJI_EXCHANGE} <b>What are you receiving in return?</b>\n\n"
            "Type the amount and currency together.\n"
            "Example: <code>5$ usdt</code>, <code>9.5 USDT</code>, <code>10 BTC</code>",
            parse_mode=HTML,
        )

    elif action == "ex_give_retry" and step == "ex_give":
        await q.answer()
        await q.edit_message_text(
            f"{emojis.EMOJI_EXCHANGE} <b>Re-enter what you are giving:</b>\n\n"
            "Type the amount and currency together.\n"
            "Example: <code>500 INR</code>, <code>10 USDT</code>, <code>1 BTC</code>",
            parse_mode=HTML,
        )

    elif action == "ex_receive_ok" and step == "ex_receive":
        await q.answer()
        s2 = await db.get_session(user.id)
        d2 = s2["data"] if s2 else {}
        confirmed_val = d2.get("_ex_receive_pending", "")
        await db.update_session(user.id, step="ex_cp", data={"ex_receive_amount": confirmed_val})
        await q.edit_message_text(
            "Who is the <b>other party</b> in this exchange?\n\nEnter their Telegram username (e.g. @username)",
            parse_mode=HTML,
        )

    elif action == "ex_receive_retry" and step == "ex_receive":
        await q.answer()
        await q.edit_message_text(
            f"{emojis.EMOJI_EXCHANGE} <b>Re-enter what you are receiving:</b>\n\n"
            "Type the amount and currency together.\n"
            "Example: <code>5$ usdt</code>, <code>9.5 USDT</code>, <code>4800 INR</code>",
            parse_mode=HTML,
        )

    elif action == "ex_tat_ok" and step == "ex_tat":
        await q.answer()
        s2 = await db.get_session(user.id)
        d2 = s2["data"] if s2 else {}
        confirmed_secs = d2.get("_ex_tat_pending", 3600)
        await db.update_session(user.id, step="ex_terms", data={"ex_tat_seconds": confirmed_secs})
        await q.edit_message_text(
            "Any <b>terms or conditions</b> for this exchange?",
            parse_mode=HTML,
            reply_markup=_kb(_btn("⏩ Skip", "d:ex_skip", GREEN)),
        )

    elif action == "ex_tat_retry" and step == "ex_tat":
        await q.answer()
        await q.edit_message_text(
            "⏱ <b>Re-enter the TAT</b> (turnaround time) for this exchange.\n\n"
            "Example: <code>30m</code>, <code>1h</code>, <code>2h</code>, <code>1d</code>",
            parse_mode=HTML,
        )

    elif action == "ex_skip" and step == "ex_terms":
        await q.answer()
        await _show_exchange_summary(ctx, user, q.message.chat_id, s, [], "None")

    elif action == "ex_confirm" and step == "ex_summary":
        await _confirm_exchange(q, ctx, s, user)

    elif action == "cancel" and step == "ex_summary":
        await q.answer()
        await db.delete_session(user.id)
        await q.edit_message_text("❌ Exchange setup cancelled.")

    elif action == "cancel" and step == "summary":
        await q.answer()
        await db.delete_session(user.id)
        await q.edit_message_text("❌ Deal setup cancelled.")

    elif action == "confirm" and step == "summary":
        await _confirm(q, ctx, s, user)
    else:
        await q.answer()


async def _confirm(q, ctx, s, user):
    d = s["data"]
    cp = await db.find_user_by_username(d["cp"])
    if not cp or cp["_id"] == user.id:
        await q.answer("The seller/buyer both parties must have started the bot.", show_alert=True)
        return
    p = _parties(d, user)
    me_buyer = d["role"] == "buyer"
    deal = {
        **p,
        "status": "pending",
        "initiator_id": user.id, "initiator_username": user.username, "initiator_role": d["role"],
        "other_id": cp["_id"],
        "buyer_id": user.id if me_buyer else cp["_id"],
        "seller_id": cp["_id"] if me_buyer else user.id,
        "created_at": utcnow(),
    }
    deal["seller_username" if me_buyer else "buyer_username"] = cp.get("username") or d["cp"]
    res = await db.deals.insert_one(deal)
    did = str(res.inserted_id)
    try:
        req = await ctx.bot.send_message(
            cp["_id"],
            texts.request_text(deal),
            parse_mode=HTML,
            reply_markup=_kb(_btn("✅ Accept", f"acc:{did}", GREEN), _btn("❌ Reject", f"rej:{did}", RED)),
        )
    except (Forbidden, BadRequest):
        await db.deals.delete_one({"_id": res.inserted_id})
        await q.answer("The seller/buyer both parties must have started the bot.", show_alert=True)
        return
    await db.deals.update_one({"_id": res.inserted_id}, {"$set": {"request_message_id": req.message_id}})
    await db.delete_session(user.id)
    await q.answer()
    await q.edit_message_text(
        f"📨 Deal request sent to @{esc(deal['seller_username' if me_buyer else 'buyer_username'])}.",
        parse_mode=HTML,
    )


async def _show_exchange_summary(ctx, user, chat_id, s, extra_ids, conditions):
    d = dict(s["data"])
    d["conditions"] = conditions
    await db.update_session(user.id, data={"conditions": conditions})
    await _delete_msgs(ctx.bot, chat_id, list(s["msg_ids"]) + list(extra_ids))
    ex_text = texts.exchange_summary_text(d, user.username)
    sent = await ctx.bot.send_message(
        chat_id,
        ex_text,
        parse_mode=HTML,
        reply_markup=_kb(
            _btn("✅ Confirm Exchange", "d:ex_confirm", GREEN),
            _btn("❌ Cancel", "d:cancel", RED),
        ),
    )
    await db.update_session(user.id, step="ex_summary", msg_ids=[sent.message_id])


async def _confirm_exchange(q, ctx, s, user):
    d = s["data"]
    cp_username = d.get("ex_cp", "")
    cp = await db.find_user_by_username(cp_username)
    if not cp or cp["_id"] == user.id:
        await q.answer("The other party must have started the bot first.", show_alert=True)
        return
    # ex_give_amount holds the full value e.g. "500 INR"
    # ex_receive_amount holds the full value e.g. "5$ usdt"
    give_val = d.get("ex_give_amount", "")
    receive_val = d.get("ex_receive_amount", "")
    exchange_deal = {
        "deal_type": "exchange",
        "status": "pending",
        "initiator_id": user.id,
        "initiator_username": user.username,
        "other_id": cp["_id"],
        "buyer_id": user.id,
        "buyer_username": user.username,
        "seller_id": cp["_id"],
        "seller_username": cp.get("username") or cp_username,
        "ex_give_amount": give_val,
        "ex_receive_amount": receive_val,
        "conditions": d.get("conditions", "None"),
        "tat_seconds": d.get("ex_tat_seconds", 3600),
        "purpose": f"Exchange: {give_val} → {receive_val}",
        "amount": give_val,
        "currency": "",
        "created_at": utcnow(),
    }
    res = await db.deals.insert_one(exchange_deal)
    did = str(res.inserted_id)
    req_text = texts.exchange_request_text(exchange_deal)
    try:
        req = await ctx.bot.send_message(
            cp["_id"],
            req_text,
            parse_mode=HTML,
            reply_markup=_kb(
                _btn("✅ Accept", f"acc:{did}", GREEN),
                _btn("❌ Reject", f"rej:{did}", RED),
            ),
        )
    except (Forbidden, BadRequest):
        await db.deals.delete_one({"_id": res.inserted_id})
        await q.answer("The other party must have started the bot first.", show_alert=True)
        return
    await db.deals.update_one({"_id": res.inserted_id}, {"$set": {"request_message_id": req.message_id}})
    await db.delete_session(user.id)
    await q.answer()
    await q.edit_message_text(
        f"📨 Exchange request sent to @{esc(cp.get('username') or cp_username)}.",
        parse_mode=HTML,
    )


def _oid(s):
    try:
        return ObjectId(s)
    except (InvalidId, TypeError):
        return None


async def accept_cb(update, ctx):
    q = update.callback_query
    oid = _oid(q.data.split(":", 1)[1])
    deal = await db.claim_pending(oid, q.from_user.id) if oid else None
    if not deal:
        await q.answer("This deal request is no longer available.", show_alert=True)
        return
    await q.answer()
    try:
        await q.edit_message_text("🎉 You accepted the deal! GC is being created...")
    except TelegramError:
        pass
    _spawn(service.finalize_deal(ctx.application, deal))


async def reject_cb(update, ctx):
    q = update.callback_query
    oid = _oid(q.data.split(":", 1)[1])
    deal = await db.deals.find_one_and_update(
        {"_id": oid, "status": "pending", "other_id": q.from_user.id},
        {"$set": {"status": "rejected", "rejected_at": utcnow()}},
    ) if oid else None
    if not deal:
        await q.answer("This deal request is no longer available.", show_alert=True)
        return
    await q.answer()
    await q.edit_message_text("❌ You Rejected the deal")


# ------------------------------------------------------------------ TAT extension (inline button callback)
async def extend_cb(update, ctx):
    q = update.callback_query
    if not _is_mm(q.from_user.id, q.from_user.username):
        await q.answer("Only the middleman can extend the TAT.", show_alert=True)
        return
    try:
        await db.callbacks.insert_one({"_id": q.id, "created_at": utcnow()})
    except DuplicateKeyError:
        await q.answer()
        return
    try:
        _, did, hours = q.data.split(":")
        hours, oid = int(hours), _oid(did)
    except ValueError:
        await q.answer()
        return
    if hours not in (1, 5, 24) or not oid or not q.message:
        await q.answer()
        return

    deal = await db.deals.find_one({"_id": oid})
    if not deal or deal.get("status") == "closed":
        await q.answer("This deal isn't active.", show_alert=True)
        return

    await service.extend_deal_tat(ctx.bot, deal, hours * 3600, f"{hours}h", q.from_user.id)
    await q.answer(f"TAT extended by {hours} hour{'s' if hours != 1 else ''}.")


# ------------------------------------------------------------------ Instant /mm Group Workflow
async def mm_dm_cmd(update, ctx):
    """Fallback when /mm is sent directly to the bot in DM."""
    user = update.effective_user
    deal_no = await db.next_deal_no()
    label = f"#{config.DEAL_ID_PREFIX}{deal_no}"
    title = settings.render_gc_title(label, "Buyer", "Seller", deal_no=deal_no)

    info = await userbot.create_deal_group(title, ctx.bot.username)
    await service.apply_gc_photo(ctx.bot, info.chat_id)
    deal = {
        "deal_no": deal_no,
        "status": "instant_role_selection",
        "created_via": "bot_dm_mm",
        "group_chat_id": info.chat_id,
        "invite_link": info.invite_link,
        "dm_user_id": user.id,
        "dm_username": user.username,
        "buyer_id": None,
        "buyer_username": None,
        "seller_id": None,
        "seller_username": None,
        "created_at": utcnow(),
    }
    res = await db.deals.insert_one(deal)
    deal["_id"] = res.inserted_id

    await update.message.reply_text(
        f"{emojis.EMOJI_CELEBRATE} <b>Deal GC Created</b>\n\n{emojis.EMOJI_LINK} <b>Link:</b> {info.invite_link}\n\nPlease share the link with both parties and have them join to proceed.",
        parse_mode=HTML,
    )
    _spawn(service.init_instant_deal_room(ctx.application, deal))


async def instant_role_callback(update, ctx):
    q = update.callback_query
    user = q.from_user
    parts = q.data.split(":")  # inst:role:buyer:{deal_no}
    role, deal_no = parts[2], int(parts[3])

    deal = await db.get_deal_by_no(deal_no)
    if not deal:
        await q.answer("Deal not found.", show_alert=True)
        return

    if deal.get("status") == "closed":
        await q.answer("This deal is closed.", show_alert=True)
        return

    buyer_id = deal.get("buyer_id")
    seller_id = deal.get("seller_id")

    if role == "buyer":
        if buyer_id and buyer_id != user.id:
            await q.answer("Buyer role is already taken. Middleman can reassign via /buyer.", show_alert=True)
            return
        updates = {"buyer_id": user.id, "buyer_username": user.username or user.first_name}
        if seller_id == user.id:
            updates["seller_id"] = None
            updates["seller_username"] = None
        await db.update_deal(deal["_id"], updates)
        await q.answer("You are registered as the Buyer!")
        await q.message.reply_text(f"{emojis.EMOJI_BUYER} <b>Role Confirmed:</b> @{esc(user.username or user.first_name)} is the <b>Buyer</b>.", parse_mode=HTML)

    elif role == "seller":
        if seller_id and seller_id != user.id:
            await q.answer("Seller role is already taken. Middleman can reassign via /seller.", show_alert=True)
            return
        updates = {"seller_id": user.id, "seller_username": user.username or user.first_name}
        if buyer_id == user.id:
            updates["buyer_id"] = None
            updates["buyer_username"] = None
        await db.update_deal(deal["_id"], updates)
        await q.answer("You are registered as the Seller!")
        await q.message.reply_text(f"{emojis.EMOJI_SELLER} <b>Role Confirmed:</b> @{esc(user.username or user.first_name)} is the <b>Seller</b>.", parse_mode=HTML)

    # Check if both are now claimed
    fresh = await db.get_deal_by_no(deal_no)
    if fresh.get("buyer_id") and fresh.get("seller_id"):
        # Auto-revoke invite link once buyer and seller are claimed
        await service.revoke_deal_invite(ctx.bot, fresh)

        if fresh.get("status") == "instant_role_selection":
            await db.update_deal(fresh["_id"], {"status": "instant_details_pending"})
            await q.message.reply_text(texts.instant_deal_details_prompt(), parse_mode=HTML, link_preview_options=NO_PREVIEW)


async def group_buyer_cmd(update, ctx):
    """Middleman replies to any message in group with /buyer to set that user as buyer."""
    msg = update.message
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_text("Please reply to a user's message to set them as Buyer.")
        return
    if not _is_mm(msg.from_user.id, msg.from_user.username):
        await msg.reply_text("Only the middleman can reassign roles.")
        return

    deal = await db.get_deal_by_group(msg.chat_id)
    if not deal:
        return
    if deal.get("status") == "closed":
        await msg.reply_text("This deal is closed.")
        return

    target = msg.reply_to_message.from_user
    updates = {"buyer_id": target.id, "buyer_username": target.username or target.first_name}
    if deal.get("seller_id") == target.id:
        updates["seller_id"] = None
        updates["seller_username"] = None
    await db.update_deal(deal["_id"], updates)
    await msg.reply_text(f"✅ Role updated: @{esc(target.username or target.first_name)} is now the <b>Buyer</b>.", parse_mode=HTML)

    fresh = await db.get_deal_by_no(deal["deal_no"])
    if fresh.get("buyer_id") and fresh.get("seller_id"):
        await service.revoke_deal_invite(ctx.bot, fresh)
        if fresh.get("status") == "instant_role_selection":
            await db.update_deal(fresh["_id"], {"status": "instant_details_pending"})
            await msg.reply_text(texts.instant_deal_details_prompt(), parse_mode=HTML, link_preview_options=NO_PREVIEW)


async def group_seller_cmd(update, ctx):
    """Middleman replies to any message in group with /seller to set that user as seller."""
    msg = update.message
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_text("Please reply to a user's message to set them as Seller.")
        return
    if not _is_mm(msg.from_user.id, msg.from_user.username):
        await msg.reply_text("Only the middleman can reassign roles.")
        return

    deal = await db.get_deal_by_group(msg.chat_id)
    if not deal:
        return
    if deal.get("status") == "closed":
        await msg.reply_text("This deal is closed.")
        return

    target = msg.reply_to_message.from_user
    updates = {"seller_id": target.id, "seller_username": target.username or target.first_name}
    if deal.get("buyer_id") == target.id:
        updates["buyer_id"] = None
        updates["buyer_username"] = None
    await db.update_deal(deal["_id"], updates)
    await msg.reply_text(f"✅ Role updated: @{esc(target.username or target.first_name)} is now the <b>Seller</b>.", parse_mode=HTML)

    fresh = await db.get_deal_by_no(deal["deal_no"])
    if fresh.get("buyer_id") and fresh.get("seller_id"):
        await service.revoke_deal_invite(ctx.bot, fresh)
        if fresh.get("status") == "instant_role_selection":
            await db.update_deal(fresh["_id"], {"status": "instant_details_pending"})
            await msg.reply_text(texts.instant_deal_details_prompt(), parse_mode=HTML, link_preview_options=NO_PREVIEW)


async def buyer_confirm_deal_cb(update, ctx):
    q = update.callback_query
    deal_no = int(q.data.split(":")[2])
    deal = await db.get_deal_by_no(deal_no)
    if not deal:
        await q.answer("Deal not found.", show_alert=True)
        return

    if deal.get("status") == "closed":
        await q.answer("This deal is closed.", show_alert=True)
        return

    # Check that caller is Buyer or Middleman
    if q.from_user.id != deal.get("buyer_id") and not _is_mm(q.from_user.id, q.from_user.username):
        await q.answer("Only the designated Buyer can confirm this deal.", show_alert=True)
        return

    if deal.get("status") in ("buyer_confirmed", "deal_confirmed", "active"):
        await q.answer("Deal is already confirmed!", show_alert=True)
        return

    await q.answer("Deal confirmed!")
    await db.update_deal(deal["_id"], {"status": "buyer_confirmed", "confirmed_at": utcnow()})

    buyer_tag = f"@{esc(deal.get('buyer_username') or 'Buyer')}"
    chat_id = deal.get("group_chat_id")

    # Update Confirm button to indicate buyer confirmation
    try:
        await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirmed by Buyer", callback_data="noop")]
        ]))
    except Exception:
        pass

    # Unpin the role-selection message if it exists
    role_msg_id = deal.get("pinned_role_message_id")
    if role_msg_id and chat_id:
        try:
            await ctx.bot.unpin_chat_message(chat_id, role_msg_id)
        except Exception:
            pass

    # Pin the deal summary message
    if chat_id:
        try:
            await ctx.bot.pin_chat_message(chat_id, q.message.message_id, disable_notification=True)
        except Exception:
            pass
        await db.update_deal(deal["_id"], {"pinned_deal_info_id": q.message.message_id})

    # Mention Middleman with button to confirm and proceed to payment
    mm_kb = _kb(_btn("Confirm to Proceed to Payment", f"inst:mm_proceed:{deal_no}", GREEN, icon=emojis.get_custom_id("SUCCESS")))
    await q.message.reply_text(
        texts.buyer_confirmed_wait_mm_text(buyer_tag),
        reply_markup=mm_kb,
        parse_mode=HTML,
    )


async def mm_proceed_payment_cb(update, ctx):
    q = update.callback_query
    deal_no = int(q.data.split(":")[2])
    deal = await db.get_deal_by_no(deal_no)
    if not deal:
        await q.answer("Deal not found.", show_alert=True)
        return

    if not _is_mm(q.from_user.id, q.from_user.username):
        await q.answer("Only the middleman can confirm to proceed for payment.", show_alert=True)
        return

    if deal.get("status") == "closed":
        await q.answer("This deal is closed.", show_alert=True)
        return

    await q.answer("Proceeding to payment!")
    await db.update_deal(deal["_id"], {"status": "deal_confirmed", "mm_approved_at": utcnow()})

    # Update the MM proceed button so it cannot be double-tapped
    try:
        await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approved by Middleman", callback_data="noop")]
        ]))
    except Exception:
        pass

    fee = deal.get("custom_fee") or settings.get("default_fee", "50 INR")
    amt = str(deal.get("amount", "0"))
    curr = str(deal.get("currency", "INR")).upper()
    net = str(deal.get("payment_network", "UPI")).upper()

    is_crypto = (
        curr in ("USDT", "BTC", "ETH", "SOL", "TON", "CRYPTO", "LTC", "TRX", "BNB", "XRP", "DOGE")
        or "CRYPTO" in curr
        or ("CRYPTO" in net and curr != "INR")
    )

    if is_crypto:
        # Step 1: Crypto payment network selection (no premature buyer confirmation button)
        kb = _build_crypto_menu(deal_no, curr, page=0)
        await q.message.reply_text(
            texts.payment_details_crypto_prompt(amt, curr, fee),
            reply_markup=kb,
            parse_mode=HTML,
        )
    else:
        # Step 2: Consolidated INR payment card, followed by confirmation button after delay
        upi_id = settings.get("upi_id", config.DEFAULT_UPI_ID) or f"Contact @{config.MM_USERNAME} for UPI ID"
        sent = await q.message.reply_text(
            texts.payment_details_upi(amt, curr, fee, upi_id),
            parse_mode=HTML,
        )
        await asyncio.sleep(3)
        buyer_kb = _kb(_btn("✅ I've sent the payment", f"inst:buyer_paid:{deal_no}", GREEN, icon=emojis.get_custom_id("SUCCESS")))
        try:
            await sent.edit_reply_markup(reply_markup=buyer_kb)
        except Exception:
            buyer_tag = f"@{esc(deal.get('buyer_username') or 'Buyer')}"
            await q.message.reply_text(
                texts.payment_verification_text(buyer_tag),
                reply_markup=buyer_kb,
                parse_mode=HTML,
            )


async def noop_cb(update, ctx):
    if update.callback_query:
        await update.callback_query.answer()


def _build_crypto_menu(deal_no: int, currency: str = "Crypto", page: int = 0) -> InlineKeyboardMarkup:
    all_coins = list(settings.CRYPTO_NETWORKS.items())
    curr_upper = (currency or "CRYPTO").upper()

    if curr_upper == "USDT":
        filtered = [item for item in all_coins if item[0].startswith("usdt_")]
    elif curr_upper in ("BTC", "BITCOIN"):
        filtered = [item for item in all_coins if item[0] == "btc"]
    elif curr_upper in ("ETH", "ETHEREUM"):
        filtered = [item for item in all_coins if item[0] in ("eth", "base", "arb")]
    elif curr_upper in ("SOL", "SOLANA"):
        filtered = [item for item in all_coins if item[0] in ("sol", "usdt_sol")]
    elif curr_upper in ("TON", "TONCOIN"):
        filtered = [item for item in all_coins if item[0] in ("ton", "usdt_ton")]
    elif curr_upper in ("LTC", "TRX", "BNB", "XRP", "DOGE", "POL", "MATIC", "AVAX", "XMR", "ADA", "DOT", "NEAR", "BCH", "SUI", "APT", "USDC"):
        k_key = curr_upper.lower()
        filtered = [item for item in all_coins if item[0] == k_key or item[1].get("symbol") == curr_upper]
    else:
        filtered = all_coins

    if not filtered:
        filtered = all_coins

    page_size = 6
    total_pages = (len(filtered) + page_size - 1) // page_size
    page = max(0, min(page, max(0, total_pages - 1)))

    current_slice = filtered[page * page_size : (page + 1) * page_size]
    btns = []
    for key, info in current_slice:
        btns.append([_btn(f"🪙 {info['symbol']} ({info['network']})", f"inst:crypto_pick:{deal_no}:{key}", BLUE)])

    nav = []
    if page > 0:
        nav.append(_btn("⬅️ Prev", f"inst:crypto_page:{deal_no}:{page-1}", BLUE))
    if page < total_pages - 1:
        nav.append(_btn("Next ➡️", f"inst:crypto_page:{deal_no}:{page+1}", BLUE))
    if nav:
        btns.append(nav)

    return InlineKeyboardMarkup(btns)


async def instant_crypto_callback(update, ctx):
    q = update.callback_query
    parts = q.data.split(":")
    action = parts[1]
    deal_no = int(parts[2])
    deal = await db.get_deal_by_no(deal_no)
    curr = deal.get("currency", "Crypto") if deal else "Crypto"

    if action == "crypto_page":
        page = int(parts[3])
        await q.answer()
        await q.edit_reply_markup(_build_crypto_menu(deal_no, curr, page))

    elif action == "crypto_pick":
        coin_key = parts[3]
        info = settings.CRYPTO_NETWORKS.get(coin_key, {})
        addr = settings.get_crypto_wallet(coin_key)

        if not addr:
            await q.answer(f"⚠️ No wallet configured for {info.get('name', coin_key)}. Contact @{config.MM_USERNAME}", show_alert=True)
            return

        await q.answer()

        t = texts.payment_details_crypto_address(
            coin_name=info.get("name", coin_key),
            symbol=info.get("symbol", coin_key),
            network=info.get("network", "N/A"),
            address=addr,
        )

        try:
            await q.edit_message_text(t, parse_mode=HTML, reply_markup=None)
        except Exception:
            pass

        # 3-second delay before displaying confirmation button on deposit message
        await asyncio.sleep(3)

        buyer_kb = _kb(_btn("✅ I've sent the payment", f"inst:buyer_paid:{deal_no}", GREEN, icon=emojis.get_custom_id("SUCCESS")))
        try:
            await q.message.edit_reply_markup(reply_markup=buyer_kb)
        except Exception:
            buyer_tag = f"@{esc(deal.get('buyer_username') or 'Buyer')}" if deal else "Buyer"
            await q.message.reply_text(
                texts.payment_verification_text(buyer_tag),
                reply_markup=buyer_kb,
                parse_mode=HTML,
            )


async def payment_sent_cb(update, ctx):
    q = update.callback_query
    parts = q.data.split(":")
    action = parts[1]
    deal_no = int(parts[2])
    deal = await db.get_deal_by_no(deal_no)
    if not deal:
        await q.answer()
        return

    if deal.get("buyer_payment_confirmed"):
        await q.answer("Payment confirmation has already been recorded.", show_alert=True)
        return

    if action == "buyer_paid":
        # Buyer confirms they sent payment
        if q.from_user.id != deal.get("buyer_id") and not _is_mm(q.from_user.id):
            await q.answer("Only the buyer can confirm this.", show_alert=True)
            return
        await q.answer("Payment confirmation noted!")
        await db.update_deal(deal["_id"], {"buyer_payment_confirmed": True, "buyer_paid_at": utcnow()})

        buyer_tag = f"@{esc(deal.get('buyer_username') or 'Buyer')}"
        await q.message.reply_text(
            f"{emojis.EMOJI_SUCCESS} {buyer_tag} confirms payment has been sent.\n\n"
            f"{emojis.EMOJI_HOURGLASS} Waiting for middleman to verify receipt.",
            parse_mode=HTML,
        )

        # Show MM confirm button
        mm_kb = _kb(_btn("Confirm Payment Received", f"inst:mm_paid:{deal_no}", GREEN, icon=emojis.get_custom_id("MONEY")))
        await q.message.reply_text(
            f"{emojis.EMOJI_BELL} @{esc(config.MM_USERNAME)} — please confirm once payment is received.",
            reply_markup=mm_kb,
            parse_mode=HTML,
        )
        return

    # Legacy: "paid_sent" fallback
    await q.answer("Payment confirmation noted!")
    await db.update_deal(deal["_id"], {"buyer_payment_confirmed": True, "buyer_paid_at": utcnow()})

    buyer_tag = f"@{esc(deal.get('buyer_username') or 'Buyer')}"
    await q.message.reply_text(
        f"{emojis.EMOJI_SUCCESS} {buyer_tag} confirms payment has been sent.\n\n"
        f"{emojis.EMOJI_HOURGLASS} Waiting for middleman to verify receipt.",
        parse_mode=HTML,
    )
    mm_kb = _kb(_btn("Confirm Payment Received", f"inst:mm_paid:{deal_no}", GREEN, icon=emojis.get_custom_id("MONEY")))
    await q.message.reply_text(
        f"{emojis.EMOJI_BELL} @{esc(config.MM_USERNAME)} — please confirm once payment is received.",
        reply_markup=mm_kb,
        parse_mode=HTML,
    )


async def mm_confirm_payment_cb(update, ctx):
    q = update.callback_query
    if not _is_mm(q.from_user.id, q.from_user.username):
        await q.answer("Only the middleman can confirm payment receipt.", show_alert=True)
        return

    deal_no = int(q.data.split(":")[2])
    deal = await db.get_deal_by_no(deal_no)
    if not deal:
        await q.answer("Deal not found.", show_alert=True)
        return

    if deal.get("status") == "closed":
        await q.answer("Deal is closed.", show_alert=True)
        return

    await q.answer("Payment verified!")
    tat_secs = deal.get("tat_seconds")
    if not tat_secs or tat_secs <= 0:
        await q.message.reply_text(
            f"{emojis.EMOJI_WARNING} <b>TAT not set!</b>\n\n"
            "Please configure the turnaround time using <code>/settat &lt;duration&gt;</code> before starting the deal.",
            parse_mode=HTML,
        )
        return

    await service.start_deal_tat(ctx.bot, deal, q.from_user.id)


# ------------------------------------------------------------------ Middleman Deal Commands in Group
async def settat_cmd(update, ctx):
    """Middleman /settat command: sets the turnaround time for the deal."""
    msg = update.message
    if not _is_mm(msg.from_user.id, msg.from_user.username):
        await msg.reply_text("⚠️ This command is reserved for the middleman.")
        return

    deal = await db.get_deal_by_group(msg.chat_id)
    if not deal:
        await msg.reply_text("❌ No deal found in this group.")
        return

    if deal.get("status") == "closed":
        await msg.reply_text("❌ This deal is closed.")
        return

    if not ctx.args:
        await msg.reply_text(
            "⚠️ <b>Usage:</b> <code>/settat &lt;duration&gt;</code>\n\n"
            "<b>Examples:</b>\n"
            "• <code>/settat 15m</code> or <code>15mins</code>\n"
            "• <code>/settat 1h</code> or <code>2hours</code>\n"
            "• <code>/settat 1d</code> or <code>3days</code>\n"
            "• <code>/settat 1d 12h</code>",
            parse_mode=HTML,
        )
        return

    raw_arg = " ".join(ctx.args).strip()
    try:
        secs = parse_tat(raw_arg)
    except ValueError as e:
        await msg.reply_text(str(e), parse_mode=HTML)
        return

    updates = {"tat_seconds": secs, "tat_str": raw_arg}
    if deal.get("status") == "active" and deal.get("tat_started_at"):
        now = utcnow()
        new_deadline = now + timedelta(seconds=secs)
        updates["tat_deadline"] = new_deadline
        updates["expiry_notified"] = False

    await db.update_deal(deal["_id"], updates)
    await db.record_deal_audit(deal["_id"], "settat", msg.from_user.id, {"seconds": secs, "input": raw_arg})
    await msg.reply_text(
        f"{emojis.EMOJI_CLOCK} <b>Turnaround Time (TAT) Configured</b>\n\n"
        f"TAT Duration: <b>{fmt_duration(secs)}</b>\n"
        "Execute /begin when payment is verified to initiate the countdown.",
        parse_mode=HTML,
    )


async def begin_cmd(update, ctx):
    """Middleman /begin command: confirms payment and activates TAT countdown."""
    msg = update.message
    if not _is_mm(msg.from_user.id, msg.from_user.username):
        await msg.reply_text("⚠️ This command is reserved for the middleman.")
        return

    deal = await db.get_deal_by_group(msg.chat_id)
    if not deal:
        await msg.reply_text("❌ No deal found in this group.")
        return

    if deal.get("status") == "closed":
        await msg.reply_text("❌ This deal is closed.")
        return

    tat_secs = deal.get("tat_seconds")
    if not tat_secs or tat_secs <= 0:
        await msg.reply_text(
            f"{emojis.EMOJI_WARNING} <b>TAT duration is missing!</b>\n\n"
            "Please configure the TAT first using:\n"
            "<code>/settat &lt;duration&gt;</code> (e.g. <code>/settat 24h</code> or <code>/settat 1d</code>)",
            parse_mode=HTML,
        )
        return

    await service.start_deal_tat(ctx.bot, deal, msg.from_user.id)


async def extendtat_cmd(update, ctx):
    """Middleman /extendtat command: extends the active deadline."""
    msg = update.message
    if not _is_mm(msg.from_user.id, msg.from_user.username):
        await msg.reply_text("⚠️ This command is reserved for the middleman.")
        return

    deal = await db.get_deal_by_group(msg.chat_id)
    if not deal:
        await msg.reply_text("❌ No deal found in this group.")
        return

    if deal.get("status") == "closed":
        await msg.reply_text("❌ This deal is closed.")
        return

    if not ctx.args:
        await msg.reply_text(
            "⚠️ <b>Usage:</b> <code>/extendtat &lt;duration&gt;</code>\n\n"
            "<b>Examples:</b>\n"
            "• <code>/extendtat 30m</code>\n"
            "• <code>/extendtat 1h</code>\n"
            "• <code>/extendtat 5hours</code>\n"
            "• <code>/extendtat 1d</code>",
            parse_mode=HTML,
        )
        return

    raw_arg = " ".join(ctx.args).strip()
    try:
        ext_secs = parse_tat(raw_arg)
    except ValueError as e:
        await msg.reply_text(str(e), parse_mode=HTML)
        return

    await service.extend_deal_tat(ctx.bot, deal, ext_secs, raw_arg, msg.from_user.id)


async def hold_cmd(update, ctx):
    """Middleman /hold command: updates group title to 'MM <No> <Currency> hold' and sets status to held."""
    msg = update.message
    if not _is_mm(msg.from_user.id, msg.from_user.username):
        await msg.reply_text("⚠️ This command is reserved for the middleman.")
        return

    deal = await db.get_deal_by_group(msg.chat_id)
    if not deal:
        await msg.reply_text("❌ No deal found in this group.")
        return

    if deal.get("status") == "closed":
        await msg.reply_text("❌ This deal is closed.")
        return

    new_title = await service.set_deal_title_hold(ctx.bot, deal)
    await db.update_deal(deal["_id"], {"status": "held", "held_at": utcnow()})
    await db.record_deal_audit(deal["_id"], "hold", msg.from_user.id, {"title": new_title})

    hold_text = settings.render_template(
        "hold",
        deal_id=str(deal.get("deal_no", "")),
        title=new_title,
        mm=config.MM_USERNAME,
    )
    await msg.reply_text(hold_text, parse_mode=HTML)


async def release_cmd(update, ctx):
    """Middleman /release command: updates group title to 'MM <No> <Currency> Released' and sets status to released."""
    msg = update.message
    if not _is_mm(msg.from_user.id, msg.from_user.username):
        await msg.reply_text("⚠️ This command is reserved for the middleman.")
        return

    deal = await db.get_deal_by_group(msg.chat_id)
    if not deal:
        await msg.reply_text("❌ No deal found in this group.")
        return

    if deal.get("status") == "closed":
        await msg.reply_text("❌ This deal is closed.")
        return

    new_title = await service.set_deal_title_release(ctx.bot, deal)
    await db.update_deal(deal["_id"], {"status": "released", "released_at": utcnow()})
    await db.record_deal_audit(deal["_id"], "release", msg.from_user.id, {"title": new_title})

    release_text = settings.render_template(
        "release",
        deal_id=str(deal.get("deal_no", "")),
        title=new_title,
        mm=config.MM_USERNAME,
    )
    await msg.reply_text(release_text, parse_mode=HTML)


async def close_cmd(update, ctx):
    """Middleman /close command: asks for confirmation before closing deal."""
    msg = update.message
    if not _is_mm(msg.from_user.id, msg.from_user.username):
        await msg.reply_text("⚠️ This command is reserved for the middleman.")
        return

    deal = await db.get_deal_by_group(msg.chat_id)
    if not deal:
        await msg.reply_text("❌ No deal found in this group.")
        return

    if deal.get("status") == "closed":
        await msg.reply_text("ℹ️ This deal is already closed.")
        return

    deal_no = deal["deal_no"]
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔴 Confirm Close", callback_data=f"deal:close_confirm:{deal_no}", api_kwargs={"style": "danger"}),
            InlineKeyboardButton("⚪ Cancel", callback_data=f"deal:close_cancel:{deal_no}"),
        ]
    ])
    await msg.reply_text(
        f"{emojis.EMOJI_WARNING} <b>Confirm Deal Closure</b>\n\n"
        f"Are you sure you want to close Deal #{deal_no}?\n\n"
        "• All active TAT countdowns will be stopped.\n"
        "• Buyer and seller will be muted.\n"
        "• Outstanding invitation links will be revoked.",
        reply_markup=kb,
        parse_mode=HTML,
    )


async def deal_close_callback(update, ctx):
    q = update.callback_query
    if not _is_mm(q.from_user.id, q.from_user.username):
        await q.answer("Only the middleman can close this deal.", show_alert=True)
        return

    parts = q.data.split(":")
    action, deal_no = parts[1], int(parts[2])
    deal = await db.get_deal_by_no(deal_no)
    if not deal:
        await q.answer("Deal not found.", show_alert=True)
        return

    if action == "close_cancel":
        await q.answer("Closure cancelled.")
        await q.edit_message_text("❌ <b>Deal closure cancelled.</b>", parse_mode=HTML)
        return

    if action == "close_confirm":
        await q.answer("Closing deal...")
        if deal.get("status") == "closed":
            await q.edit_message_text("ℹ️ Deal is already closed.", parse_mode=HTML)
            return

        # 1. Update database atomically
        await db.close_deal(deal["_id"], q.from_user.id)

        # 2. Revoke invitation links
        await service.revoke_deal_invite(ctx.bot, deal)

        # 3. Mute participants
        await service.mute_deal_participants(
            ctx.bot,
            deal["group_chat_id"],
            deal.get("buyer_id"),
            deal.get("seller_id"),
        )

        # 4. Notify group
        closure_text = settings.render_template(
            "deal_closure",
            deal_id=str(deal_no),
            mm=config.MM_USERNAME,
        )
        await q.edit_message_text("🚪 <b>Deal Closed.</b>", parse_mode=HTML)
        await safe_send(ctx.bot, deal["group_chat_id"], closure_text)


async def paid_cmd(update, ctx):
    """Middleman /paid command in group chat."""
    msg = update.message
    if not _is_mm(msg.from_user.id, msg.from_user.username):
        await msg.reply_text("Only the middleman can confirm payments.")
        return

    deal = await db.get_deal_by_group(msg.chat_id)
    if not deal:
        await msg.reply_text("No active deal found in this group.")
        return

    if deal.get("status") == "closed":
        await msg.reply_text("This deal is closed.")
        return

    tat_secs = deal.get("tat_seconds")
    if not tat_secs or tat_secs <= 0:
        await msg.reply_text(
            f"{emojis.EMOJI_WARNING} <b>TAT not set!</b>\n\n"
            "Please configure the turnaround time using <code>/settat &lt;duration&gt;</code> before starting the deal.",
            parse_mode=HTML,
        )
        return

    await service.start_deal_tat(ctx.bot, deal, msg.from_user.id)


async def complete_cmd(update, ctx):
    """Middleman /complete or /done command to finish deal and output vouch."""
    msg = update.message
    if not _is_mm(msg.from_user.id, msg.from_user.username):
        await msg.reply_text("Only the middleman can complete deals.")
        return

    deal = await db.get_deal_by_group(msg.chat_id)
    if not deal:
        await msg.reply_text("No active deal found in this group.")
        return

    if deal.get("status") == "closed":
        await msg.reply_text("This deal is already closed.")
        return

    await db.update_deal(deal["_id"], {"status": "completed", "completed_at": utcnow()})
    vouch_text = settings.render_vouch(deal)

    vouch_msg = await msg.reply_text(
        f"🎉 <b>Deal Completed Successfully!</b>\n\n"
        f"Funds have been released. Thank you for using {texts.MM} Escrow Service!\n\n"
        f"<b>Please drop a vouch in our channel:</b>\n\n{vouch_text}",
        parse_mode=HTML,
        link_preview_options=NO_PREVIEW,
    )

    # Prompt Middleman with confirmation button to forward vouch to vouches channel
    vouch_target = parse_channel_target(settings.get("vouch_channel_url", config.VOUCH_CHANNEL_URL))
    fwd_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📢 Forward to Vouches Channel", callback_data=f"vouch:fwd:{deal['deal_no']}:{vouch_msg.message_id}"),
            InlineKeyboardButton("❌ Don't Forward", callback_data=f"vouch:no:{deal['deal_no']}"),
        ]
    ])
    await msg.reply_text(
        f"📢 <b>Forward Vouch to Channel?</b>\n\n"
        f"Destination: <code>{esc(str(vouch_target))}</code>\n"
        f"<i>(Only middleman @{config.MM_USERNAME} can confirm)</i>",
        reply_markup=fwd_kb,
        parse_mode=HTML,
    )


async def vouch_callback(update, ctx):
    """Handles vouch forwarding confirmation (visible/actionable by middleman only)."""
    q = update.callback_query
    user = q.from_user
    if not _is_mm(user.id, user.username):
        await q.answer(f"⚠️ Visible only to middleman: only @{config.MM_USERNAME} can confirm forwarding.", show_alert=True)
        return

    parts = q.data.split(":")
    action = parts[1]
    deal_no = int(parts[2])

    if action == "no":
        await q.answer("Vouch forwarding dismissed.")
        await q.edit_message_text("❌ <b>Vouch forwarding dismissed.</b>", parse_mode=HTML)
        return

    deal = await db.get_deal_by_no(deal_no)
    target_channel = parse_channel_target(settings.get("vouch_channel_url", config.VOUCH_CHANNEL_URL))
    if not target_channel:
        await q.answer("Vouch channel is not configured in settings.", show_alert=True)
        return

    await q.answer("Forwarding vouch...")
    if action == "fwd_msg":
        msg_id = int(parts[3])
        chat_id = deal.get("group_chat_id") if deal else q.message.chat_id
        try:
            await ctx.bot.forward_message(chat_id=target_channel, from_chat_id=chat_id, message_id=msg_id)
            await q.edit_message_text(f"✅ <b>Vouch forwarded to {esc(str(target_channel))}!</b>", parse_mode=HTML)
            if deal:
                await db.update_deal(deal["_id"], {"vouch_forwarded": True, "vouch_forwarded_at": utcnow()})
        except Exception as e:
            log.warning("Could not forward vouch: %s", e)
            try:
                vouch_text = settings.render_vouch(deal) if deal else "Vouch received!"
                await ctx.bot.send_message(chat_id=target_channel, text=vouch_text, parse_mode=HTML, link_preview_options=NO_PREVIEW)
                await q.edit_message_text(f"✅ <b>Vouch posted to {esc(str(target_channel))}!</b>", parse_mode=HTML)
                if deal:
                    await db.update_deal(deal["_id"], {"vouch_forwarded": True, "vouch_forwarded_at": utcnow()})
            except Exception as e2:
                await q.edit_message_text(
                    f"⚠️ <b>Could not forward to {esc(str(target_channel))}:</b> {esc(str(e2))}\n\n"
                    f"Please ensure @{ctx.bot.username} is added as an <b>Admin</b> in the channel with <b>Post Messages</b> permission.",
                    parse_mode=HTML,
                )
    elif action == "fwd":
        vouch_text = settings.render_vouch(deal)
        try:
            await ctx.bot.send_message(chat_id=target_channel, text=vouch_text, parse_mode=HTML, link_preview_options=NO_PREVIEW)
            await q.edit_message_text(f"✅ <b>Vouch successfully posted to {esc(str(target_channel))}!</b>", parse_mode=HTML)
            if deal:
                await db.update_deal(deal["_id"], {"vouch_forwarded": True, "vouch_forwarded_at": utcnow()})
        except Exception as e:
            log.warning("Could not post vouch: %s", e)
            await q.edit_message_text(
                f"⚠️ <b>Could not post to {esc(str(target_channel))}:</b> {esc(str(e))}\n\n"
                f"Please ensure @{ctx.bot.username} is added as an <b>Admin</b> in the channel with <b>Post Messages</b> permission.",
                parse_mode=HTML,
            )


# ------------------------------------------------------------------ Chat Member Admission Restrictions
async def on_chat_member_update(update, ctx):
    """Enforces max 2 participants (1 buyer, 1 seller). Revokes link and welcomes new joins."""
    cm = update.chat_member
    if not cm:
        return

    chat = cm.chat
    deal = await db.get_deal_by_group(chat.id)
    if not deal:
        return

    new_user = cm.new_chat_member.user if cm.new_chat_member else None
    if not new_user or new_user.is_bot:
        return

    # Only process actual join events (joining group from left/kicked/none)
    new_status = getattr(cm.new_chat_member, "status", None)
    old_status = getattr(cm.old_chat_member, "status", None) if cm.old_chat_member else None
    joined_statuses = ("member", "administrator", "creator")
    if new_status not in joined_statuses:
        return  # user left, was kicked, or restricted - do not send welcome or admit
    if old_status in joined_statuses:
        return  # user was already in the group (e.g. role/title change)

    # Allow Middleman
    if _is_mm(new_user.id, new_user.username):
        return

    # If deal is closed, do NOT kick - mute only
    if deal.get("status") == "closed":
        await service.mute_deal_participants(ctx.bot, chat.id, new_user.id)
        return

    buyer_id = deal.get("buyer_id")
    seller_id = deal.get("seller_id")

    # If both participants are already set
    if buyer_id and seller_id:
        if new_user.id != buyer_id and new_user.id != seller_id:
            # Both roles filled: revoke invite link and mute extra joiner (approval required)
            await service.revoke_deal_invite(ctx.bot, deal)
            await service.mute_deal_participants(ctx.bot, chat.id, new_user.id)
            await safe_send(
                ctx.bot,
                chat.id,
                f"⚠️ {user_mention(new_user.id, new_user.username, new_user.first_name)} joined, but Buyer & Seller roles are already confirmed.\n"
                f"Participant has been muted. Approval from Middleman @{config.MM_USERNAME} required to participate.",
            )
            return
        else:
            # Both participants are in, revoke invitation link
            await service.revoke_deal_invite(ctx.bot, deal)
            return

    # Welcoming message prompting for role
    mention = user_mention(new_user.id, new_user.username, new_user.first_name)
    dno = deal["deal_no"]
    b_id = emojis.get_custom_id("BUYER")
    s_id = emojis.get_custom_id("SELLER")
    b_kw = {"style": "primary"}
    if b_id:
        b_kw["icon_custom_emoji_id"] = b_id
    s_kw = {"style": "success"}
    if s_id:
        s_kw["icon_custom_emoji_id"] = s_id
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Buyer", callback_data=f"inst:role:buyer:{dno}", api_kwargs=b_kw),
            InlineKeyboardButton("Seller", callback_data=f"inst:role:seller:{dno}", api_kwargs=s_kw),
        ]
    ])
    await safe_send(
        ctx.bot,
        chat.id,
        f"{emojis.EMOJI_WAVE} Welcome {mention} to Deal #{config.DEAL_ID_PREFIX}{dno}!\n\n"
        "Please confirm your role in this deal below:",
        reply_markup=kb,
    )


# ------------------------------------------------------------------ Message Routers
async def on_group_message(update, ctx):
    msg = update.message
    if not msg or not msg.text:
        return

    chat_id = msg.chat_id
    deal = await db.get_deal_by_group(chat_id)
    if not deal:
        return

    text = msg.text.strip()
    status = deal.get("status")

    if status == "closed":
        return

    # Payment sent reply: "Yes" or "Confirm"
    if status in ("payment_pending", "deal_confirmed") and text.lower() in ("yes", "confirm", "sent", "paid"):
        mm_kb = _kb(_btn("💰 Confirm Payment Received", f"inst:mm_paid:{deal['deal_no']}", GREEN))
        await msg.reply_text(texts.payment_pending_acknowledgement(), reply_markup=mm_kb, parse_mode=HTML)
        return

    # Deal details submission
    if status in ("instant_details_pending", "instant_role_selection"):
        parsed = await ai_parser.parse_deal_details(text)
        if parsed and parsed.get("amount") and parsed.get("deal_type"):
            deal_no = deal["deal_no"]
            await db.update_deal(deal["_id"], {
                "deal_type": parsed["deal_type"],
                "purpose": parsed["deal_type"],
                "tat": parsed["tat"],
                "tat_seconds": parsed["tat_seconds"],
                "conditions": parsed["conditions"],
                "amount": parsed["amount"],
                "currency": parsed["currency"],
                "payment_network": parsed["payment_network"],
                "status": "instant_confirmation_pending",
            })

            fresh = await db.get_deal_by_no(deal_no)
            buyer_tag = f"@{esc(fresh.get('buyer_username') or 'Buyer')}"
            seller_tag = f"@{esc(fresh.get('seller_username') or 'Seller')}"

            summary = texts.instant_deal_summary(fresh, buyer_tag, seller_tag)
            kb = _kb(_btn("Confirm Deal", f"inst:confirm:{deal_no}", GREEN, icon=emojis.get_custom_id("SUCCESS")))
            await msg.reply_text(summary, reply_markup=kb, parse_mode=HTML)
            return

    # Vouch detection in deal group (buyer/seller drops a vouch)
    lower = text.lower()
    is_vouch = (
        "vouch" in lower
        or "+rep" in lower
        or "vouched" in lower
        or ("legit" in lower and ("mm" in lower or config.MM_USERNAME.lower() in lower))
        or (f"@{config.MM_USERNAME.lower()}" in lower and any(w in lower for w in ("deal", "completed", "thanks", "done", "trusted")))
    )
    if is_vouch and status in ("completed", "active", "closed", "deal_confirmed", "payment_pending"):
        vouch_target = parse_channel_target(settings.get("vouch_channel_url", config.VOUCH_CHANNEL_URL))
        vouch_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📢 Forward to Vouches Channel", callback_data=f"vouch:fwd_msg:{deal['deal_no']}:{msg.message_id}"),
                InlineKeyboardButton("❌ Don't Forward", callback_data=f"vouch:no:{deal['deal_no']}"),
            ]
        ])
        await msg.reply_text(
            f"⭐ <b>Vouch Detected!</b>\n\n"
            f"Forward this vouch message to <code>{esc(str(vouch_target))}</code>?\n"
            f"<i>(Only middleman @{config.MM_USERNAME} can confirm)</i>",
            reply_markup=vouch_kb,
            parse_mode=HTML,
        )
        return


async def on_private_message(update, ctx):
    msg = update.message
    if msg is None:
        return
    user = update.effective_user

    if msg.users_shared:
        return await _users_shared(msg)
    if msg.forward_origin:
        return await _forwarded(msg)

    # 1. Admin session (setting a field, crypto address, template, GC photo, or start number)
    admin_sess = _admin_sessions.get(user.id)
    if admin_sess and _is_mm(user.id, user.username):
        action = admin_sess["action"]

        if msg.text and msg.text.strip() == "/cancel":
            del _admin_sessions[user.id]
            await msg.reply_text("❌ Action cancelled.")
            return

        # Handle GC Profile Photo Upload (photo message)
        if action == "set_gc_photo":
            if msg.photo:
                photo_file_id = msg.photo[-1].file_id
                await settings.set_setting("gc_photo_file_id", photo_file_id)
                del _admin_sessions[user.id]
                await msg.reply_text(
                    "✅ <b>GC Profile Photo Configured!</b>\n\n"
                    "This photo will now be automatically set on every newly created deal group.",
                    parse_mode=HTML,
                )
                return
            else:
                await msg.reply_text("⚠️ Please send an image photo (or /cancel to abort).")
                return

        # Handle GC starting number input (text message)
        if action == "set_gc_start_num":
            if not msg.text:
                await msg.reply_text("Please enter a positive integer number (e.g. 121), or /cancel to abort.")
                return
            val = msg.text.strip()
            if not val.isdigit() or int(val) <= 0:
                await msg.reply_text("❌ Invalid number. Please enter a positive integer (e.g. <code>121</code>):", parse_mode=HTML)
                return
            start_num = int(val)
            preset_idx = admin_sess["preset_idx"]
            curr_counter = await db.get_current_deal_no()
            baseline = curr_counter + 1
            await settings.set_setting("gc_start_num", start_num)
            await settings.set_setting("gc_baseline_deal_no", baseline)
            await settings.set_setting("gc_name_template", settings.GC_NAME_PRESETS[preset_idx])
            del _admin_sessions[user.id]
            await msg.reply_text(
                f"✅ <b>Sequential GC Naming Configured!</b>\n\n"
                f"• Preset: <code>{esc(settings.GC_NAME_PRESETS[preset_idx])}</code>\n"
                f"• Starting Deal Number: <b>#{start_num}</b> (Baseline counter: {baseline})\n\n"
                f"The next deal group will be named: <code>Deal #{start_num} | @{config.MM_USERNAME}</code>.",
                parse_mode=HTML,
            )
            return

        if msg.text:
            val = msg.text.strip()

            if action == "set_template":
                tmpl_key = admin_sess["tmpl_key"]
                # Validate template safely
                try:
                    safe_format(val, deal_id="1", buyer="@b", seller="@s", currency="$", amount="100", tat="24h", deadline="now", mm=config.MM_USERNAME)
                except Exception as e:
                    await msg.reply_text(f"❌ Invalid template format: {e}. Please try again or send /cancel.")
                    return

                await settings.set_template(tmpl_key, val)
                del _admin_sessions[user.id]
                label = settings.TEMPLATE_LABELS.get(tmpl_key, tmpl_key)
                await msg.reply_text(f"✅ Template <b>{label}</b> updated successfully!", parse_mode=HTML)
                return

            elif action == "set_ad":
                ad_content = msg.text_html.strip() if hasattr(msg, "text_html") and msg.text_html else val
                if len(val) > 250:
                    await msg.reply_text("❌ Ad text is too long (maximum 250 characters). Please send a shorter text, or /cancel:")
                    return
                await settings.set_ad(ad_content, enabled=True)
                del _admin_sessions[user.id]
                await msg.reply_text(
                    f"✅ <b>Advertisement Configured & Activated!</b>\n\n"
                    f"Footer will appear on outgoing messages as:\n— \"{ad_content}\"",
                    parse_mode=HTML,
                )
                return

            elif action == "set_crypto":
                coin_key = admin_sess["coin_key"]
                await settings.set_crypto_wallet(coin_key, val)
                del _admin_sessions[user.id]
                info = settings.CRYPTO_NETWORKS.get(coin_key, {})
                await msg.reply_text(f"✅ Wallet address updated for <b>{info.get('name')}</b>!", parse_mode=HTML)
                return

            elif action == "set_field":
                field = admin_sess["field"]
                await settings.set_setting(field, val)
                del _admin_sessions[user.id]
                await msg.reply_text(f"✅ Setting <b>{field}</b> updated!", parse_mode=HTML)
                return

            elif action == "livechat_reply":
                target_uid = admin_sess["target_uid"]
                del _admin_sessions[user.id]
                ok = await _relay_reply_to_user(ctx.bot, target_uid, val)
                if ok:
                    await msg.reply_text(f"✅ Reply delivered to user <code>{target_uid}</code>.", parse_mode=HTML)
                else:
                    await msg.reply_text(f"❌ Failed to deliver reply to user <code>{target_uid}</code>.", parse_mode=HTML)
                return

    # 2. Middleman replying directly to a livechat message
    if _is_mm(user.id, user.username) and msg.reply_to_message:
        relay = await db.get_livechat_relay(msg.reply_to_message.message_id)
        if relay and msg.text:
            target_uid = relay["user_id"]
            ok = await _relay_reply_to_user(ctx.bot, target_uid, msg.text)
            if ok:
                await msg.reply_text(f"✅ Reply delivered to user <code>{target_uid}</code>.", parse_mode=HTML)
            else:
                await msg.reply_text(f"❌ Failed to deliver reply to user <code>{target_uid}</code>.", parse_mode=HTML)
            return

    # 3. Active livechat relay from client to Middleman
    lc = await db.get_active_livechat(user.id)
    if lc:
        mm_id = config.MM_USER_ID or userbot.mm_user_id
        if mm_id:
            text_content = msg.text or msg.caption or "[Media / Attachment]"
            alert = texts.livechat_user_msg_alert(user.first_name or "", user.username or "", user.id, text_content)
            reply_kb = _kb(_btn("↩️ Reply to User", f"lc:reply_to:{user.id}", BLUE))
            try:
                if msg.photo:
                    sent = await ctx.bot.send_photo(
                        mm_id,
                        photo=msg.photo[-1].file_id,
                        caption=alert,
                        parse_mode=HTML,
                        reply_markup=reply_kb,
                    )
                else:
                    sent = await ctx.bot.send_message(mm_id, alert, parse_mode=HTML, reply_markup=reply_kb)

                await db.map_livechat_relay(sent.message_id, user.id, msg.message_id)
                await msg.reply_text(f"✅ Message sent to @{config.MM_USERNAME}. Please wait for a reply.", parse_mode=HTML)
                return
            except TelegramError as e:
                log.warning("Could not relay livechat message to MM: %s", e)

    # 4. Standard /deal session setup
    s = await db.get_session(user.id)
    if s:
        if msg.text:
            await _session_text(update, ctx, s)
        else:
            await msg.reply_text("Please send a text message.")
        return


async def on_error(update, ctx):
    log.error("Unhandled error", exc_info=ctx.error)
