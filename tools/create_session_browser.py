#!/usr/bin/env python3
"""
Requirements:
  pip install nodriver pyotp

Usage:
  python3 tools/create_session_browser.py <username> <password> [totp_seed] [--append sessions.jsonl] [--headless]
"""

import asyncio
import json
import os
import sys

import nodriver as uc
import pyotp


async def login_and_get_cookies(username, password, totp_seed=None, alternate_id=None, headless=False):
    """Authenticate with X.com and extract session cookies"""
    browser = await uc.start(
        headless=headless,
        browser_args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
    )
    tab = await browser.get("https://x.com/i/flow/login")

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
                content = await tab.get_content()
                with open("debug_login.html", "w") as f:
                    f.write(content)
                print(f"[*] Page content preview (first 200 chars): {content[:200]}", file=sys.stderr)
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
            print("[!] Security challenge detected! Twitter/X requires additional verification (Username/Phone/Email).", file=sys.stderr)
            
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
                if not alternate_id:
                     print("[!] Error: Security challenge detected but no ID provided. Use --id <username/phone/email>.", file=sys.stderr)
                     raise Exception("Stuck on security challenge screen (needs ID)")
                
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
        for _ in range(30):
            cookies = await browser.cookies.get_all()
            cookies_dict = {cookie.name: cookie.value for cookie in cookies}

            if "auth_token" in cookies_dict and "ct0" in cookies_dict:
                user_id = None
                if "twid" in cookies_dict:
                    twid = cookies_dict["twid"]
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
    if len(sys.argv) < 3:
        print(
            "Usage: python3 create_session_browser.py username password [totp_seed] [--append file.jsonl] [--headless]"
        )
        sys.exit(1)

    username = sys.argv[1]
    password = sys.argv[2]
    totp_seed = None
    alternate_id = None
    append_file = None
    headless = False

    # Parse optional arguments
    i = 3
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--append":
            if i + 1 < len(sys.argv):
                append_file = sys.argv[i + 1]
                i += 2
            else:
                print("[!] Error: --append requires a filename", file=sys.stderr)
                sys.exit(1)
        elif arg == "--id":
            if i + 1 < len(sys.argv):
                alternate_id = sys.argv[i + 1]
                i += 2
            else:
                print("[!] Error: --id requires a value", file=sys.stderr)
                sys.exit(1)
        elif arg == "--headless":
            headless = True
            i += 1
        elif not arg.startswith("--"):
            if totp_seed is None:
                totp_seed = arg
            i += 1
        else:
            i += 1

    try:
        cookies = await login_and_get_cookies(username, password, totp_seed, alternate_id, headless)
        session = {
            "kind": "cookie",
            "username": cookies["username"],
            "id": cookies.get("id"),
            "auth_token": cookies["auth_token"],
            "ct0": cookies["ct0"],
        }
        output = json.dumps(session)

        if append_file:
            with open(append_file, "a") as f:
                f.write(output + "\n")
            print(f"✓ Session appended to {append_file}", file=sys.stderr)
        else:
            print(output)

        os._exit(0)

    except Exception as error:
        print(f"[!] Error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
