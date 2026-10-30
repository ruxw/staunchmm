import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
# +573003279549 number

# ─────────────────────────────────────────────
# 🎨 Colors
# ─────────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
WHITE = "\033[97m"
MAGENTA = "\033[95m"


def banner():
    print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════╗
║                                              ║
║       {WHITE}TELETHON STRING SESSION GENERATOR{CYAN}      ║
║                                              ║
╚══════════════════════════════════════════════╝{RESET}
""")


async def main():
    banner()

    print(f"{BLUE}{BOLD}➜ Telegram API Configuration{RESET}\n")

    api_id_input = input(
        f"{YELLOW}  API ID {WHITE}➜ {RESET}"
    ).strip()

    if not api_id_input.isdigit():
        print(f"\n{RED}✘ API ID must be a number.{RESET}")
        return

    api_id = int(api_id_input)

    api_hash = input(
        f"{YELLOW}  API Hash {WHITE}➜ {RESET}"
    ).strip()

    if not api_hash:
        print(f"\n{RED}✘ API Hash cannot be empty.{RESET}")
        return

    print(f"\n{CYAN}⟳ Starting Telethon client...{RESET}")

    client = TelegramClient(
        StringSession(),
        api_id,
        api_hash
    )

    try:
        await client.start()

        session_str = client.session.save()

        print(f"""
{GREEN}{BOLD}╔══════════════════════════════════════════════╗
║                                              ║
║              ✔ LOGIN SUCCESSFUL             ║
║                                              ║
╚══════════════════════════════════════════════╝{RESET}
""")

        print(f"{MAGENTA}{BOLD}Your Telethon Session String:{RESET}\n")
        print(f"{WHITE}{session_str}{RESET}")

        print(f"""
{CYAN}──────────────────────────────────────────────{RESET}

{GREEN}✔ Session generated successfully!{RESET}

{YELLOW}Add it to your .env file as:{RESET}

{WHITE}TG_SESSION={session_str}{RESET}

{RED}⚠ Keep this session string private.
Anyone with it may be able to access your Telegram account.{RESET}

{CYAN}──────────────────────────────────────────────{RESET}
""")

    except Exception as e:
        print(f"\n{RED}{BOLD}✘ Error:{RESET} {WHITE}{e}{RESET}")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}⚠ Aborted by user.{RESET}")