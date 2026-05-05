#!/usr/bin/env python3
"""
One-time setup: loads your LinkedIn session, switches identity to
Grade Institute of Finance page, and saves that session.

After this, gif_comment_bot_browser.py will post ALL comments as GIF.

Run: python3 setup_gif_session.py
"""

import time
from playwright.sync_api import sync_playwright
from pathlib import Path

MAIN_SESSION = Path(__file__).parent / "linkedin_session.json"
GIF_SESSION  = Path(__file__).parent / "gif_browser_session.json"

print("\n" + "="*55)
print("  GIF LinkedIn Session Setup")
print("="*55)

if not MAIN_SESSION.exists():
    print("\nNo base session found. Run setup_session.py first.")
    exit(1)

print("\nOpening browser with your LinkedIn session...")
print("We will switch your identity to Grade Institute of Finance.\n")

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        storage_state=str(MAIN_SESSION),
        viewport={"width": 1440, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()

    print("Loading LinkedIn feed...")
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)

    if "login" in page.url or "authwall" in page.url:
        print("Session expired. Re-run setup_session.py first.")
        browser.close()
        exit(1)

    print("Logged in as Mahaveer. Attempting to switch to GIF page...\n")

    # ── Try automatic identity switch ─────────────────────────────────────────
    switched = False

    # Try clicking the "Me" nav trigger to open the identity dropdown
    me_selectors = [
        "[data-control-name='nav.settings']",
        "button[data-alias='me']",
        "#global-nav-icon-btn",
        "button.global-nav__me-photo",
        "[aria-label='Me']",
    ]
    for sel in me_selectors:
        try:
            page.click(sel, timeout=3000)
            time.sleep(1.5)
            break
        except Exception:
            continue

    # Try to find and click GIF page in the switcher dropdown
    gif_labels = [
        "Grade Institute of Finance",
        "grade institute of finance",
        "GIF",
    ]
    for label in gif_labels:
        try:
            page.click(f"text={label}", timeout=3000)
            time.sleep(2)
            switched = True
            print(f"Switched to GIF page via identity switcher.")
            break
        except Exception:
            continue

    # ── Manual fallback ───────────────────────────────────────────────────────
    if not switched:
        print("Auto-switch did not work (LinkedIn UI varies by account).")
        print("\n" + "-"*55)
        print("MANUAL STEPS — do this in the browser window:")
        print("-"*55)
        print("1. Click your profile picture at the TOP RIGHT of LinkedIn")
        print("2. In the dropdown, look for 'Grade Institute of Finance'")
        print("   under 'Switch to another account' or 'Manage pages'")
        print("3. Click on it — the page banner should change to GIF")
        print("4. Come back here and press ENTER")
        print("-"*55)
        input("\nPress ENTER once you have switched to GIF identity → ")

    # ── Verify identity ───────────────────────────────────────────────────────
    print("\nVerifying identity switch...")
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
    time.sleep(2)

    page_source = page.content().lower()
    if "grade institute of finance" in page_source:
        print("GIF identity confirmed in page.")
    else:
        print("Could not auto-confirm — saving session anyway.")
        print("If comments post as Mahaveer instead of GIF, re-run this script.")

    # ── Save session ──────────────────────────────────────────────────────────
    context.storage_state(path=str(GIF_SESSION))
    browser.close()

print(f"\nGIF session saved to: {GIF_SESSION}")
print("\nYou can now run the GIF comment bot:")
print("  python3 gif_comment_bot_browser.py\n")
