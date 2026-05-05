# How to Get Your LinkedIn Session Cookie

This takes 2 minutes. Do this once. Refresh every 30-60 days.

## Steps

1. Open Chrome and go to linkedin.com — make sure you are logged in as Mahaveer Soni

2. Press F12 to open DevTools (or right-click anywhere → Inspect)

3. Click the "Application" tab in DevTools

4. In the left sidebar, expand "Cookies" → click "https://www.linkedin.com"

5. Find the cookie named **li_at** — click it

6. Copy the entire value from the "Value" column (it's a long string, ~200 characters)

7. Open the .env file in this folder and replace `YOUR_LI_AT_COOKIE_HERE` with what you copied

8. Also find **JSESSIONID** cookie and copy that value too (optional but recommended)

## When to refresh

LinkedIn cookies expire roughly every 30-60 days. When the bot stops working and logs
"Cookie expired", just repeat these steps and paste the new values into .env.

## What happens if the cookie expires mid-run

The bot detects the login redirect automatically, prints a message, and stops cleanly.
No comments are posted. Just refresh the cookie and run again.
