#!/usr/bin/env python3
"""Debug — find data-urn attributes and all link patterns near posts."""
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
    time.sleep(4)
    for _ in range(3):
        page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
        time.sleep(2)

    result = page.evaluate("""() => {
        const output = [];
        const box = document.querySelector('[data-testid="expandable-text-box"]');
        if (!box) return 'NO BOX';

        // Walk up and check EVERY element for data-urn, data-id, data-entity-urn
        let el = box;
        for (let i = 0; i < 30; i++) {
            el = el.parentElement;
            if (!el || el.tagName === 'BODY') break;

            const attrs = ['data-urn', 'data-entity-urn', 'data-id',
                           'data-occludable-job-id', 'data-view-name',
                           'data-finite-scroll-hotkey', 'id'];
            for (const attr of attrs) {
                const val = el.getAttribute(attr);
                if (val && val.length > 3) {
                    output.push(`L${i} [${attr}] = ${val.substring(0,100)}`);
                }
            }

            // Also check number of text boxes at this level
            const boxes = el.querySelectorAll('[data-testid="expandable-text-box"]');
            if (boxes.length > 1) {
                output.push(`L${i} *** MULTIPLE POSTS (${boxes.length}) — sharing scope starts here`);
            }
        }
        return output.join('\\n') || 'NOTHING';
    }""")
    print("=== DATA ATTRIBUTES ===")
    print(result)

    # Also try top-down: find all elements with data-urn containing 'activity' or 'share'
    result2 = page.evaluate("""() => {
        const all = Array.from(document.querySelectorAll('[data-urn], [data-entity-urn]'));
        return all.slice(0,20).map(el =>
            `${el.tagName}.${(el.className||'').substring(0,30)} | ` +
            `data-urn=${el.getAttribute('data-urn')||''} | ` +
            `data-entity-urn=${el.getAttribute('data-entity-urn')||''}`
        ).join('\\n');
    }""")
    print("\n=== TOP-DOWN URN ELEMENTS ===")
    print(result2)

    browser.close()
