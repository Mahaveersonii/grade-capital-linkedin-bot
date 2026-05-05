#!/usr/bin/env python3
"""
Grade Institute of Finance (GIF) — LinkedIn Browser Comment Bot
Posts 5-7 expert educational comments daily AS the GIF LinkedIn Page
using a saved browser session (no API needed).

Setup (one-time):
  python3 setup_gif_session.py   ← switches identity to GIF, saves session

Then run daily:
  python3 gif_comment_bot_browser.py
"""

import os, json, time, random, hashlib
from typing import Optional
from pathlib import Path
from datetime import datetime, date
import anthropic
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

# ── Load .env ──────────────────────────────────────────────────────────────────
_ENV = Path(__file__).parent / ".env"
if _ENV.exists():
    for _ln in _ENV.read_text().splitlines():
        _ln = _ln.strip()
        if _ln and not _ln.startswith("#") and "=" in _ln:
            _k, _v = _ln.split("=", 1)
            os.environ[_k.strip()] = _v.strip()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# ── Settings ───────────────────────────────────────────────────────────────────
POSTS_PER_DAY = random.randint(5, 7)
SESSION_FILE  = Path(__file__).parent / "gif_browser_session.json"
LOG_FILE      = Path(__file__).parent / "gif_commented_posts.json"
MIN_DELAY     = 60
MAX_DELAY     = 150

HASHTAGS = [
    "blockchain", "crypto", "web3", "bitcoin", "defi",
    "cryptoeducation", "blockchainlearning", "web3education",
    "cryptoforbeginners", "financialeducation", "investing",
    "personalfinance", "cryptoIndia", "fintech",
]

# ── GIF Voice & Style ──────────────────────────────────────────────────────────
AUTHOR_CONTEXT = """
You are writing as Grade Institute of Finance (GIF) — India's leading crypto and blockchain
education platform. GIF's mission is to make crypto/web3/DeFi education accessible,
accurate, and actionable for Indian financial advisors, professionals and retail investors.

Voice: authoritative but approachable. You simplify complex concepts without dumbing them down.
You hold strong, evidence-backed opinions on crypto markets, regulation, and crypto investment in India.
You speak as an institution that has certified thousands of financial advisors — you know what concepts people
get wrong, what misconceptions are most dangerous, and what knowledge gaps cost advisors and their clients money.
"""

STYLE_RULES = """
STYLE RULES — follow every single one:
- 2 to 4 sentences maximum. No bullet points. No lists. No headers.
- Add a specific educational insight or correct a common misconception NOT mentioned in the post
- Use clear language — GIF educates people, so no unexplained jargon. If you use a term, briefly ground it.
- No em dashes or long hyphens (—). Use commas or periods instead.
- No hashtags. No emojis. No markdown formatting.
- No sycophantic openers ("Great post", "Well said", "Love this", "Totally agree")
- Do not start with "I" or "We" — start with the insight directly
- State it with conviction. No hedging ("I think", "maybe", "perhaps")
- Sound like an institution that has seen 1000 advisors make the same mistake with clients
- Occasionally reference what advisors GIF has certified commonly misunderstand about this topic
"""

COMMENT_EXAMPLES = """
EXAMPLES — match this quality and style exactly:

Post topic: What is DeFi?
Comment: "Most people learn DeFi by starting with protocols, which is backwards. Start with the problem: traditional finance excludes 1.7 billion people globally because it requires documentation, credit history, and geography. DeFi removes all three gatekeepers. Once learners understand the problem it solves, the protocol design makes sense immediately."

Post topic: Bitcoin price volatility
Comment: "Volatility is the price of asymmetric upside, and that framing changes everything for a new investor. What GIF teaches is to separate price volatility from fundamental volatility. Bitcoin's price moves wildly. Its supply schedule, consensus mechanism, and network security have never changed. Learning to distinguish the two is the first step to holding without panic-selling."

Post topic: Crypto regulation India
Comment: "The most dangerous misconception we see among learners is that regulation means restriction. India's IFSCA framework at GIFT City is actually creating a pathway for legal participation that didn't exist before. Regulated access is better than unregulated access for long-term wealth building, and that distinction matters enormously for anyone calculating tax exposure."

Post topic: Smart contracts explained
Comment: "Smart contracts are not magic and not software in the traditional sense. They are enforced commitments: code that executes automatically when conditions are met, with no counterparty risk. The analogy we use at GIF: a vending machine is the world's oldest smart contract. You put in the right input, you get the output. No human can intercept the transaction."
"""


