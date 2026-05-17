"""Shared-token auth for the bigbox web UI.

One token, generated on first run and persisted under /etc/bigbox/ so OTA
updates don't wipe it. Sent as a SameSite=Strict cookie so cross-site
form posts can't trigger reboot/poweroff.

Bootstrapping: on first start the token is printed to the journal and
written to /etc/bigbox/web_token. Read it once over SSH (or have it
displayed via the device UI later) and paste it into the login page.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import Request, WebSocket

TOKEN_PATH = Path("/etc/bigbox/web_token")
COOKIE_NAME = "bigbox_auth"
ENV_OVERRIDE = "BIGBOX_WEB_TOKEN"


def _load_or_create_token() -> str:
    # Env var wins — useful for dev and for CI tests that don't want to
    # touch /etc.
    env = os.environ.get(ENV_OVERRIDE)
    if env:
        return env.strip()

    try:
        existing = TOKEN_PATH.read_text().strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[web/auth] could not read {TOKEN_PATH}: {e}")

    token = secrets.token_urlsafe(32)
    try:
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(token + "\n")
        TOKEN_PATH.chmod(0o600)
        print(f"[web/auth] generated new web auth token, saved to {TOKEN_PATH}")
        print(f"[web/auth] token: {token}")
    except Exception as e:
        print(f"[web/auth] could not persist token ({e}); using in-memory only")
    return token


TOKEN: str = _load_or_create_token()


def check_request(request: Request) -> bool:
    val = request.cookies.get(COOKIE_NAME, "")
    return bool(val) and secrets.compare_digest(val, TOKEN)


def check_websocket(ws: WebSocket) -> bool:
    val = ws.cookies.get(COOKIE_NAME, "")
    return bool(val) and secrets.compare_digest(val, TOKEN)


def matches(candidate: str) -> bool:
    return bool(candidate) and secrets.compare_digest(candidate.strip(), TOKEN)
