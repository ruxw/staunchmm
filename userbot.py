"""Middleman's Telethon userbot: creates deal groups, promotes the bot, sets tags, manages the folder."""
import asyncio
import logging
from dataclasses import dataclass

from telethon import TelegramClient, functions, types, utils
from telethon.errors import RPCError
from telethon.sessions import StringSession

import config
import database as db
import texts

log = logging.getLogger(__name__)

client: TelegramClient = None
mm_user_id: int = None
_folder_lock = asyncio.Lock()

BOT_RIGHTS = types.ChatAdminRights(
    change_info=True, delete_messages=True, ban_users=True,
    invite_users=True, pin_messages=True, manage_call=True, other=True,
)
OWNER_RIGHTS = types.ChatAdminRights(
    change_info=True, delete_messages=True, ban_users=True,
    invite_users=True, pin_messages=True, manage_call=True, add_admins=True, other=True,
)


@dataclass
class GroupInfo:
    chat_id: int       # Bot-API style id (-100...)
    invite_link: str


async def start():
    global client, mm_user_id
    client = TelegramClient(StringSession(config.SESSION_STRING), config.API_ID, config.API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("SESSION_STRING is invalid/expired. Generate a new one with gen_session.py")
    me = await client.get_me()
    mm_user_id = me.id
    if (me.username or "").lower() != config.MM_USERNAME.lower():
        log.warning("Session account is @%s but MM_USERNAME is @%s", me.username, config.MM_USERNAME)
    log.info("Userbot connected as @%s (%s)", me.username, me.id)


async def stop():
    if client:
        await client.disconnect()


async def create_deal_group(title: str, bot_username: str, invite_users: list = None) -> GroupInfo:
    bot_ent = await client.get_input_entity(bot_username)
    res = await client(functions.channels.CreateChannelRequest(title=title, about="", megagroup=True))
    channel = res.chats[0]
    peer = await client.get_input_entity(channel)
    try:
        # bot in + admin with the "MM BOT" tag
        await client(functions.channels.InviteToChannelRequest(channel=peer, users=[bot_ent]))
        await client(functions.channels.EditAdminRequest(
            channel=peer, user_id=bot_ent, admin_rights=BOT_RIGHTS, rank="MM BOT"))
        # middleman's own tag -> "MM" (best effort, never blocks the deal)
        await _set_own_tag(peer)

        # best-effort invite for counterparty
        if invite_users:
            for u in invite_users:
                try:
                    uent = await client.get_input_entity(u)
                    await client(functions.channels.InviteToChannelRequest(channel=peer, users=[uent]))
                except Exception as e:
                    log.info("Direct invite to deal GC skipped (privacy/contact restriction): %s", e)

        # folder (best effort)
        try:
            await _add_to_folder(peer)
        except Exception:
            log.exception("Could not add group to folder")
        inv = await client(functions.messages.ExportChatInviteRequest(peer=peer))
        return GroupInfo(chat_id=utils.get_peer_id(channel), invite_link=inv.link)
    except Exception:
        try:  # don't leave half-built groups behind
            await client(functions.channels.DeleteChannelRequest(channel=peer))
        except Exception:
            log.exception("Cleanup of half-created group failed")
        raise


async def _set_own_tag(peer):
    me = await client.get_input_entity("me")
    try:
        await client(functions.channels.EditAdminRequest(
            channel=peer, user_id=me, admin_rights=OWNER_RIGHTS, rank="MM"))
        return
    except Exception as e:
        log.info("EditAdmin(self) for tag failed (%s), trying member-tag API", e)
    try:
        req = getattr(functions.messages, "EditChatParticipantRankRequest", None)
        if req is None:
            raise RuntimeError("Telethon version has no EditChatParticipantRankRequest")
        await client(req(peer=peer, participant=me, rank="MM"))
    except Exception:
        log.warning("Could not set the 'MM' tag on the middleman account (group still created)")


def _folder_title(name: str, wrapped: bool):
    return types.TextWithEntities(text=name, entities=[]) if wrapped else name


async def _add_to_folder(channel_peer):
    ipeer = types.InputPeerChannel(channel_id=channel_peer.channel_id, access_hash=channel_peer.access_hash)
    async with _folder_lock:
        saved = await db.meta.find_one({"_id": "folder"})
        res = await client(functions.messages.GetDialogFiltersRequest())
        flist = getattr(res, "filters", res)
        used, existing = set(), None
        for f in flist:
            fid = getattr(f, "id", None)
            if fid is not None:
                used.add(fid)
            if saved and fid == saved.get("folder_id") and isinstance(f, types.DialogFilter):
                existing = f

        if existing:
            if not any(getattr(p, "channel_id", None) == ipeer.channel_id for p in existing.include_peers):
                existing.include_peers = list(existing.include_peers) + [ipeer]
            await client(functions.messages.UpdateDialogFilterRequest(id=existing.id, filter=existing))
            return

        fid = saved["folder_id"] if saved and saved["folder_id"] not in used else max(used | {1}) + 1
        last_err = None
        for wrapped in (True, False):  # newer layers want TextWithEntities, older want str
            try:
                flt = types.DialogFilter(
                    id=fid, title=_folder_title(config.FOLDER_NAME, wrapped),
                    pinned_peers=[], include_peers=[ipeer], exclude_peers=[],
                )
                await client(functions.messages.UpdateDialogFilterRequest(id=fid, filter=flt))
                await db.meta.update_one({"_id": "folder"}, {"$set": {"folder_id": fid}}, upsert=True)
                return
            except RPCError:
                raise
            except Exception as e:
                last_err = e
        raise last_err


# ------------------------------------------------------------- /mm trigger in DMs
from telethon import events
import settings
from utils import utcnow

_instant_callback = None


def set_instant_deal_callback(cb):
    global _instant_callback
    _instant_callback = cb


def setup_listeners(bot_username: str):
    @client.on(events.NewMessage(func=lambda e: e.is_private and e.raw_text and e.raw_text.strip().lower().startswith("/mm")))
    async def on_mm_cmd(event):
        try:
            await event.delete()
        except Exception:
            pass

        other_id = event.chat_id if event.out else event.sender_id
        asyncio.create_task(_handle_instant_mm(event, other_id, bot_username))


async def _handle_instant_mm(event, other_id: int, bot_username: str):
    try:
        other_ent = await client.get_entity(other_id)
        other_username = getattr(other_ent, "username", None) or getattr(other_ent, "first_name", "User")

        deal_no = await db.next_deal_no()
        label = f"#{config.DEAL_ID_PREFIX}{deal_no}"
        gc_title = settings.render_gc_title(label, "Buyer", "Seller")

        info = await create_deal_group(gc_title, bot_username, invite_users=[other_ent])

        # Notify other user in DM with invite link
        try:
            await client.send_message(
                other_id,
                texts.gc_created_text(info.invite_link),
                parse_mode="html",
            )
        except Exception as e:
            log.warning("Could not send DM to client about new group: %s", e)

        deal = {
            "deal_no": deal_no,
            "status": "instant_role_selection",
            "created_via": "instant_mm",
            "group_chat_id": info.chat_id,
            "invite_link": info.invite_link,
            "dm_user_id": other_id,
            "dm_username": other_username,
            "buyer_id": None,
            "buyer_username": None,
            "seller_id": None,
            "seller_username": None,
            "created_at": utcnow(),
        }
        res = await db.deals.insert_one(deal)
        deal["_id"] = res.inserted_id

        if _instant_callback:
            await _instant_callback(deal)
    except Exception:
        log.exception("Error handling /mm instant room creation")

