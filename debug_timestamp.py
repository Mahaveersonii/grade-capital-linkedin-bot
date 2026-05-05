#!/usr/bin/env python3
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

SESSION_FILE = Path(__file__).parent / "gif_browser_session.json"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        storage_state=str(SESSION_FILE),
        viewport={"width": 1440, "height": 900},
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    )
    page = context.new_page()
    page.goto("https://www.linkedin.com/search/results/content/?keywords=%23IndianCrypto&sortBy=date_posted",
              wait_until="domcontentloaded", timeout=30000)
    time.sleep(5)
    for _ in range(3):
        page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
        time.sleep(2)

    result = page.evaluate(r"""() => {
        const box = document.querySelector('[data-testid="expandable-text-box"]');
        if (!box) return 'NO BOX';
        const output = [];

        let el = box;
        for (let i = 0; i < 30; i++) {
            el = el.parentElement;
            if (!el || el.tagName === 'BODY') break;

            // Look for ANY element whose direct text contains a time pattern like 2w, 3d, 1mo etc
            const allEls = Array.from(el.querySelectorAll('*'));
            for (const nd of allEls) {
                // Only look at leaf-ish nodes (not deeply nested containers)
                const txt = (nd.innerText || '').trim();
                // Match patterns: 2w, 1d, 3h, 4mo, 2m, just now, yesterday etc
                if (/^\d+\s*(w|d|h|mo|m|s)\b/i.test(txt) && txt.length < 30) {
                    output.push(`L${i} <${nd.tagName}> class="${(nd.className||'').substring(0,60)}" text="${txt}"`);
                }
            }
            if (output.length > 0) break;  // Found something, stop walking up
        }
        return output.length ? output.join('\n') : 'NOTHING';
    }""")
    print(result)
    browser.close()
