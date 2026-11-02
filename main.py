import asyncio
import logging
import os
import threading

from html import escape as _esc
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, ChatMemberHandler, CommandHandler, ExtBot, MessageHandler, filters
)

import config
import database as db
import emojis
import handlers as h
import service
import settings
import tat
import userbot

import json
import traceback

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("middlemanbot")

# Real-time health state for Render web endpoint
APP_STATE = {
    "web_server": "running",
    "mongodb": "pending",
    "userbot": "pending",
    "telegram_bot": "pending",
    "errors": []
}

# ---- Render keep-alive web server (so Render detects an open port & allows live diagnostics) ----
class _Ping(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        body = json.dumps({
            "status": "online" if APP_STATE["telegram_bot"].startswith("polling") else "initializing",
            "components": APP_STATE,
            "tip": "On Render free tier, ping this URL every 5-10 minutes (via UptimeRobot/Cron-job.org) to prevent Render from going to sleep."
        }, indent=2)
        self.wfile.write(body.encode("utf-8"))

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def _run_web():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), _Ping).serve_forever()


def start_keepalive():
    threading.Thread(target=_run_web, daemon=True).start()

COMMANDS = [
    BotCommand("start", "Start the bot & open main menu"),
    BotCommand("deal", "Set up a new deal"),
    BotCommand("mm", "Instantly create a deal group"),
    BotCommand("chat", "Direct chat with middleman"),
    BotCommand("settings", "Middleman admin dashboard"),
    BotCommand("stats", "Live middleman statistics"),
    BotCommand("ad", "MM: Manage advertisement footer"),
    BotCommand("deals", "View deal history"),
    BotCommand("referral", "Check referral points"),
    BotCommand("redeem", "Exchange points for gifts"),
    BotCommand("leaderboard", "View top 10 deal makers"),
    BotCommand("id", "Retrieve user IDs and chat IDs"),
    BotCommand("settat", "MM: Set turnaround time for deal"),
    BotCommand("begin", "MM: Confirm payment & start countdown"),
    BotCommand("extendtat", "MM: Extend active TAT deadline"),
    BotCommand("hold", "MM: Set status & group title to hold"),
    BotCommand("release", "MM: Set status & group title to released"),
    BotCommand("close", "MM: Close deal & mute participants"),
]


class EmojiBot(ExtBot):
    """Every outgoing text/caption gets its plain emoji swapped for the custom ones (see emojis.py),
    so no message is missed. Plain-text messages are HTML-escaped first, so they stay safe.
    Also handles centralized advertisement footer injection."""

    @staticmethod
    def _fix(kw: dict, key: str):
        api_kw = kw.get("api_kwargs") or {}
        no_ad = kw.pop("_no_ad", False) or api_kw.pop("_no_ad", False)
        t = kw.get(key)
        if not isinstance(t, str) or kw.get("entities") or kw.get("caption_entities"):
            return
        pm = kw.get("parse_mode")
        pm = getattr(pm, "value", pm)          # unwrap PTB's DEFAULT_NONE
        if pm is None:                          # plain text -> escape, then send as HTML
            t = _esc(t, quote=False)
        elif pm != ParseMode.HTML:
            return

        # Centralized advertisement footer injection
        skip_ad = no_ad or any(k in t for k in (
            "Admin Dashboard",
            "Advertisement Footer",
            "Advertisement Preview",
            "Set Advertisement",
            "Settings dashboard",
            "Configurable Message Templates",
            "GC Profile Photo",
            "Sequential GC Naming",
        ))

        if not skip_ad:
            try:
                ad = settings.get_ad()
                if ad.get("enabled") and ad.get("text"):
                    ad_text = ad["text"].strip()
                    if ad_text and ('— "' not in t and '— &quot;' not in t and ad_text not in t):
                        t = f"{t}\n\n— \"{ad_text}\""
            except Exception:
                pass

        kw["parse_mode"] = ParseMode.HTML
        kw[key] = emojis.emojify(t)

    async def send_message(self, *a, **kw):
        if len(a) >= 2:
            kw.setdefault("chat_id", a[0]); kw.setdefault("text", a[1]); a = a[2:]
        self._fix(kw, "text")
        return await super().send_message(*a, **kw)

    async def edit_message_text(self, *a, **kw):
        if len(a) >= 1:
            kw.setdefault("text", a[0]); a = a[1:]
        self._fix(kw, "text")
        return await super().edit_message_text(*a, **kw)

    async def send_photo(self, *a, **kw):
        if len(a) >= 2:
            kw.setdefault("chat_id", a[0]); kw.setdefault("photo", a[1]); a = a[2:]
        self._fix(kw, "caption")
        return await super().send_photo(*a, **kw)

    async def edit_message_caption(self, *a, **kw):
        if len(a) >= 1:
            kw.setdefault("caption", a[0]); a = a[1:]
        self._fix(kw, "caption")
        return await super().edit_message_caption(*a, **kw)


