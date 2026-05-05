#!/usr/bin/env python3
"""
One-time LinkedIn session setup.
Run this ONCE — it opens a browser, you log in, it saves the full session.
After that the main bot uses the saved session automatically.

Run in Terminal: python3 setup_session.py
"""

import time
from playwright.sync_api import sync_playwright
from pathlib import Path

SESSION_FILE = Path(__file__).parent / "linkedin_session.json"

print("\n" + "="*55)
print("  LinkedIn Session Setup — Grade Capital")
print("="*55)
print("\nOpening browser...")
print("1. Make sure you are logged in to LinkedIn in the browser")
print("2. Wait here — it will auto-save after 45 seconds")
print("3. Do NOT close the browser window until you see 'Session saved!'\n")

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)

    # Wait for login — LinkedIn feed takes a moment to fully load
    print("Browser open. Checking login status...")

    # If not logged in, wait up to 60s for user to log in manually
    for i in range(12):
        current_url = page.url
        if "feed" in current_url and "login" not in current_url and "authwall" not in current_url:
            print(f"Feed detected! Saving session...")
            break
        if "login" in current_url or "authwall" in current_url:
            print(f"Login required — please log in in the browser window ({60 - i*5}s remaining)...")
        time.sleep(5)

    # Save the complete session state (all cookies + localStorage)
    context.storage_state(path=str(SESSION_FILE))
    browser.close()

print(f"\nSession saved!")
print(f"File: {SESSION_FILE}")
print("\nYou can now run the bot:")
print("  python3 linkedin_comment_bot.py\n")
