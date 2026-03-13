#!/usr/bin/env python3
"""
Requirements:
  pip install -r tools/requirements.txt

Usage:
  python3 tools/create_sessions_browser.py <accounts_file> [--append sessions.jsonl] [--headless] [--delay]

Examples:
  # Output to terminal
  python3 tools/create_sessions_browser.py <accounts_file>

  # Append to sessions.jsonl
  python3 tools/create_sessions_browser.py <accounts_file> --append sessions.jsonl

  # Add 5 second delay between sessions (default: 1)
  python3 tools/create_sessions_browser.py <accounts_file> --delay 5

  # Headless mode (may increase detection risk)
  python3 tools/create_sessions_browser.py <accounts_file> --headless

Input (accounts_file):
  [{"username": "user", "password": "pass", "totp": "totp_code"}, {...}, ...]

Output:
  {"kind": "cookie", "username": "...", "id": "...", "auth_token": "...", "ct0": "..."}
  {"kind": "cookie", "username": "...", "id": "...", "auth_token": "...", "ct0": "..."}
  ...
"""

import asyncio
import json
import sys
from time import sleep

import nodriver as uc
import pyotp


async def login_and_get_cookies(account, headless=False):
    """Authenticate with X.com and extract session cookies"""
    # Note: headless mode may increase detection risk from bot-detection systems
    browser = await uc.start(headless=headless)
    tab = await browser.get("https://x.com/i/flow/login")

    username = account["username"]
    password = account["password"]
    totp_seed = account["totp"]

    try:
        # Enter username
        print(f"[*] Entering username {username}...", file=sys.stderr)

        retry = 0
        username_input = None
        while retry < 5:
            try:
                # Try multiple common selectors
                selectors = [
                    'input[autocomplete="username"]',
                    'input[name="text"]',
                    'input[type="text"]'
                ]
                for sel in selectors:
                    try:
                        username_input = await tab.find(sel, timeout=5)
                        if username_input:
                            print(f"[+] Found username input with selector: {sel}", file=sys.stderr)
                            break
                    except:
                        continue
                
                if not username_input:
                     raise Exception("No username input found with any selector")
            except Exception as e:
                print(f"[!] Warning: Could not find username input: {e}", file=sys.stderr)
                await asyncio.sleep(5)
                retry += 1
                continue

            pos = await username_input.get_position()
            await tab.mouse_move(pos.x, pos.y, steps=50, flash=True)
            await asyncio.sleep(0.5)

            await username_input.click()
            await asyncio.sleep(0.5)
            await username_input.send_keys(username)
            await asyncio.sleep(0.5)
            await username_input.send_keys("\n")
            await asyncio.sleep(5)

            page_content = await tab.get_content()
            if "Could not log you in" in page_content:
                retry += 1
                wait = retry * 5
                print(f"Retrying username in {wait} seconds...", file=sys.stderr)
                await asyncio.sleep(wait)
            else:
                break
        
        # Security check detection
        page_content = await tab.get_content()
        if any(x in page_content.lower() for x in ["unusual activity", "verify your identity", "enter your phone", "enter your username"]):
            print(f"[!] Security challenge detected for {username}! Twitter/X requires additional verification (Username/Phone/Email).", file=sys.stderr)
            
            # Try to find the identifier input
            id_input = None
            selectors = [
                'input[autocomplete="username"]',
                'input[name="text"]',
                'input[data-testid="ocfEnterTextTextInput"]'
            ]
            for sel in selectors:
                try:
                    id_input = await tab.find(sel, timeout=5)
                    if id_input:
                        print(f"[+] Found verification input field", file=sys.stderr)
                        break
                except:
                    continue
            
            if id_input:
                alternate_id = account.get("alternate_id") or account.get("id")
                if not alternate_id:
                     print(f"[!] Error: Security challenge detected but no alternate_id provided for {username} in JSON.", file=sys.stderr)
                     raise Exception("Stuck on security challenge screen (needs alternate_id)")
                
                print(f"[*] Entering alternate identifier: {alternate_id}...", file=sys.stderr)
                await id_input.send_keys(alternate_id + "\n")
                await asyncio.sleep(5)
            else:
                 print("[!] Warning: Security challenge screen detected but no input field found.", file=sys.stderr)

        # Enter password
        print("[*] Entering password...", file=sys.stderr)
        pretry = 0
        password_input = None
        while pretry < 5:
            try:
                selectors = [
                    'input[autocomplete="current-password"]',
                    'input[name="password"]',
                    'input[type="password"]'
                ]
                for sel in selectors:
                    try:
                        password_input = await tab.find(sel, timeout=5)
                        if password_input:
                            print(f"[+] Found password input with selector: {sel}", file=sys.stderr)
                            break
                    except:
                        continue

                if not password_input:
                    page_content = await tab.get_content()
                    if "unusual" in page_content.lower():
                         raise Exception("Stuck on security challenge screen")
                    raise Exception("Password input not found")
            except Exception as e:
                print(f"[!] Warning: Could not find password input: {e}", file=sys.stderr)
                await asyncio.sleep(5)
                pretry += 1
                continue

            await password_input.click()
            await asyncio.sleep(0.5)
            await password_input.send_keys(password)
            await asyncio.sleep(0.5)
            await password_input.send_keys("\n")
            await asyncio.sleep(5)

            page_content = await tab.get_content()
            if "Could not log you in" in page_content:
                pretry += 1
                wait = pretry * 5
                print(f"Retrying password in {wait} seconds...", file=sys.stderr)
                await asyncio.sleep(wait)
            else:
                break

        # Handle 2FA if needed
        page_content = await tab.get_content()
        if "verification code" in page_content.lower() or "enter code" in page_content.lower():
            if not totp_seed:
                raise Exception("2FA required but no TOTP seed provided")

            print("[*] 2FA detected, entering code...", file=sys.stderr)
            totp_code = pyotp.TOTP(totp_seed).now()
            # Try to find the 2FA input
            code_input = None
            try:
                code_input = await tab.select('input[type="text"]')
            except:
                try:
                    code_input = await tab.find('input[autocomplete="one-time-code"]', timeout=5)
                except:
                    pass
            
            if code_input:
                await code_input.send_keys(totp_code + "\n")
                await asyncio.sleep(5)
            else:
                print("[!] Error: 2FA detected but no code input found", file=sys.stderr)

        # Get cookies
        print("[*] Retrieving cookies...", file=sys.stderr)
        for _ in range(20):  # 20 second timeout
            cookies = await browser.cookies.get_all()
            cookies_dict = {cookie.name: cookie.value for cookie in cookies}

            if "auth_token" in cookies_dict and "ct0" in cookies_dict:
                # Extract ID from twid cookie (may be URL-encoded)
                user_id = None
                if "twid" in cookies_dict:
                    twid = cookies_dict["twid"]
                    # Try to extract the ID from twid (format: u%3D<id> or u=<id>)
                    if "u%3D" in twid:
                        user_id = twid.split("u%3D")[1].split("&")[0].strip('"')
                    elif "u=" in twid:
                        user_id = twid.split("u=")[1].split("&")[0].strip('"')

                cookies_dict["username"] = username
                if user_id:
                    cookies_dict["id"] = user_id

                return cookies_dict

            await asyncio.sleep(1)

        raise Exception("Timeout waiting for cookies")

    finally:
        browser.stop()


