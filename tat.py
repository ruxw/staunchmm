"""Persistent TAT watcher. One poll loop over MongoDB -> survives restarts, no per-deal timers to leak."""
import asyncio
import logging
from datetime import timedelta

from pymongo import ReturnDocument

import config
import database as db
import service
from utils import utcnow

log = logging.getLogger(__name__)


async def _process_due(app):
    now = utcnow()
    # crash recovery: claimed but never finished
    await db.deals.update_many(
        {"status": "active", "expiry_notified": True, "expiry_notified_at": {"$exists": False},
         "expiry_claimed_at": {"$lt": now - timedelta(minutes=2)}},
        {"$set": {"expiry_notified": False}},
    )
    while True:
        now = utcnow()
        # atomic claim => exactly one notification per deadline, deals handled independently
        deal = await db.deals.find_one_and_update(
            {
                "status": "active",
                "expiry_notified": False,
                "tat_deadline": {"$lte": now},
                "$or": [{"next_notify_at": {"$exists": False}}, {"next_notify_at": None},
                        {"next_notify_at": {"$lte": now}}],
            },
            {"$set": {"expiry_notified": True, "expiry_claimed_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if not deal:
            return
        try:
            ok = await service.notify_expiry(app, deal)
        except Exception:
            log.exception("notify_expiry crashed for %s", deal["_id"])
            ok = False
        if ok:
            await db.deals.update_one({"_id": deal["_id"], "tat_deadline": deal["tat_deadline"]},
                                      {"$set": {"expiry_notified_at": utcnow()}})
            continue
        retries = deal.get("notify_retries", 0) + 1
        if retries < service.MAX_NOTIFY_RETRIES:
            await db.deals.update_one(
                {"_id": deal["_id"], "tat_deadline": deal["tat_deadline"]},  # don't clobber an extension
                {"$set": {"expiry_notified": False, "notify_retries": retries,
                          "next_notify_at": utcnow() + timedelta(seconds=60 * retries)}},
            )
        else:
            log.error("Giving up expiry notification for deal %s", deal["_id"])
            await db.deals.update_one(
                {"_id": deal["_id"], "tat_deadline": deal["tat_deadline"]},
                {"$set": {"expiry_notified_at": utcnow(), "expiry_notify_failed": True}},
            )


async def run(app):
    log.info("TAT watcher started (poll=%ss)", config.TAT_POLL_SECONDS)
    while True:
        try:
            await _process_due(app)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("TAT loop error")
        await asyncio.sleep(config.TAT_POLL_SECONDS)