async def post_init(app: Application):
    log.info("Starting post_init bootstrap...")
    try:
        log.info("1/5 Connecting to MongoDB...")
        await db.init()
        await settings.init_settings()
        APP_STATE["mongodb"] = "connected"
        log.info("MongoDB connected successfully.")
    except Exception as e:
        APP_STATE["mongodb"] = f"error: {e}"
        APP_STATE["errors"].append(f"MongoDB init failed: {e}")
        log.error("MongoDB init failed (check Atlas IP whitelist / MONGO_URI): %s", e)
        raise

    try:
        log.info("2/5 Starting Telethon userbot...")
        await asyncio.wait_for(userbot.start(), timeout=35)
        me = getattr(userbot, "client", None)
        username = getattr(me, "username", None) if me else "unknown"
        APP_STATE["userbot"] = f"connected as @{username}"
        log.info("Telethon userbot started.")
    except asyncio.TimeoutError:
        err = "Telethon userbot.start() timed out after 35s. Check network / MTProto connection."
        APP_STATE["userbot"] = f"error: {err}"
        APP_STATE["errors"].append(err)
        log.error(err)
        raise
    except Exception as e:
        APP_STATE["userbot"] = f"error: {e}"
        APP_STATE["errors"].append(f"Userbot error: {e}")
        log.error("Telethon userbot failed to start: %s", e)
        raise

    # Link userbot instant deal callback and DM listeners
    userbot.set_instant_deal_callback(lambda deal: service.init_instant_deal_room(app, deal))
    userbot.setup_listeners(app.bot.username)

    log.info("3/5 Registering bot commands...")
    await app.bot.set_my_commands(COMMANDS)

    log.info("4/5 Recovering interrupted deals...")
    await service.recover_interrupted(app)

    log.info("5/5 Starting background TAT monitor...")
    app.bot_data["tat_task"] = asyncio.create_task(tat.run(app))

    APP_STATE["telegram_bot"] = f"polling updates as @{app.bot.username}"
    log.info("Bootstrap complete! MiddleShield Bot is now fully listening for updates.")


async def post_shutdown(app: Application):
    t = app.bot_data.get("tat_task")
    if t:
        t.cancel()
    await userbot.stop()
    await db.close()