async def main():
    if len(sys.argv) < 2:
        print(
            "Usage: python3 create_sessions_browser.py <accounts_file> [--append sessions.jsonl] [--headless]"
        )
        sys.exit(1)

    input = sys.argv[1]
    append_file = None
    headless = False
    delay = 1

    # Parse optional arguments
    i = 2
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--append":
            if i + 1 < len(sys.argv):
                append_file = sys.argv[i + 1]
                i += 2  # Skip '--append' and filename
            else:
                print("[!] Error: --append requires a filename", file=sys.stderr)
                sys.exit(1)
        elif arg == "--headless":
            headless = True
            i += 1
        elif arg == "--delay":
            delay = int(sys.argv[i + 1])
            i += 2
        else:
            # Unkown args
            print(f"[!] Warning: Unknown argument: {arg}", file=sys.stderr)
            i += 1

    accounts = []
    with open(input) as f:
        accounts = json.load(f)

    if len(accounts) == 0:
        print("no accounts in file")
        sys.exit(0)

    sessions = 0
    for acc in accounts:
        sessions += 1
        try:
            cookies = await login_and_get_cookies(acc, headless)
            session = {
                "kind": "cookie",
                "username": cookies["username"],
                "id": cookies.get("id"),
                "auth_token": cookies["auth_token"],
                "ct0": cookies["ct0"],
            }

            if append_file:
                with open(append_file, "a") as f:
                    f.write(json.dumps(session) + "\n")
            else:
                print(json.dumps(session))

            print(f"Progress: {sessions} / {len(accounts)}")
            if sessions < len(accounts):
                print("Waiting", delay, "seconds")
                sleep(delay)
        except Exception as error:
            print(
                f"[!] Error getting session for {acc["username"]}, skipping: {error}",
                file=sys.stderr,
            )


if __name__ == "__main__":
    asyncio.run(main())
