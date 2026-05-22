#!/usr/bin/env python3
"""
Grade Institute of Finance (GIF) — LinkedIn Email Digest Bot
Finds 15 relevant posts daily (max 24 h old), generates sharp opinion comments,
and emails them to mahaveer@grade.capital for manual posting.
"""

import os, json, re, time, random, hashlib, smtplib, urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
from pathlib import Path
from datetime import datetime, date
import anthropic
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

# ── Load .env ─────────────────────────────────────────────────────────────────
_ENV = Path(__file__).parent / ".env"
if _ENV.exists():
    for _ln in _ENV.read_text().splitlines():
        _ln = _ln.strip()
        if _ln and not _ln.startswith("#") and "=" in _ln:
            _k, _v = _ln.split("=", 1)
            os.environ[_k.strip()] = _v.strip()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# ── Settings ──────────────────────────────────────────────────────────────────
POSTS_PER_DAY  = 15
MAX_AGE_HOURS  = 24          # only posts from the last 24 hours
SESSION_FILE   = Path(__file__).parent / "gif_browser_session.json"
LOG_FILE       = Path(__file__).parent / "gif_email_log.json"

EMAIL_FROM = "mahaveer@grade.capital"
EMAIL_TO   = "mahaveer@grade.capital"
EMAIL_PASS = "qfwk aqqe ymes lgmy"
SMTP_HOST  = "smtp.gmail.com"
SMTP_PORT  = 587

# India-focused keyword searches — catches people who don't use hashtags
KEYWORD_SEARCHES = [
    # ── India-first (highest priority) ────────────────────────────────────────
    "blockchain India",
    "web3 India",
    "crypto India",
    "bitcoin India",
    "DeFi India",
    "fintech India",
    "tokenization India",
    "crypto regulation India",
    "Web3 startup India",
    "blockchain finance India",
    # ── Global RWA / Institutional ─────────────────────────────────────────────
    "RWA tokenization",
    "tokenized securities",
    "institutional crypto",
    "on-chain assets",
    "DeFi infrastructure",
]

# Hashtag searches — fallback after keywords exhaust quota
HASHTAG_SEARCHES = [
    # ── Tier 1: RWA / Tokenization ─────────────────────────────────────────────
    "RWA", "Tokenization", "RealEstateTokenization", "DigitalAssets",
    # ── Tier 2: Institutional / Capital Markets ────────────────────────────────
    "CapitalMarkets", "InstitutionalInvesting", "FutureOfFinance", "Blockchain", "DeFi",
    # ── Tier 3: Broad crypto ───────────────────────────────────────────────────
    "cryptocurrency", "investing", "web3", "bitcoin", "ethereum",
    "cryptotrading", "solana", "fintech", "tokenomics",
]

# ── GIF Voice ─────────────────────────────────────────────────────────────────
AUTHOR_CONTEXT = """
You are a sharp, opinionated crypto and finance professional commenting on LinkedIn.
You have deep knowledge of blockchain, DeFi, Bitcoin, Web3, crypto regulation, and markets.
You share strong, contrarian, evidence-backed opinions that make people stop and think.

NEVER mention any company, institution, brand, course, or platform — including GIF.
NEVER reference students, learners, education, teaching, or training.
Speak purely as an individual with conviction and expertise.
"""

STYLE_RULES = """
STYLE RULES — follow every single one:
- 2 to 4 sentences maximum. No bullet points. No lists. No headers.
- Your comment MUST reference a specific fact, number, name, claim, or framing
  that appears in the post. A comment that could apply to ANY post is unacceptable.
- Lead with a sharp, analytical take that adds perspective NOT already in the post.
- You may use em dashes (—) sparingly for rhythm where it reads naturally.
- No hashtags. No emojis. No markdown formatting.
- No sycophantic openers ("Great post", "Well said", "Love this", "Totally agree").
- Do not start with "I" — open with the insight, observation, or framing directly.
- State it with conviction. No hedging ("I think", "maybe", "perhaps", "in my opinion").
- NEVER mention GIF, Grade Institute, students, learners, education, courses, or training.
- Sound like a senior practitioner who understands markets, regulation, and infrastructure.
"""

