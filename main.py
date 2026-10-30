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

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ---- Render keep-alive web server (so Render detects an open port) ----
class _Ping(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive")

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
    so no message is missed. Plain-text messages are HTML-escaped first, so they stay safe."""

    @staticmethod
    def _fix(kw: dict, key: str):
        t = kw.get(key)
        if not isinstance(t, str) or kw.get("entities") or kw.get("caption_entities"):
            return
        pm = kw.get("parse_mode")
        pm = getattr(pm, "value", pm)          # unwrap PTB's DEFAULT_NONE
        if pm is None:                          # plain text -> escape, then send as HTML
            t = _esc(t, quote=False)
        elif pm != ParseMode.HTML:
            return
        kw["parse_mode"] = ParseMode.HTML
        kw[key] = emojis.emojify(t)

    async def send_message(self, *a, **kw):
        if len(a) >= 2:
            kw.setdefault("chat_id", a[0]); kw.setdefault("text", a[1]); a = a[2:]
        self._fix(kw, "text")
        return await super().send_message(*a, **kw)

    async def edit_message_text(self, *a, **kw):
        self._fix(kw, "text")
        return await super().edit_message_text(*a, **kw)

    async def send_photo(self, *a, **kw):
        self._fix(kw, "caption")
        return await super().send_photo(*a, **kw)

    async def edit_message_caption(self, *a, **kw):
        self._fix(kw, "caption")
        return await super().edit_message_caption(*a, **kw)


async def post_init(app: Application):
    await db.init()
    await settings.init_settings()
    await userbot.start()

    # Link userbot instant deal callback and DM listeners
    userbot.set_instant_deal_callback(lambda deal: service.init_instant_deal_room(app, deal))
    userbot.setup_listeners(app.bot.username)

    await app.bot.set_my_commands(COMMANDS)
    await service.recover_interrupted(app)
    app.bot_data["tat_task"] = asyncio.create_task(tat.run(app))


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
        ("settings", h.settings_cmd), ("stats", h.stats_cmd), ("reply", h.reply_cmd),
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

    # Chat Member Updates (admission restriction & greeting)
    app.add_handler(ChatMemberHandler(h.on_chat_member_update, ChatMemberHandler.CHAT_MEMBER))

    # Message Handlers
    app.add_handler(MessageHandler(groups & filters.UpdateType.MESSAGE & ~filters.COMMAND, h.on_group_message))
    app.add_handler(MessageHandler(private & filters.UpdateType.MESSAGE & ~filters.COMMAND, h.on_private_message))

    app.add_error_handler(h.on_error)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()