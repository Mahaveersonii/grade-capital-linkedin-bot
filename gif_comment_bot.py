#!/usr/bin/env python3
"""
Grade Institute of Finance (GIF) — LinkedIn Comment Bot
Finds crypto/blockchain/web3/education posts via Playwright, generates comments
in GIF's educational voice via Claude, then posts them AS the GIF LinkedIn Page
using the official LinkedIn Community Management API.

Setup:
  1. python3 gif_auth.py          ← one-time OAuth, saves token
  2. python3 gif_comment_bot.py   ← run daily (scheduled automatically)
"""

import os, json, time, random, re, sys, requests
from typing import Optional
from pathlib import Path
from datetime import datetime, date
import anthropic
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

# ── Load .env ─────────────────────────────────────────────────────────────────
_ENV = Path(__file__).parent / ".env.gif"
if _ENV.exists():
    for _ln in _ENV.read_text().splitlines():
        _ln = _ln.strip()
        if _ln and not _ln.startswith("#") and "=" in _ln:
            _k, _v = _ln.split("=", 1)
            os.environ[_k.strip()] = _v.strip()

ANTHROPIC_API_KEY   = os.environ["ANTHROPIC_API_KEY"]
LI_CLIENT_ID        = os.environ["GIF_LI_CLIENT_ID"]
LI_CLIENT_SECRET    = os.environ["GIF_LI_CLIENT_SECRET"]
GIF_ORG_ID          = os.environ.get("GIF_ORG_ID", "120903954")   # Grade Institute of Finance
TOKEN_FILE          = Path(__file__).parent / "gif_token.json"

# ── Settings ──────────────────────────────────────────────────────────────────
POSTS_PER_DAY = random.randint(5, 7)
LOG_FILE      = Path(__file__).parent / "gif_commented_posts.json"
MIN_DELAY     = 60
MAX_DELAY     = 150

HASHTAGS = [
    "blockchain", "crypto", "web3", "bitcoin", "defi",
    "cryptoeducation", "blockchainlearning", "web3education",
    "cryptoforbeginners", "financialeducation", "investing",
    "personalfinance", "cryptoIndia", "fintech",
]

# ── GIF voice + style ─────────────────────────────────────────────────────────
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

Post topic: NFTs and Web3
Comment: "The NFT hype cycle burned a lot of learners because they confused the speculation layer with the infrastructure layer. NFTs as a mechanism for provable digital ownership are sound technology. The specific assets people were buying were often worthless. Understanding the difference between the technology and the market using it is the core financial literacy skill web3 demands."
"""


# ── Token management ──────────────────────────────────────────────────────────
def load_token() -> Optional[dict]:
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text())
        except Exception:
            pass
    return None


def save_token(token_data: dict):
    TOKEN_FILE.write_text(json.dumps(token_data, indent=2))


def refresh_access_token(token_data: dict) -> Optional[dict]:
    """Refresh an expired access token using the refresh token."""
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        return None
    try:
        resp = requests.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": LI_CLIENT_ID,
                "client_secret": LI_CLIENT_SECRET,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            new_token = resp.json()
            save_token(new_token)
            return new_token
    except Exception as e:
        print(f"Token refresh failed: {e}")
    return None


def get_valid_token() -> Optional[str]:
    """Return a valid access token, refreshing if needed."""
    token_data = load_token()
    if not token_data:
        print("No token found. Run: python3 gif_auth.py")
        return None

    # Check if token is still valid (LinkedIn tokens last 60 days)
    expires_at = token_data.get("expires_at", 0)
    if time.time() < expires_at - 300:   # 5 min buffer
        return token_data["access_token"]

    # Try to refresh
    print("Access token expired, refreshing...")
    new_token = refresh_access_token(token_data)
    if new_token:
        return new_token["access_token"]

    print("Could not refresh token. Re-run: python3 gif_auth.py")
    return None


# ── LinkedIn API: post comment as GIF page ─────────────────────────────────────
def post_comment_as_gif(access_token: str, post_urn: str, comment_text: str) -> bool:
    """
    Post a comment on a LinkedIn post AS the GIF organization page.
    post_urn examples:
      urn:li:activity:7234567890123456789
      urn:li:ugcPost:7234567890123456789
      urn:li:share:7234567890123456789
    """
    org_urn = f"urn:li:organization:{GIF_ORG_ID}"

    # Normalize URN — activity URNs need to be fetched differently
    # The Comments API uses the share/ugcPost URN, not activity URN
    if "activity" in post_urn:
        # Try to resolve the activity URN via API
        resolve_url = f"https://api.linkedin.com/v2/activities/{post_urn.split(':')[-1]}"
        headers = {"Authorization": f"Bearer {access_token}"}
        r = requests.get(resolve_url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            post_urn = data.get("id", post_urn)  # use resolved URN if available

    url = f"https://api.linkedin.com/v2/socialActions/{post_urn}/comments"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": "202401",
    }
    payload = {
        "actor": org_urn,
        "message": {"text": comment_text},
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        if resp.status_code in (200, 201):
            return True
        print(f"    API error {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as e:
        print(f"    API request error: {e}")
        return False


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


# ── LinkedIn scraping helpers (same as main bot) ───────────────────────────────
import hashlib

def make_post_id(text: str) -> str:
    return hashlib.md5(text[:300].encode()).hexdigest()


def extract_post_urn(page, post_text: str) -> Optional[str]:
    """
    Try to extract the LinkedIn post URN from the page DOM.
    LinkedIn embeds URNs in link hrefs even on search results pages.
    """
    try:
        urn = page.evaluate(f"""() => {{
            // Search all links for URN patterns matching this post
            const links = Array.from(document.querySelectorAll('a[href]'));
            for (const link of links) {{
                const href = link.href || '';
                // Activity URN pattern
                const actMatch = href.match(/activity[:-](\\d{{15,}})/);
                if (actMatch) return 'urn:li:activity:' + actMatch[1];
                // ugcPost URN
                const ugcMatch = href.match(/ugcPost[:-](\\d{{15,}})/);
                if (ugcMatch) return 'urn:li:ugcPost:' + ugcMatch[1];
                // Share URN
                const shareMatch = href.match(/share[:-](\\d{{15,}})/);
                if (shareMatch) return 'urn:li:share:' + shareMatch[1];
            }}
            return null;
        }}""")
        return urn
    except Exception:
        return None


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

            // Also try to extract the post URL/URN from links near this post
            let postUrn = null;
            let container = box;
            for (let i = 0; i < 20; i++) {
                container = container.parentElement;
                if (!container) break;
                const links = container.querySelectorAll('a[href]');
                for (const link of links) {
                    const href = link.href || '';
                    const m = href.match(/activity[:-](\\d{15,})|ugcPost[:-](\\d{15,})|share[:-](\\d{15,})/);
                    if (m) {
                        if (m[1]) postUrn = 'urn:li:activity:' + m[1];
                        else if (m[2]) postUrn = 'urn:li:ugcPost:' + m[2];
                        else if (m[3]) postUrn = 'urn:li:share:' + m[3];
                        break;
                    }
                }
                if (postUrn) break;
            }
            results.push({ text: text.substring(0, 1200), btn_index: btnIndex, post_urn: postUrn });
        }
        return results;
    }""") or []