COMMENT_EXAMPLES = """
EXAMPLES — match this quality and style exactly. Each comment references something
SPECIFIC from the post and adds a layer of analysis the post itself did not make:

Post topic: RWA tokenization maturity analysis
Comment: "This is one of the most honest takes on where RWA tokenization actually stands right now. Marketing has moved faster than analytical frameworks and that gap is a real risk for the space maturing properly."

Post topic: Tokenized infrastructure and new financial rails
Comment: "New rails — that framing is exactly right. The asset class isn't the innovation, the infrastructure underneath it is. Settlement delays and fragmented access aren't small inconveniences, they're structural problems that have been accepted for too long simply because there was no alternative."

Post topic: BlackRock, Franklin Templeton, JPMorgan all moving into tokenization
Comment: "When BlackRock, Franklin Templeton, and JPMorgan are all moving in the same direction, it stops being an experiment and becomes a new standard. The stories that don't trend are often the ones that matter most — institutional conviction at this scale rewrites the risk calculus for everyone else."

Post topic: Institutional tokenization moving from 'if' to 'how'
Comment: "The shift from 'if' to 'how' is exactly where the serious conversation is happening now. Institutions aren't debating whether tokenization is real anymore — they're working through architecture, compliance frameworks, and custody. That's a fundamentally different conversation."

Post topic: RWA market growing from $5B to $24B
Comment: "The jump from $5B to $24B tells you everything about where institutional confidence is heading. What makes RWA tokenization different from previous crypto cycles is that it's solving a real problem — capital that's locked behind geography, regulations, and outdated settlement infrastructure."

Post topic: Bitcoin holding despite macro uncertainty
Comment: "Price holding range while macro uncertainty spikes is exactly the signal that matters. The market is separating Bitcoin's volatility from its fundamentals — and those fundamentals, the supply schedule, the network security, the custody infrastructure, have never been stronger."
"""


# ── Claude: generate comment ──────────────────────────────────────────────────
def generate_comment(post_text: str) -> Optional[str]:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""
{AUTHOR_CONTEXT}

Your task: read the LinkedIn post below and decide whether to comment.

ACCEPT the post (write a comment) if it is:
- About crypto/blockchain/web3 INVESTMENT decisions, portfolio strategy, market analysis,
  or asset allocation — HIGHEST PRIORITY
- From or about India: Indian crypto market, Indian investors, Indian regulation,
  Indian startups — HIGH PRIORITY
- A genuine opinion or analysis about crypto, DeFi, Bitcoin, Web3, NFTs,
  tokenization, or macro finance

SKIP the post (respond with exactly: SKIP) if it is:
- Not written primarily in English
- A job posting, hiring announcement, or recruitment
- A course promotion, webinar invite, or educational product
- A pure price prediction with no analysis ("BTC will hit $100K")
- Spam, giveaway, mining scheme, or promotional content
- Not meaningfully related to crypto, blockchain, web3, or finance

{STYLE_RULES}

{COMMENT_EXAMPLES}

POST CONTENT:
\"\"\"{post_text}\"\"\"

