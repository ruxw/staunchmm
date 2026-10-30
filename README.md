# Middleman Bot (MongoDB)

Telegram middleman bot: `/start`, `/deal`, `/deals`, `/mm`, `/livechat`, `/settings`, `/stats`, `/referral`, `/redeem`, `/leaderboard`, `/id` + TAT system.
Stack: python-telegram-bot 22 · Telethon (middleman userbot session) · MongoDB (motor) · AI / NLP parsing. Python 3.11+.

## New Features
- **Direct Live Chat (`/livechat`)**: Allows restricted/limited Telegram accounts to chat with the middleman directly through the bot. Middleman can reply directly by swiping/replying to the bot's relayed message or via `/reply`.
- **Admin Dashboard (`/settings`)**: Interactive middleman dashboard to configure Official Channel, Vouch Channel, TOS Channel, UPI ID, 25+ Crypto Wallets, GC Name templates, and Vouch format.
- **Active `/stats`**: Real-time monitoring of deals, registered users, daily growth, active TATs, and system health.
- **Instant `/mm` Deal Rooms**:
  - Typing `/mm` in any DM automatically deletes the command, creates a deal supergroup, tags Middleman as "MM", tags the bot as "MM Bot", moves group to Deals folder, and invites the counterparty.
  - Interactive role selection (`[ 🛒 Buyer ]` | `[ 💼 Seller ]`).
  - Middleman can reassign roles by replying to any message in the group with `/buyer` or `/seller`.
  - AI / NLP parser detects deal details and outputs a structured deal card.
  - Buyer one-tap confirmation (`[ ✅ Confirm Deal ]`).
  - Dual Payment Flow: Deal Amount + Fee with UPI or buttonised menu of 25+ cryptocurrency networks.
  - Payment submission verification + Middleman `/paid` and `/complete` commands with automated vouch generation.

## Setup
1. `pip install -r requirements.txt`
2. `python gen_session.py` (log in with the **middleman's** account, copy `SESSION_STRING`)
3. Copy `.env.example` to `.env` and fill it in
4. **The middleman account must press /start on the bot once** (so the bot can DM him)
5. `python main.py`

## Collections
`users`, `sessions` (TTL), `deals`, `referrals`, `counters`, `processed_callbacks` (TTL), `meta`.

## TAT design (restart-safe)
- Deadline lives in `deals.tat_deadline` (UTC). One poll loop (`tat.py`) claims due deals with an atomic
  `find_one_and_update` -> one notification per deadline, no in-memory timers to lose or duplicate.
- Extension = a single atomic pipeline update (adds to the deadline, appends to `extensions`, resets the
  notified flag), so the old expiry is automatically invalid. Callback ids are stored to block double-apply.
- Failed notifications retry with backoff (max 10). Expiry never changes the deal status.

## Files
`main.py` wiring · `handlers.py` commands/flows · `service.py` group creation + TAT actions ·
`tat.py` watcher · `userbot.py` Telethon (group, tags, folder) · `database.py` · `texts.py` · `utils.py`
