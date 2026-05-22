#!/usr/bin/env python3
"""
LinkedIn Comment Bot — Grade Capital / Mahaveer Soni
Finds blockchain/crypto/DeFi posts and generates expert comments.
MANUAL TRIGGER ONLY — run with --post to actually post. Default is dry-run (preview only).

Usage:
    python3 linkedin_comment_bot.py           # preview only, no posting
    python3 linkedin_comment_bot.py --post    # actually post comments
"""

import argparse, os, json, time, random, re, sys
import anthropic
from typing import Optional
from pathlib import Path
from datetime import datetime, date
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

# ── Load .env ─────────────────────────────────────────────────────────────────
_ENV = Path(__file__).parent / ".env"
if _ENV.exists():
    for _ln in _ENV.read_text().splitlines():
        _ln = _ln.strip()
        if _ln and not _ln.startswith("#") and "=" in _ln:
            _k, _v = _ln.split("=", 1)
            os.environ[_k.strip()] = _v.strip()

ANTHROPIC_API_KEY   = os.environ["ANTHROPIC_API_KEY"]
LINKEDIN_LI_AT      = os.environ["LINKEDIN_LI_AT"]        # main session cookie
LINKEDIN_JSESSIONID = os.environ.get("LINKEDIN_JSESSIONID", "")

# ── Settings ──────────────────────────────────────────────────────────────────
POSTS_PER_DAY = random.randint(25, 30)  # temporarily increased
LOG_FILE      = Path(__file__).parent / "commented_posts.json"
MIN_DELAY     = 55    # seconds between comments (keeps it human-paced)
MAX_DELAY     = 140

# Hashtag feeds to browse — will shuffle and cycle through these each run
HASHTAGS = [
    "blockchain", "bitcoin", "crypto", "defi", "web3",
    "smartcontracts", "decentralization", "tokenization",
    "cryptoregulation", "bitcoininvestment", "cryptotrading",
    "layer2", "stablecoins", "cryptofinance",
]

# ── Mahaveer's voice + style ───────────────────────────────────────────────────
AUTHOR_CONTEXT = """
You are writing as Mahaveer Soni, Marketing Manager at Grade Capital — India's first professionally managed crypto derivatives fund.
Background: 3+ years at Grade Capital with deep expertise in options strategies, risk-adjusted returns (Sharpe 1.38), DeFi mechanics, blockchain protocol design, regulatory frameworks (IFSCA, SEBI, FIU-IND), and Indian financial markets.
You think like someone who has navigated real market cycles — not a researcher, not a journalist, someone with actual P&L on the line.
You have opinions. You are not afraid to push back or add nuance that complicates an easy narrative.
"""

STYLE_RULES = """
STYLE RULES — follow every single one:
- 2 to 4 sentences maximum. No bullet points. No lists. No headers.
- Add a specific angle or nuance NOT mentioned in the post — do not just restate or agree
- Use precise domain vocabulary naturally (liquidity, derivatives, regulatory arbitrage, execution layer, governance, tokenization) without over-explaining
- No em dashes or long hyphens (—). Use commas or periods instead.
- No hashtags. No emojis. No markdown formatting of any kind.
- No sycophantic openers ("Great post", "Well said", "Love this", "Totally agree", "Absolutely")
- Do not start your comment with "I" — start with the insight directly
- No hedging language ("I think", "maybe", "perhaps", "I believe") — state it with conviction
- lowercase is fine for impact (see examples below) — do not force capitalization for style
- Do not mention Grade Capital unless it arises completely naturally from the post topic
- Sound like someone who has skin in the game, not someone commenting from the sidelines
"""

