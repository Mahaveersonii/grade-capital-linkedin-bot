#!/usr/bin/env python3
"""
One-time LinkedIn OAuth2 setup for Grade Institute of Finance page.
Run this once to get and save the access token.

Run: python3 gif_auth.py
"""

import os, json, time, webbrowser
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode
import requests

# ── Load .env.gif ──────────────────────────────────────────────────────────────
_ENV = Path(__file__).parent / ".env.gif"
if _ENV.exists():
    for _ln in _ENV.read_text().splitlines():
        _ln = _ln.strip()
        if _ln and not _ln.startswith("#") and "=" in _ln:
            _k, _v = _ln.split("=", 1)
            os.environ[_k.strip()] = _v.strip()

CLIENT_ID     = os.environ["GIF_LI_CLIENT_ID"]
CLIENT_SECRET = os.environ["GIF_LI_CLIENT_SECRET"]
REDIRECT_URI  = "http://localhost:8888/callback"
TOKEN_FILE    = Path(__file__).parent / "gif_token.json"

# Scopes needed for page commenting
SCOPES = "r_organization_social w_organization_social r_basicprofile"

auth_code_holder = {"code": None}


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/callback":
            params = parse_qs(parsed.query)
            if "code" in params:
                auth_code_holder["code"] = params["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"""
                <html><body style="font-family:sans-serif;text-align:center;padding:50px">
                <h2>&#x2705; Authorised!</h2>
                <p>Grade Institute of Finance bot is connected to LinkedIn.</p>
                <p>You can close this tab now.</p>
                </body></html>
                """)
            else:
                error = params.get("error_description", ["Unknown error"])[0]
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f"Error: {error}".encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress request logs


def main():
    print("\n" + "="*55)
    print("  GIF LinkedIn OAuth Setup")
    print("="*55)

    # Build auth URL
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": "gif_bot_auth",
    }
    auth_url = "https://www.linkedin.com/oauth/v2/authorization?" + urlencode(params)

    print("\nOpening LinkedIn authorization in your browser...")
    print("Log in as Mahaveer Soni and approve access for Grade Institute of Finance.\n")
    webbrowser.open(auth_url)

    # Start local callback server
    print("Waiting for LinkedIn to redirect back...")
    server = HTTPServer(("localhost", 8888), CallbackHandler)
    server.timeout = 120  # wait up to 2 minutes

    while auth_code_holder["code"] is None:
        server.handle_request()

    code = auth_code_holder["code"]
    print(f"Auth code received. Exchanging for access token...")

    # Exchange code for token
    resp = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        timeout=15,
    )

    if resp.status_code != 200:
        print(f"Token exchange failed: {resp.status_code} — {resp.text}")
        return

    token_data = resp.json()
    # Store expiry time
    token_data["expires_at"] = time.time() + token_data.get("expires_in", 5184000)
    TOKEN_FILE.write_text(json.dumps(token_data, indent=2))

    print(f"\nAccess token saved to: {TOKEN_FILE}")
    print(f"Token expires in: {token_data.get('expires_in', 0) // 86400} days")
    print("\nYou can now run the GIF comment bot:")
    print("  python3 gif_comment_bot.py\n")


if __name__ == "__main__":
    main()