def main():
    start_keepalive()
    app = (Application.builder().bot(EmojiBot(config.BOT_TOKEN))
           .post_init(post_init).post_shutdown(post_shutdown).build())
    private = filters.ChatType.PRIVATE
    groups = filters.ChatType.GROUPS

    # Private chat commands
    for name, fn in (
        ("start", h.start_cmd), ("deal", h.deal_cmd), ("deals", h.deals_cmd),
        ("referral", h.referral_cmd), ("redeem", h.redeem_cmd),
        ("leaderboard", h.leaderboard_cmd), ("id", h.id_cmd),
        ("mm", h.mm_dm_cmd), ("livechat", h.livechat_cmd), ("endchat", h.endchat_cmd),
        ("settings", h.settings_cmd), ("stats", h.stats_cmd), ("ad", h.ad_cmd), ("reply", h.reply_cmd),
    ):
        app.add_handler(CommandHandler(name, fn, filters=private))

    # Deal Group commands (middleman & participants)
    app.add_handler(CommandHandler("settat", h.settat_cmd, filters=groups))
    app.add_handler(CommandHandler("begin", h.begin_cmd, filters=groups))
    app.add_handler(CommandHandler("extendtat", h.extendtat_cmd, filters=groups))
    app.add_handler(CommandHandler("hold", h.hold_cmd, filters=groups))
    app.add_handler(CommandHandler("release", h.release_cmd, filters=groups))
    app.add_handler(CommandHandler("close", h.close_cmd, filters=groups))
    app.add_handler(CommandHandler("buyer", h.group_buyer_cmd, filters=groups))
    app.add_handler(CommandHandler("seller", h.group_seller_cmd, filters=groups))
    app.add_handler(CommandHandler("paid", h.paid_cmd, filters=groups))
    app.add_handler(CommandHandler("complete", h.complete_cmd, filters=groups))
    app.add_handler(CommandHandler("done", h.complete_cmd, filters=groups))

    # Callback Query Handlers
    app.add_handler(CallbackQueryHandler(h.menu_cb, pattern=r"^menu:"))
    app.add_handler(CallbackQueryHandler(h.referral_cb, pattern=r"^ref$"))
    app.add_handler(CallbackQueryHandler(h.livechat_callback, pattern=r"^lc:"))
    app.add_handler(CallbackQueryHandler(h.settings_callback, pattern=r"^set:"))
    app.add_handler(CallbackQueryHandler(h.ad_callback, pattern=r"^ad:"))
    app.add_handler(CallbackQueryHandler(h.stats_callback, pattern=r"^stats:"))
    app.add_handler(CallbackQueryHandler(h.deal_callback, pattern=r"^d:"))
    app.add_handler(CallbackQueryHandler(h.accept_cb, pattern=r"^acc:"))
    app.add_handler(CallbackQueryHandler(h.reject_cb, pattern=r"^rej:"))
    app.add_handler(CallbackQueryHandler(h.extend_cb, pattern=r"^ext:"))
    app.add_handler(CallbackQueryHandler(h.instant_role_callback, pattern=r"^inst:role:"))
    app.add_handler(CallbackQueryHandler(h.buyer_confirm_deal_cb, pattern=r"^inst:confirm:"))
    app.add_handler(CallbackQueryHandler(h.mm_proceed_payment_cb, pattern=r"^inst:mm_proceed:"))
    app.add_handler(CallbackQueryHandler(h.noop_cb, pattern=r"^noop$"))
    app.add_handler(CallbackQueryHandler(h.instant_crypto_callback, pattern=r"^inst:crypto_"))
    app.add_handler(CallbackQueryHandler(h.payment_sent_cb, pattern=r"^inst:paid_sent:"))
    app.add_handler(CallbackQueryHandler(h.payment_sent_cb, pattern=r"^inst:buyer_paid:"))
    app.add_handler(CallbackQueryHandler(h.mm_confirm_payment_cb, pattern=r"^inst:mm_paid:"))
    app.add_handler(CallbackQueryHandler(h.deal_close_callback, pattern=r"^deal:close_"))
    app.add_handler(CallbackQueryHandler(h.vouch_callback, pattern=r"^vouch:"))

    # Chat Member Updates (admission restriction & greeting)
    app.add_handler(ChatMemberHandler(h.on_chat_member_update, ChatMemberHandler.CHAT_MEMBER))

    # Message Handlers
    app.add_handler(MessageHandler(groups & filters.UpdateType.MESSAGE & ~filters.COMMAND, h.on_group_message))
    app.add_handler(MessageHandler(private & filters.UpdateType.MESSAGE & ~filters.COMMAND, h.on_private_message))

    app.add_error_handler(h.on_error)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()