COMMENT_EXAMPLES = """
EXAMPLES — match this quality and style exactly:

Post topic: DeFi/TradFi convergence, regulatory certainty vs speed
Comment: "the convergence layer is where execution speed meets regulatory certainty, but most institutions treat this as binary when it's really sequencing. you need the decentralized piece first to prove the model, then layer governance. backwards kills the innovation signal that makes adoption worth it."

Post topic: DeFi/TradFi re-intermediation
Comment: "Re-intermediation with better architecture is probably the most accurate way to describe where this is all heading. The winners won't be pure DeFi or pure TradFi. They'll be the ones who understand both and build the bridge between them."

Post topic: Bitcoin as institutional reserve asset
Comment: "the reserve asset argument works until you stress-test the correlation. most institutions citing bitcoin as a hedge haven't modeled it through a real liquidity crisis. that's when correlation to risk assets spikes and the narrative breaks. the long-term thesis holds, but the path matters."

Post topic: Smart contract security and audits
Comment: "audits reduce exploits but they don't eliminate the attack surface, they just move it. the real risk is at the integration layer between protocols, where no single audit has jurisdiction. composability is what makes DeFi powerful and what makes it catastrophically fragile at the same time."

Post topic: Crypto regulation India / emerging markets
Comment: "the regulatory play in emerging markets is always about who gets to define the rails first. once exchanges are licensed and reporting frameworks are set, the asset classification becomes secondary. India is 18 months into that process and the outcome is already visible to anyone paying attention."
"""


def load_log() -> dict:
    """Load the log of already-commented post IDs."""
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text())
        except Exception:
            pass
    return {}


def save_log(log: dict):
    LOG_FILE.write_text(json.dumps(log, indent=2))


def already_commented(log: dict, post_id: str) -> bool:
    return post_id in log


def mark_commented(log: dict, post_id: str, post_snippet: str, comment: str):
    log[post_id] = {
        "date": str(date.today()),
        "snippet": post_snippet[:120],
        "comment": comment,
    }
    save_log(log)


def human_delay(min_s=1.5, max_s=4.0):
    """Short random pause to simulate human reading/thinking speed."""
    time.sleep(random.uniform(min_s, max_s))


def slow_type(element, text: str):
    """Type text with randomised per-character delay."""
    for char in text:
        element.type(char)
        time.sleep(random.uniform(0.04, 0.13))