# ── Claude: generate comment ───────────────────────────────────────────────────
def generate_comment(post_text: str) -> Optional[str]:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""
{AUTHOR_CONTEXT}

Your task: read the LinkedIn post below and decide:
1. Is it relevant to blockchain, crypto, Bitcoin, DeFi, web3, NFTs, tokenization, or crypto/financial education?
2. Is it a genuine opinion/thought piece (not a job posting, course promo, or pure price prediction)?
3. Does it have enough substance to add meaningful educational value in a comment?

If ALL three are YES — write a comment in GIF's voice.
If ANY is NO — respond with exactly: SKIP

{STYLE_RULES}

{COMMENT_EXAMPLES}

POST CONTENT:
\"\"\"{post_text}\"\"\"

Respond with EITHER:
- The comment text only (no explanation, no quotes around it)
- OR the word: SKIP
"""
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            result = resp.content[0].text.strip()
            if result.upper().startswith("SKIP"):
                return None
            result = result.replace("—", ",").replace("–", "-")
            return result
        except anthropic.RateLimitError:
            wait = 30 * (attempt + 1)
            print(f"    Rate limit — waiting {wait}s...")
            time.sleep(wait)
        except Exception as e:
            print(f"    Claude error: {e}")
            return None
    return None


# ── Log helpers ────────────────────────────────────────────────────────────────
def load_log() -> dict:
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

def mark_commented(log: dict, post_id: str, snippet: str, comment: str):
    log[post_id] = {
        "date": str(date.today()),
        "snippet": snippet[:120],
        "comment": comment,
    }
    save_log(log)

def make_post_id(text: str) -> str:
    return hashlib.md5(text[:300].encode()).hexdigest()

def human_delay(min_s=1.5, max_s=4.0):
    time.sleep(random.uniform(min_s, max_s))


# ── Playwright helpers ─────────────────────────────────────────────────────────
def get_posts_from_page(page) -> list:
    return page.evaluate("""() => {
        const allCommentBtns = Array.from(document.querySelectorAll('button')).filter(b =>
            b.textContent.trim() === 'Comment' && b.offsetParent !== null
        );
        const boxes = document.querySelectorAll('[data-testid="expandable-text-box"]');
        const results = [];
        for (const box of boxes) {
            const text = box.innerText.trim();
            if (text.length < 80) continue;
            let el = box;
            let commentBtn = null;
            for (let i = 0; i < 25; i++) {
                el = el.parentElement;
                if (!el || el.tagName === 'BODY') break;
                const btns = Array.from(el.querySelectorAll('button')).filter(b =>
                    b.textContent.trim() === 'Comment' && b.offsetParent !== null
                );
                if (btns.length === 1) { commentBtn = btns[0]; break; }
                if (btns.length > 4) break;
            }
            if (!commentBtn) continue;
            const btnIndex = allCommentBtns.indexOf(commentBtn);
            if (btnIndex === -1) continue;
            results.push({ text: text.substring(0, 1200), btn_index: btnIndex });
        }
        return results;
    }""") or []


def switch_to_gif_identity(page) -> bool:
    """Switch active LinkedIn identity to Grade Institute of Finance via the Me nav dropdown."""
    try:
        # Click the "Me" nav button in the top navigation bar
        me_result = page.evaluate("""() => {
            const candidates = Array.from(document.querySelectorAll(
                '#global-nav a, #global-nav button, .global-nav a, .global-nav button, nav a, nav button'
            )).filter(el => el.offsetParent !== null);

            for (const el of candidates) {
                const raw  = el.innerText.trim();
                const text = raw.toLowerCase().replace(/\\s+/g, ' ');
                const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                const trig = (el.getAttribute('data-link-to-trigger') || '').toLowerCase();
                if (text === 'me' || aria === 'me' || trig === 'nav.settings'
                        || text.startsWith('me ') || text.endsWith(' me')) {
                    el.scrollIntoView({block: 'center'});
                    el.click();
                    return 'clicked:' + raw.substring(0, 20);
                }
            }
            return 'not_found';
        }""")

        print(f"  Me dropdown: {me_result}")
        if 'not_found' in me_result:
            return False

        human_delay(1.5, 2.5)

        # Select GIF from the dropdown
        for label in ["Grade Institute of Finance", "Grade Institute", "GIF"]:
            try:
                page.click(f"text={label}", timeout=3000)
                human_delay(2, 3)
                print(f"  Clicked '{label}' in Me dropdown")
                # Navigate to feed to verify the switch
                page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
                human_delay(2, 3)
                # After switching to a page, LinkedIn shows the page name prominently in the nav
                nav_html = page.evaluate("""() => {
                    const nav = document.querySelector('#global-nav, .global-nav, nav');
                    return nav ? nav.innerText.toLowerCase() : '';
                }""")
                if "grade institute" in nav_html:
                    print("  Confirmed: browsing as Grade Institute of Finance.")
                    return True
                # Fallback: check broader page content
                if "grade institute of finance" in page.content().lower():
                    return True
            except Exception:
                continue

    except Exception as e:
        print(f"  switch_to_gif_identity error: {e}")
    return False


def switch_post_identity_to_gif(page, btn_index: int) -> bool:
    """Click the avatar+▼ button in the post action bar (same row as Like/Comment)
    to switch 'acting as' to Grade Institute of Finance BEFORE commenting."""

    def pick_gif_from_dropdown() -> bool:
        for label in ["Grade Institute of Finance", "Grade Institute", "GIF"]:
            try:
                page.click(f"text={label}", timeout=4000)
                human_delay(1.0, 1.5)
                return True
            except Exception:
                continue
        return False

    try:
        result = page.evaluate(f"""() => {{
            const commentBtns = Array.from(document.querySelectorAll('button')).filter(b =>
                b.textContent.trim() === 'Comment' && b.offsetParent !== null
            );
            if (commentBtns.length <= {btn_index}) return 'no_comment_btn';
            const commentBtn = commentBtns[{btn_index}];

            // Walk UP and dump all buttons at each level for diagnosis
            let el = commentBtn;
            let diagnostics = [];
            for (let i = 0; i < 15; i++) {{
                el = el.parentElement;
                if (!el || el.tagName === 'BODY') break;
                const allBtns = Array.from(el.querySelectorAll('button'));
                if (allBtns.length > 0 && allBtns.length < 25) {{
                    diagnostics.push('L' + i + ':' + allBtns.map(b =>
                        '[' + b.innerText.trim().substring(0,15) + '|' +
                        (b.getAttribute('aria-label')||'').substring(0,20) + '|img:' +
                        (!!b.querySelector('img')) + '|op:' + (!!b.offsetParent) + ']'
                    ).join(','));
                }}

                // Action bar: contains Like AND Comment buttons
                const texts = allBtns.map(b => b.innerText.trim().toLowerCase());
                if (!texts.includes('like') || !texts.includes('comment')) continue;

                const actionNames = ['like', 'comment', 'repost', 'send', 'share'];
                // Try WITH offsetParent filter first
                for (const checkOffsetParent of [true, false]) {{
                    for (const btn of allBtns) {{
                        if (checkOffsetParent && !btn.offsetParent) continue;
                        const txt  = btn.innerText.trim().toLowerCase();
                        if (actionNames.includes(txt)) continue;
                        const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
                        if (aria.includes('reaction') || aria.includes('like')) continue;
                        if (aria.includes('grade institute')) return 'already_gif';
                        if (btn.querySelector('img')) {{
                            btn.scrollIntoView({{block: 'center'}});
                            btn.click();
                            return 'clicked:' + aria.substring(0, 60);
                        }}
                    }}
                }}
                return 'action_bar_found_no_avatar|' + diagnostics.join('||');
            }}
            return 'not_found|' + diagnostics.join('||');
        }}""")

        print(f"    Identity switch: {result}")
        if result == 'already_gif':
            return True
        if result and result.startswith('clicked'):
            human_delay(1.0, 1.5)
            if pick_gif_from_dropdown():
                print("    Switched to GIF.")
                return True
    except Exception as e:
        print(f"    Identity switch error: {e}")

    try:
        debug_path = Path(__file__).parent / "debug_identity.png"
        page.screenshot(path=str(debug_path))
        print(f"    Debug screenshot: {debug_path}")
    except Exception:
        pass
    return False


def click_comment_button_by_index(page, btn_index: int) -> bool:
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
    box.click()
    human_delay(0.3, 0.8)

    for char in comment_text:
        page.keyboard.type(char)
        time.sleep(random.uniform(0.04, 0.12))

    human_delay(1.5, 2.5)

    submitted = page.evaluate("""() => {
        const editor = document.querySelector('[contenteditable="true"]');
        if (!editor) return false;
        let el = editor;
        for (let i = 0; i < 12; i++) {
            el = el.parentElement;
            if (!el) break;
            const btns = Array.from(el.querySelectorAll('button')).filter(b =>
                !b.disabled &&
                b.textContent.trim() === 'Comment' &&
                b.offsetParent !== null
            );
            if (btns.length > 0) {
                btns[btns.length - 1].click();
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


# ── Main ───────────────────────────────────────────────────────────────────────
def run():
    if not SESSION_FILE.exists():
        print("No GIF session found. Run setup_gif_session.py first:")
        print("  python3 setup_gif_session.py")
        return

    log = load_log()
    today = str(date.today())
    done_today = sum(1 for v in log.values() if v.get("date") == today and v.get("comment") != "SKIP")
    remaining = POSTS_PER_DAY - done_today

    if remaining <= 0:
        print(f"Already posted {done_today} comments today as GIF. Done.")
        return

    print(f"\n{'='*55}")
    print(f"  GIF Comment Bot (Browser) — {datetime.now():%d %b %Y %H:%M}")
    print(f"  Target: {remaining} more comments today (total {POSTS_PER_DAY})")
    print(f"  Posting as: Grade Institute of Finance")
    print(f"{'='*55}\n")

    hashtags_today = random.sample(HASHTAGS, min(len(HASHTAGS), 8))
    commented = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage", "--start-maximized"],
        )
        context = browser.new_context(
            storage_state=str(SESSION_FILE),
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )
        page = context.new_page()

        try:
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"Navigation error: {e}")
            browser.close()
            return

        human_delay(3, 6)

        if "authwall" in page.url or "login" in page.url or "checkpoint" in page.url:
            print("GIF session expired. Re-run setup_gif_session.py.")
            SESSION_FILE.unlink(missing_ok=True)
            browser.close()
            return

        # Always switch to GIF identity at startup via Me nav dropdown
        print("Switching identity to Grade Institute of Finance...")
        switched = switch_to_gif_identity(page)
        if not switched:
            print("Could not switch to GIF identity. Re-run: python3 setup_gif_session.py")
            browser.close()
            return
        print("Identity active: Grade Institute of Finance\n")

        for hashtag in hashtags_today:
            if commented >= remaining:
                break

            print(f"Browsing #{hashtag}...")
            search_url = f"https://www.linkedin.com/search/results/content/?keywords=%23{hashtag}&sortBy=date_posted"

            try:
                page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            except PwTimeout:
                print(f"  Timeout loading #{hashtag}, skipping")
                continue

            human_delay(4, 8)
            for _ in range(4):
                page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                human_delay(2, 4)

            posts = get_posts_from_page(page)
            print(f"  Found {len(posts)} posts")

            indices = list(range(len(posts)))
            random.shuffle(indices)

            for idx in indices:
                if commented >= remaining:
                    break

                post = posts[idx]
                post_text = post["text"]
                btn_index = post["btn_index"]
                post_id = make_post_id(post_text)

                if already_commented(log, post_id):
                    continue

                print(f"  Post: {post_text[:80]}...")

                comment = generate_comment(post_text)
                if comment is None:
                    print("    Skipped (not relevant or promotional)")
                    mark_commented(log, post_id, post_text, "SKIP")
                    continue

                print(f"    Comment: {comment[:100]}...")

                if not click_comment_button_by_index(page, btn_index):
                    print("    Could not click comment button, skipping")
                    continue

                success = type_and_submit_comment(page, comment)

                if success:
                    mark_commented(log, post_id, post_text, comment)
                    commented += 1
                    print(f"    Posted as GIF! ({commented}/{remaining} today)")
                    wait = random.randint(MIN_DELAY, MAX_DELAY)
                    print(f"    Waiting {wait}s...\n")
                    time.sleep(wait)

                    try:
                        page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                        human_delay(3, 6)
                        for _ in range(3):
                            page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                            human_delay(2, 3)
                        posts = get_posts_from_page(page)
                    except Exception:
                        break
                else:
                    print("    Failed to submit comment")
                    try:
                        page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                        human_delay(3, 5)
                    except Exception:
                        pass

        browser.close()

    print(f"\nDone. {commented} comments posted as Grade Institute of Finance today.")


if __name__ == "__main__":
    run()