Respond with EITHER:
- The comment text only (no explanation, no quotes around it)
- OR the single word: SKIP
"""
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            result = resp.content[0].text.strip()
            if result.upper().startswith("SKIP"):
                return None
            return result.replace("—", ",").replace("–", "-")
        except anthropic.RateLimitError:
            time.sleep(30 * (attempt + 1))
        except Exception as e:
            print(f"    Claude error: {e}")
            return None
    return None


# ── Log helpers ───────────────────────────────────────────────────────────────
def load_log() -> dict:
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text())
        except Exception:
            pass
    return {}

def save_log(log: dict):
    LOG_FILE.write_text(json.dumps(log, indent=2))

def make_post_id(text: str) -> str:
    return hashlib.md5(text[:300].encode()).hexdigest()

def is_likely_english(text: str) -> bool:
    """Return False if the post is predominantly non-Latin script."""
    sample = text[:400]
    letters = [c for c in sample if c.isalpha()]
    if not letters:
        return True
    latin = sum(1 for c in letters if ord(c) < 256)
    return (latin / len(letters)) > 0.80

def human_delay(min_s=1.5, max_s=4.0):
    time.sleep(random.uniform(min_s, max_s))


# ── Playwright: get posts with age filter ─────────────────────────────────────
def get_posts_from_page(page, max_age_hours: int) -> list:
    """
    Returns post dicts {text, url, ageHours} from the current page,
    filtered to max_age_hours and sorted newest-first.

    LinkedIn does NOT use <time> elements on search-result pages.
    The timestamp is rendered as plain text like "2w •" or "5h •" inside
    a short <div> or <p> near the post card.
    """
    raw = page.evaluate(f"""() => {{
        const MAX_AGE = {max_age_hours};
        const results = [];
        const boxes = document.querySelectorAll('[data-testid="expandable-text-box"]');

        for (const box of boxes) {{
            const text = box.innerText.trim();
            if (text.length < 80) continue;

            let postUrl    = '';   // actual post permalink
            let profileUrl = '';   // author profile URL (for dedup)
            let isPage     = false; // true if author is a company/org page
            let ageHours   = null;
            let el = box;

            for (let i = 0; i < 25; i++) {{
                el = el.parentElement;
                if (!el || el.tagName === 'BODY') break;

                // ── Actual post URL (activity / posts permalink) ─────────────
                if (!postUrl) {{
                    const postLink = el.querySelector(
                        'a[href*="/feed/update/"], a[href*="/posts/"]'
                    );
                    if (postLink) postUrl = postLink.href.split('?')[0];
                }}

                // ── Author profile URL & page-type detection ─────────────────
                // Personal accounts use /in/, company/org pages use /company/
                if (!profileUrl) {{
                    const personalLink = el.querySelector('a[href*="/in/"]');
                    if (personalLink) {{
                        profileUrl = personalLink.href.split('?')[0];
                    }} else {{
                        const companyLink = el.querySelector('a[href*="/company/"]');
                        if (companyLink) {{
                            profileUrl = companyLink.href.split('?')[0];
                            isPage = true;
                        }}
                    }}
                }}

                // ── Timestamp ───────────────────────────────────────────────
                if (ageHours === null) {{
                    const candidates = Array.from(
                        el.querySelectorAll('div, p, span, a')
                    );
                    for (const nd of candidates) {{
                        const t = (nd.innerText || '').trim();
                        if (t.length > 20) continue;
                        const m = t.match(/^(\\d+)\\s*(mo|w|d|h|m|s)\\b/i);
                        if (!m) continue;
                        const n = parseInt(m[1]);
                        const unit = m[2].toLowerCase();
                        if      (unit === 's')  ageHours = n / 3600;
                        else if (unit === 'm')  ageHours = n / 60;
                        else if (unit === 'h')  ageHours = n;
                        else if (unit === 'd')  ageHours = n * 24;
                        else if (unit === 'w')  ageHours = n * 168;
                        else if (unit === 'mo') ageHours = n * 720;
                        // If the timestamp element is itself a link to the post
                        if (!postUrl && nd.tagName === 'A') {{
                            const h = nd.href || '';
                            if (h.includes('/feed/update/') || h.includes('/posts/')) {{
                                postUrl = h.split('?')[0];
                            }}
                        }}
                        break;
                    }}
                }}

                if ((postUrl || profileUrl) && ageHours !== null) break;
            }}

            // Unknown age: let it pass through (treat as fresh)
            if (ageHours === null) ageHours = -1;

            // Hard filter: drop posts older than MAX_AGE hours
            if (ageHours > MAX_AGE) continue;

            results.push({{
                text:       text.substring(0, 1200),
                url:        postUrl || profileUrl,
                profileUrl: profileUrl,
                ageHours:   ageHours,
                isPage:     isPage,
            }});
        }}

        // Sort newest-first; unknown age (-1) goes to the end
        results.sort((a, b) => {{
            const aa = a.ageHours < 0 ? 999999 : a.ageHours;
            const bb = b.ageHours < 0 ? 999999 : b.ageHours;
            return aa - bb;
        }});
        return results;
    }}""") or []
    return raw


# ── Email ─────────────────────────────────────────────────────────────────────
def send_email(items: list):
    today_str = datetime.now().strftime("%d %b %Y")
    subject = f"GIF LinkedIn Comments — {today_str} ({len(items)} posts)"

    # Plain text
    plain_lines = [
        f"GIF LINKEDIN COMMENTS — {today_str}",
        f"Post these {len(items)} comments as Grade Institute of Finance.",
        "=" * 60, ""
    ]
    for i, item in enumerate(items, 1):
        age_str = f"  [{item.get('age_label','')}]" if item.get('age_label') else ""
        plain_lines += [
            f"[{i}] POST LINK:{age_str}",
            item["url"] or "(link not found — search via snippet below)",
            "",
            "POST SNIPPET:",
            item["snippet"],
            "",
            "COMMENT TO POST AS GIF:",
            item["comment"],
            "-" * 60, ""
        ]
    plain_body = "\n".join(plain_lines)

    # HTML
    rows = ""
    for i, item in enumerate(items, 1):
        url_cell = (f'<a href="{item["url"]}" style="color:#0a66c2">{item["url"]}</a>'
                    if item["url"] else "<em>profile link not found — search via snippet</em>")
        age_badge = (
            f'<span style="background:#e0f2e9;color:#1a7340;font-size:11px;'
            f'padding:2px 7px;border-radius:10px;margin-left:8px">'
            f'{item["age_label"]}</span>'
            if item.get("age_label") and item["age_label"] != "age unknown" else ""
        )
        rows += f"""
        <tr style="background:{'#f9f9f9' if i%2==0 else '#fff'}">
          <td style="padding:16px;font-weight:bold;font-size:18px;vertical-align:top;
                     color:#0a66c2;width:30px">{i}</td>
          <td style="padding:16px">
            <p style="margin:0 0 6px"><strong>Post link:</strong> {url_cell}{age_badge}</p>
            <p style="margin:0 0 10px;color:#555;font-size:13px">{item['snippet'][:120]}...</p>
            <div style="background:#e8f4fd;border-left:4px solid #0a66c2;padding:12px 16px;
                        border-radius:4px;font-size:14px;line-height:1.6">
              {item['comment']}
            </div>
          </td>
        </tr>"""

    html_body = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:800px;margin:0 auto;color:#333">
      <div style="background:#0a66c2;padding:20px;border-radius:8px 8px 0 0">
        <h2 style="color:#fff;margin:0">GIF LinkedIn Comments — {today_str}</h2>
        <p style="color:#cce4ff;margin:6px 0 0">
          Post these {len(items)} comments as <strong>Grade Institute of Finance</strong>
        </p>
      </div>
      <div style="background:#fff3cd;padding:12px 20px;border:1px solid #ffc107">
        <strong>How to post:</strong> Open each link, find the post using the snippet,
        click Comment, switch identity to <em>Grade Institute of Finance</em>, paste the text.
      </div>
      <table style="width:100%;border-collapse:collapse;border:1px solid #e0e0e0">
        {rows}
      </table>
      <p style="color:#888;font-size:12px;padding:16px">
        Generated by GIF Comment Bot · {datetime.now().strftime("%d %b %Y %H:%M")}
      </p>
    </body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(EMAIL_FROM, EMAIL_PASS)
        smtp.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
    print(f"  Email sent to {EMAIL_TO}")


# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    if not SESSION_FILE.exists():
        print("No GIF session found. Run: python3 setup_gif_session.py")
        return

    log = load_log()
    today = str(date.today())
    remaining = POSTS_PER_DAY

    print(f"\n{'='*55}")
    print(f"  GIF Email Bot — {datetime.now():%d %b %Y %H:%M}")
    print(f"  Collecting {remaining} comments (max age: {MAX_AGE_HOURS}h)")
    print(f"{'='*55}\n")

    # India keywords first (top 10 fixed), then hashtags (top 9 fixed, rest shuffled)
    rotating_hashtags = HASHTAG_SEARCHES[9:]
    random.shuffle(rotating_hashtags)
    searches_today = (
        [{"q": k, "type": "keyword"} for k in KEYWORD_SEARCHES] +
        [{"q": h, "type": "hashtag"} for h in HASHTAG_SEARCHES[:9] + rotating_hashtags]
    )

    collected      = []
    seen_profiles  = set()  # dedup: one post per author per email batch

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
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
            page.goto("https://www.linkedin.com/feed/",
                      wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"Navigation error: {e}")
            browser.close()
            return

        human_delay(3, 5)

        if "authwall" in page.url or "login" in page.url:
            print("Session expired. Run: python3 setup_gif_session.py")
            SESSION_FILE.unlink(missing_ok=True)
            browser.close()
            return

        try:
            for search in searches_today:
                if len(collected) >= remaining:
                    break

                q = search["q"]
                if search["type"] == "keyword":
                    encoded = urllib.parse.quote_plus(q)
                    search_url = (f"https://www.linkedin.com/search/results/content/"
                                  f"?keywords={encoded}&sortBy=date_posted")
                    label = f'"{q}"'
                else:
                    search_url = (f"https://www.linkedin.com/search/results/content/"
                                  f"?keywords=%23{q}&sortBy=date_posted")
                    label = f"#{q}"

                print(f"Browsing {label}...")
                try:
                    page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                except Exception as e:
                    print(f"  Could not load {label}: {e.__class__.__name__} — skipping")
                    continue

                human_delay(3, 5)
                # Scroll to load more posts
                for _ in range(8):
                    try:
                        page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                        human_delay(1.2, 2.0)
                    except Exception:
                        break

                try:
                    posts = get_posts_from_page(page, MAX_AGE_HOURS)
                except Exception:
                    continue

                print(f"  Found {len(posts)} recent posts (≤{MAX_AGE_HOURS}h old)")

                for post in posts:
                    if len(collected) >= remaining:
                        break

                    post_text   = post["text"]
                    post_url    = post["url"]
                    profile_url = post.get("profileUrl", "")
                    age_h       = post.get("ageHours", -1)
                    post_id     = make_post_id(post_text)

                    if post_id in log:
                        continue

                    # Skip company/org pages — only comment on personal accounts
                    if post.get("isPage"):
                        print("    Skipped (company page)")
                        continue

                    # Skip non-English posts before calling Claude
                    if not is_likely_english(post_text):
                        print("    Skipped (non-English)")
                        log[post_id] = {"date": today, "snippet": post_text[:120],
                                        "comment": "SKIP"}
                        save_log(log)
                        continue

                    # Skip if we already have a post from this author this batch
                    if profile_url and profile_url in seen_profiles:
                        print("    Skipped (duplicate author)")
                        continue

                    if age_h < 0:
                        age_label = "age unknown"
                    elif age_h < 1:
                        age_label = f"{int(age_h * 60)}m ago"
                    elif age_h < 24:
                        age_label = f"{int(age_h)}h ago"
                    else:
                        age_label = f"{age_h/24:.0f}d ago"

                    print(f"  [{age_label}] {post_text[:65]}...")

                    comment = generate_comment(post_text)
                    if comment is None:
                        print("    Skipped (not relevant)")
                        log[post_id] = {"date": today, "snippet": post_text[:120],
                                        "comment": "SKIP"}
                        save_log(log)
                        continue

                    print(f"    Comment ready ({len(comment)} chars)")
                    if profile_url:
                        seen_profiles.add(profile_url)
                    collected.append({
                        "url":       post_url,
                        "snippet":   post_text[:200],
                        "comment":   comment,
                        "age_label": age_label,
                    })
                    log[post_id] = {
                        "date":    today,
                        "snippet": post_text[:120],
                        "comment": comment,
                        "url":     post_url,
                        "age_h":   age_h,
                    }
                    save_log(log)
                    time.sleep(random.uniform(1, 2))

        except Exception as e:
            print(f"Browser error: {e.__class__.__name__} — sending what was collected")
        finally:
            try:
                browser.close()
            except Exception:
                pass

    print(f"\nCollected {len(collected)} comments.")

    if collected:
        print("Sending email...")
        try:
            send_email(collected)
            print(f"Done. Email sent with {len(collected)} comments.")
        except Exception as e:
            print(f"Email error: {e}")
            print("\nFalling back — printing here:\n")
            for i, item in enumerate(collected, 1):
                print(f"[{i}] {item['url']}")
                print(f"    {item['comment']}\n")
    else:
        print("No recent relevant posts found today.")


if __name__ == "__main__":
    run()