def human_delay(min_s=1.5, max_s=4.0):
    time.sleep(random.uniform(min_s, max_s))


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

def mark_commented(log: dict, post_id: str, snippet: str, comment: str, urn: str = ""):
    log[post_id] = {
        "date": str(date.today()),
        "snippet": snippet[:120],
        "comment": comment,
        "post_urn": urn,
    }
    save_log(log)


# ── Main ───────────────────────────────────────────────────────────────────────
def run():
    # Get valid API token
    access_token = get_valid_token()
    if not access_token:
        return

    log = load_log()
    today = str(date.today())
    done_today = sum(1 for v in log.values() if v.get("date") == today and v.get("comment") != "SKIP")
    remaining = POSTS_PER_DAY - done_today

    if remaining <= 0:
        print(f"Already posted {done_today} comments today as GIF. Done.")
        return

    print(f"\n{'='*55}")
    print(f"  GIF Comment Bot — {datetime.now():%d %b %Y %H:%M}")
    print(f"  Target: {remaining} more comments today (total {POSTS_PER_DAY})")
    print(f"  Posting as: Grade Institute of Finance (org:{GIF_ORG_ID})")
    print(f"{'='*55}\n")

    SESSION_FILE = Path(__file__).parent / "linkedin_session.json"
    if not SESSION_FILE.exists():
        print("No browser session. Run setup_session.py first.")
        return

    hashtags_today = random.sample(HASHTAGS, min(len(HASHTAGS), 8))
    commented = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"],
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

        # Verify session
        try:
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"Navigation error: {e}")
            browser.close()
            return
        human_delay(3, 6)
        if "authwall" in page.url or "login" in page.url:
            print("Session expired. Re-run setup_session.py.")
            browser.close()
            return
        print("Browser session active.\n")

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
                post_urn  = post.get("post_urn")
                post_id   = make_post_id(post_text)

                if already_commented(log, post_id):
                    continue

                if not post_urn:
                    print(f"  Post: {post_text[:60]}...")
                    print("    No URN found — cannot comment via API, skipping")
                    mark_commented(log, post_id, post_text, "SKIP")
                    continue

                print(f"  Post: {post_text[:80]}...")
                print(f"    URN: {post_urn}")

                comment = generate_comment(post_text)
                if comment is None:
                    print("    Skipped (not relevant or promotional)")
                    mark_commented(log, post_id, post_text, "SKIP")
                    continue

                print(f"    Comment: {comment[:100]}...")

                # Post comment via LinkedIn API as GIF page
                success = post_comment_as_gif(access_token, post_urn, comment)

                if success:
                    mark_commented(log, post_id, post_text, comment, post_urn)
                    commented += 1
                    print(f"    Posted as GIF! ({commented}/{remaining} today)")
                    wait = random.randint(MIN_DELAY, MAX_DELAY)
                    print(f"    Waiting {wait}s...\n")
                    time.sleep(wait)
                else:
                    print("    API post failed")

        browser.close()

    print(f"\nDone. {commented} comments posted as Grade Institute of Finance today.")


if __name__ == "__main__":
    run()