# ── Claude: relevance check + comment generation ──────────────────────────────
def generate_comment(post_text: str) -> Optional[str]:
    """
    Returns a comment string if the post is relevant, or None if it should be skipped.
    Single API call — Claude decides relevance AND writes the comment.
    """
    prompt = f"""
{AUTHOR_CONTEXT}

Your task: read the LinkedIn post below and decide:
1. Is it relevant to blockchain, crypto, Bitcoin, DeFi, smart contracts, tokenization, decentralization, or crypto regulation?
2. Is it a genuine opinion/thought piece (not a job posting, course promo, or pure price prediction)?
3. Does it have enough substance to add a meaningful comment to?

If ALL three are YES — write a comment in Mahaveer's voice.
If ANY is NO — respond with exactly: SKIP

{STYLE_RULES}

{COMMENT_EXAMPLES}

POST CONTENT:
\"\"\"{post_text}\"\"\"

Respond with EITHER:
- The comment text only (no explanation, no quotes around it, just the comment)
- OR the word: SKIP
"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            result = resp.content[0].text.strip()

            if result.upper() == "SKIP" or result.upper().startswith("SKIP"):
                return None

            result = result.replace("—", ",").replace("–", "-")
            return result

        except Exception as e:
            print(f"    Claude error: {e}")
            if attempt < 2:
                time.sleep(10 * (attempt + 1))

    return None


# ── LinkedIn scraping helpers ─────────────────────────────────────────────────
import hashlib

def make_post_id(text: str) -> str:
    """Generate a stable ID from post text (LinkedIn no longer exposes data-urn)."""
    return hashlib.md5(text[:300].encode()).hexdigest()


def get_posts_from_page(page) -> list:
    """
    Return list of dicts: {text, btn_index}
    Pairs each expandable-text-box with its OWN Comment button by walking up
    the DOM — no global index guessing.
    btn_index is the position of that post's Comment button among ALL Comment
    buttons on the page (used to click the right one later).
    """
    return page.evaluate("""() => {
        const allCommentBtns = Array.from(document.querySelectorAll('button')).filter(b =>
            b.textContent.trim() === 'Comment' && b.offsetParent !== null
        );

        const boxes = document.querySelectorAll('[data-testid="expandable-text-box"]');
        const results = [];

        for (const box of boxes) {
            const text = box.innerText.trim();
            if (text.length < 80) continue;

            // Walk up DOM from text box to find the container that holds
            // exactly one Comment button (= this post's card)
            let el = box;
            let commentBtn = null;

            for (let i = 0; i < 25; i++) {
                el = el.parentElement;
                if (!el || el.tagName === 'BODY') break;

                const btns = Array.from(el.querySelectorAll('button')).filter(b =>
                    b.textContent.trim() === 'Comment' && b.offsetParent !== null
                );

                if (btns.length === 1) {
                    commentBtn = btns[0];
                    break;
                }
                // If already found multiple, went too high — stop
                if (btns.length > 4) break;
            }

            if (!commentBtn) continue;

            // Find this button's index in the global Comment button list
            const btnIndex = allCommentBtns.indexOf(commentBtn);
            if (btnIndex === -1) continue;

            results.push({ text: text.substring(0, 1200), btn_index: btnIndex });
        }
        return results;
    }""") or []


def click_comment_button_by_index(page, btn_index: int) -> bool:
    """Click the specific Comment button by its global index on the page."""
    try:
        page.evaluate("window.scrollBy(0, 200)")
        human_delay(0.5, 1.0)

        result = page.evaluate(f"""() => {{
            const btns = Array.from(document.querySelectorAll('button')).filter(b =>
                b.textContent.trim() === 'Comment' && b.offsetParent !== null
            );
            if (btns.length > {btn_index}) {{
                btns[{btn_index}].scrollIntoView({{block: 'center'}});
                btns[{btn_index}].click();
                return true;
            }}
            return false;
        }}""")
        if result:
            human_delay(1.5, 3.0)
            return True
    except Exception as e:
        print(f"    click_comment_button error: {e}")
    return False


def type_and_submit_comment(page, comment_text: str) -> bool:
    """Type the comment into the active comment box and submit."""

    # Wait for the comment input to appear (LinkedIn renders it after clicking Comment)
    box = None
    for sel in ["[contenteditable='true']", "div[role='textbox']", ".ql-editor"]:
        try:
            page.wait_for_selector(sel, timeout=8000)
            candidates = page.query_selector_all(sel)
            for c in reversed(candidates):
                if c.is_visible():
                    box = c
                    break
            if box:
                break
        except PwTimeout:
            continue

    if not box:
        print("    Could not find comment box")
        return False

    human_delay(0.5, 1.5)
    box.click()          # focus the editor
    human_delay(0.3, 0.8)

    # Use page.keyboard.type() — properly triggers LinkedIn's React input events
    # This is what makes the blue "Comment" submit button appear
    for char in comment_text:
        page.keyboard.type(char)
        time.sleep(random.uniform(0.04, 0.12))

    human_delay(1.5, 2.5)

    # Find the submit "Comment" button that appears inside the comment form
    # It lives near the contenteditable editor — walk up to find it
    submitted = page.evaluate("""() => {
        const editor = document.querySelector('[contenteditable="true"]');
        if (!editor) return false;

        // Walk up the DOM to find the comment form container, then find its submit button
        let el = editor;
        for (let i = 0; i < 12; i++) {
            el = el.parentElement;
            if (!el) break;
            // Look for a button with text "Comment" that is NOT disabled
            const btns = Array.from(el.querySelectorAll('button')).filter(b =>
                !b.disabled &&
                b.textContent.trim() === 'Comment' &&
                b.offsetParent !== null
            );
            if (btns.length > 0) {
                btns[btns.length - 1].click();   // click the last one (the submit)
                return true;
            }
        }
        return false;
    }""")

    if submitted:
        human_delay(2.5, 4.0)
        return True

    print("    Submit button not found — skipping")
    return False


# ── Main browser session ───────────────────────────────────────────────────────
def run(post: bool = False):
    if not post:
        print("\n[DRY-RUN MODE] Comments will be generated but NOT posted.")
        print("Run with --post to actually post comments.\n")

    log = load_log()
    today = str(date.today())

    # Count actual comments posted today (SKIPs don't count toward the daily quota)
    done_today = sum(1 for v in log.values() if v.get("date") == today and v.get("comment") != "SKIP")
    remaining  = POSTS_PER_DAY - done_today

    if remaining <= 0:
        print(f"Already posted {done_today} comments today. Done.")
        return

    print(f"\n{'='*55}")
    print(f"  LinkedIn Comment Bot — {datetime.now():%d %b %Y %H:%M}")
    mode_label = "POSTING" if post else "DRY-RUN (preview only)"
    print(f"  Mode: {mode_label}")
    print(f"  Target: {remaining} more comments today (total {POSTS_PER_DAY})")
    print(f"{'='*55}\n")

    hashtags_today = random.sample(HASHTAGS, min(len(HASHTAGS), 8))
    commented = 0

    SESSION_FILE = Path(__file__).parent / "linkedin_session.json"

    if not SESSION_FILE.exists():
        print("No session found. Run setup_session.py first:")
        print("  python3 setup_session.py")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        # Load the full saved session (all cookies + localStorage)
        context = browser.new_context(
            storage_state=str(SESSION_FILE),
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )

        page = context.new_page()

        try:
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"Navigation error: {e}")
            print("Session may be expired. Re-run setup_session.py to refresh.")
            browser.close()
            return
        human_delay(3, 6)

        if "authwall" in page.url or "login" in page.url or "checkpoint" in page.url:
            print("Session expired. Re-run setup_session.py to refresh.")
            # Delete stale session file so user knows to redo setup
            SESSION_FILE.unlink(missing_ok=True)
            browser.close()
            return

        print("Logged in successfully.\n")

        for hashtag in hashtags_today:
            if commented >= remaining:
                break

            print(f"Browsing #{hashtag}...")
            # LinkedIn now redirects hashtag feeds to search — use search URL directly
            search_url = (
                f"https://www.linkedin.com/search/results/content/"
                f"?keywords=%23{hashtag}&sortBy=date_posted"
            )
            try:
                page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            except PwTimeout:
                print(f"  Timeout loading #{hashtag}, skipping")
                continue

            human_delay(4, 8)

            # Scroll to load more posts
            for _ in range(4):
                page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                human_delay(2, 4)

            # Get all posts from page using new stable selector
            posts = get_posts_from_page(page)
            print(f"  Found {len(posts)} posts")

            # Process in random order (shuffle indices)
            indices = list(range(len(posts)))
            random.shuffle(indices)

            for idx in indices:
                if commented >= remaining:
                    break

                if idx >= len(posts):
                    continue

                post_item = posts[idx]
                post_text = post_item["text"]
                btn_index = post_item["btn_index"]  # this post's specific Comment button
                post_id = make_post_id(post_text)

                if already_commented(log, post_id):
                    continue

                print(f"  Post: {post_text[:80]}...")

                # Generate comment (Claude decides relevance too)
                comment = generate_comment(post_text)

                if comment is None:
                    print("    Skipped (not relevant or promotional)")
                    mark_commented(log, post_id, post_text, "SKIP")
                    continue

                print(f"    Comment: {comment[:100]}...")

                if not post:
                    # Dry-run: log as preview, don't touch LinkedIn
                    print("    [DRY-RUN] Would post this comment (skipping actual post)")
                    commented += 1
                    continue

                # Click THIS post's Comment button (correctly paired via DOM walk)
                if not click_comment_button_by_index(page, btn_index):
                    print("    Could not click comment button, skipping")
                    continue

                # Type + submit
                success = type_and_submit_comment(page, comment)

                if success:
                    mark_commented(log, post_id, post_text, comment)
                    commented += 1
                    print(f"    Posted! ({commented}/{remaining} today)")

                    # Human-paced gap between comments
                    wait = random.randint(MIN_DELAY, MAX_DELAY)
                    print(f"    Waiting {wait}s before next comment...\n")
                    time.sleep(wait)

                    # Navigate back to search results after commenting
                    try:
                        page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                        human_delay(3, 6)
                        for _ in range(3):
                            page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                            human_delay(2, 3)
                        # Refresh post list
                        posts = get_posts_from_page(page)
                    except Exception:
                        break  # move to next hashtag
                else:
                    print("    Failed to submit comment")
                    # Navigate back to recover
                    try:
                        page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                        human_delay(3, 5)
                    except Exception:
                        pass

        browser.close()

    if post:
        print(f"\nDone. {commented} comments posted today.")
    else:
        print(f"\n[DRY-RUN] Done. {commented} comments previewed (none posted).")
        print("Run with --post to actually post these comments.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--post", action="store_true", help="Actually post comments (default: dry-run preview only)")
    parser.add_argument("--dry-run", action="store_true", help="Preview comments without posting (default behaviour)")
    args = parser.parse_args()
    run(post=args.post)
