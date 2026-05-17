from __future__ import annotations

import asyncio
import io
import time
from typing import TYPE_CHECKING

import pygame
import os
import shutil
import pty
import fcntl
import termios
import struct
import subprocess
from fastapi import FastAPI, Request, Response, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from bigbox.events import Button, ButtonEvent
from bigbox import wigle as wigle_mod
from bigbox import emulator as emu_mod
from bigbox import retroachievements as ra_mod
from bigbox import shop as shop_mod
from bigbox import webhooks as webhook_mod
from bigbox.gps import GPSReader

from bigbox import system as system_mod
from bigbox import background as bg_mod
from bigbox import activity as activity_mod
from bigbox.web import auth as web_auth

if TYPE_CHECKING:
    from bigbox.app import App

app = FastAPI()


# Paths that bypass auth: the login page itself, the phone GPS link the
# user shares deliberately, and the streaming MJPEG mirror (the WebSocket
# terminal and dashboard are still gated).
_AUTH_EXEMPT_PREFIXES = ("/auth/", "/gps/link", "/gps/phone")


@app.middleware("http")
async def _security_and_auth(request: Request, call_next):
    path = request.url.path
    is_exempt = any(path == p or path.startswith(p) for p in _AUTH_EXEMPT_PREFIXES)
    if not is_exempt and not web_auth.check_request(request):
        # Browser hitting the dashboard → bounce to login. Anything else
        # (XHR, fetch, curl) → 401 so the JS wrapper can redirect cleanly.
        accept = request.headers.get("accept", "")
        if request.method == "GET" and "text/html" in accept:
            return RedirectResponse(url="/auth/login", status_code=303)
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    resp = await call_next(request)
    # Defense in depth: stop the dashboard from being framed by another origin,
    # block MIME sniffing on uploads, and keep referer leakage down.
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    return resp


_LOGIN_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>bigbox login</title>
<style>
  body { background: #06070b; color: #cfe; font-family: monospace;
         display: flex; align-items: center; justify-content: center;
         height: 100vh; margin: 0; }
  form { background: #0d1118; padding: 24px 28px; border: 1px solid #2a3140;
         border-radius: 4px; min-width: 280px; }
  h1 { margin: 0 0 14px 0; font-size: 14px; color: #5ae6aa;
       letter-spacing: 2px; }
  input[type=password] { width: 100%; padding: 8px 10px; box-sizing: border-box;
                         background: #000; color: #cfe; border: 1px solid #2a3140;
                         font-family: monospace; font-size: 13px; }
  button { margin-top: 12px; width: 100%; padding: 8px; background: #1b2a3a;
           color: #cfe; border: 1px solid #5ae6aa; cursor: pointer;
           font-family: monospace; letter-spacing: 1px; }
  button:hover { background: #243549; }
  .err { color: #e66; font-size: 11px; margin-top: 8px; min-height: 14px; }
  .hint { color: #556; font-size: 10px; margin-top: 12px; line-height: 1.4; }
</style></head><body>
<form method="post" action="/auth/login">
  <h1>BIGBOX // AUTH</h1>
  <input type="password" name="token" placeholder="auth token" autofocus required>
  <button type="submit">AUTHENTICATE</button>
  <div class="err">__ERR__</div>
  <div class="hint">token at /etc/bigbox/web_token on device<br>(journalctl -u bigbox to see it)</div>
</form></body></html>"""


def _login_html(error: str = "") -> HTMLResponse:
    body = _LOGIN_PAGE.replace("__ERR__", error)
    return HTMLResponse(body)


@app.get("/auth/login", response_class=HTMLResponse)
async def auth_login_page(request: Request):
    if web_auth.check_request(request):
        return RedirectResponse(url="/", status_code=303)
    return _login_html()


@app.post("/auth/login")
async def auth_login(token: str = Form(...)):
    if not web_auth.matches(token):
        return _login_html("invalid token")
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie(
        key=web_auth.COOKIE_NAME,
        value=token.strip(),
        httponly=True,
        samesite="strict",
        max_age=60 * 60 * 24 * 30,  # 30 days
        path="/",
    )
    return resp


@app.post("/auth/logout")
async def auth_logout():
    resp = JSONResponse({"status": "ok"})
    resp.delete_cookie(web_auth.COOKIE_NAME, path="/")
    return resp


@app.get("/system/stats")
async def system_stats():
    return system_mod.get_system_stats()

@app.get("/system/activity")
async def activity_list():
    recent = activity_mod.recent(20)
    return [{
        "ts": e.ts,
        "message": e.message
    } for e in recent]

@app.get("/gps/current")
async def gps_current():
    fix = GPSReader.get_shared().latest()
    return {
        "has_fix": fix.has_fix,
        "lat": fix.lat,
        "lon": fix.lon,
        "alt": fix.alt_m,
        "sats": fix.sats,
        "speed": fix.speed_kmh,
        "heading": fix.heading_deg,
        "device": fix.device_path
    }

@app.get("/tasks")
async def tasks_list():
    tasks = bg_mod.list_tasks()
    return [{
        "id": t.id,
        "label": t.label,
        "section": t.section,
        "started_at": t.started_at,
        "age_seconds": time.time() - t.started_at
    } for t in tasks]

@app.post("/tasks/stop/{task_id}")
async def task_stop(task_id: str):
    ok = bg_mod.stop_one(task_id)
    return {"status": "ok" if ok else "not_found"}

@app.post("/tasks/stop_all")
async def tasks_stop_all():
    bg_mod.stop_all()
    return {"status": "ok"}

@app.post("/system/reboot")
async def system_reboot():
    subprocess.Popen(["systemctl", "reboot"])
    return {"status": "rebooting"}

@app.post("/system/poweroff")
async def system_poweroff():
    subprocess.Popen(["systemctl", "poweroff"])
    return {"status": "powering_off"}

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
MEDIA_DIR = Path("media")
ALLOWED_FOLDERS = ("movies", "tv")
MEDIA_DIR.mkdir(exist_ok=True)
for _sub in ALLOWED_FOLDERS:
    (MEDIA_DIR / _sub).mkdir(exist_ok=True)

# Global reference to the running Bigbox App
_bb_app: App | None = None

def set_app(bb_app: App):
    global _bb_app
    _bb_app = bb_app

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")

@app.websocket("/ws/terminal")
async def terminal_websocket(websocket: WebSocket):
    # HTTP middleware doesn't run on WS upgrades; check the cookie inline.
    if not web_auth.check_websocket(websocket):
        await websocket.close(code=1008, reason="unauthorized")
        return
    await websocket.accept()

    # Spawn bash in a PTY
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        ["/bin/bash"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        preexec_fn=os.setsid,
        env={**os.environ, "TERM": "xterm-256color", "HOME": "/root"}
    )
    os.close(slave_fd)

    # Set non-blocking
    fl = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    async def pty_to_ws():
        try:
            while True:
                await asyncio.sleep(0.01)
                try:
                    data = os.read(master_fd, 1024)
                    if not data:
                        break
                    await websocket.send_bytes(data)
                except BlockingIOError:
                    continue
                except Exception:
                    break
        except Exception:
            pass

    task = asyncio.create_task(pty_to_ws())

    try:
        while True:
            data = await websocket.receive_json()
            if data["type"] == "input":
                os.write(master_fd, data["data"].encode())
            elif data["type"] == "resize":
                buf = struct.pack("HHHH", data["rows"], data["cols"], 0, 0)
                fcntl.ioctl(master_fd, termios.TIOCSWINSZ, buf)
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        task.cancel()
        if proc.poll() is None:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        os.close(master_fd)

@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    folder: str = Form("movies"),
):
    if folder not in ALLOWED_FOLDERS:
        raise HTTPException(
            status_code=400,
            detail=f"folder must be one of {ALLOWED_FOLDERS}",
        )
    # Strip any path components from the client-supplied filename so an
    # upload can't escape MEDIA_DIR/<folder>/.
    safe_name = os.path.basename(file.filename or "")
    if not safe_name:
        raise HTTPException(status_code=400, detail="missing filename")

    target_dir = MEDIA_DIR / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / safe_name

    # Stream the file to disk in chunks instead of using shutil.copyfileobj
    # on the SpooledTemporaryFile, which can be slow/memory intensive for 1GB+
    try:
        with file_path.open("wb") as buffer:
            while chunk := await file.read(1024 * 1024): # 1MB chunks
                buffer.write(chunk)
    except Exception as e:
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail=f"write failed: {e}")
    finally:
        await file.close()

    # Refresh the device-side player if it's open. refresh() handles both
    # the category screen and any open file list. Fall back to the legacy
    # _refresh_list() name if a stale build is somehow running.
    if _bb_app and _bb_app.media_view:
        try:
            if hasattr(_bb_app.media_view, "refresh"):
                _bb_app.media_view.refresh()
            else:
                _bb_app.media_view.list = _bb_app.media_view._refresh_list()
        except Exception as e:
            print(f"[web] media refresh failed: {e}")

    return {"filename": safe_name, "folder": folder, "status": "uploaded"}


@app.get("/media")
async def list_media():
    """Quick listing of what's in each folder, for the web UI to show."""
    out: dict[str, list[str]] = {}
    for sub in ALLOWED_FOLDERS:
        d = MEDIA_DIR / sub
        if d.is_dir():
            out[sub] = sorted(p.name for p in d.iterdir() if p.is_file())
        else:
            out[sub] = []
    return out

@app.get("/press/{button_name}")
async def press_button(button_name: str):
    if not _bb_app:
        return {"error": "App not initialized"}
    
    try:
        btn = Button(button_name.upper())
        # Inject press and release immediately for remote clicks
        _bb_app.bus.put(ButtonEvent(btn, pressed=True))
        await asyncio.sleep(0.05)
        _bb_app.bus.put(ButtonEvent(btn, pressed=False))
        return {"status": "ok", "button": button_name}
    except ValueError:
        return {"error": "Invalid button"}

async def frame_generator():
    import time as _time
    while True:
        if _bb_app:
            # Tell the main loop "yes, somebody is watching" so it keeps
            # encoding. Bumped per-iteration so the encode gate stays
            # open as long as a client keeps the connection.
            _bb_app.last_web_view_request = _time.time()
            if _bb_app.last_frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + _bb_app.last_frame + b'\r\n')
        await asyncio.sleep(0.1) # 10 FPS mirror is plenty for remote

@app.get("/video_feed")
async def video_feed():
    # Bump immediately so the first frame request kicks off encoding
    # even before frame_generator's first iteration.
    if _bb_app:
        import time as _time
        _bb_app.last_web_view_request = _time.time()
    return StreamingResponse(frame_generator(), media_type="multipart/x-mixed-replace; boundary=frame")


# ---------------- Wardrive / WiGLE -----------------------------------------

WARDRIVE_DIR = Path("loot/wardrive")


@app.get("/wigle/status")
async def wigle_status():
    creds = wigle_mod.load_creds()
    if not creds:
        return {"logged_in": False}
    return {"logged_in": True, "api_name": creds.api_name}


@app.post("/wigle/login")
async def wigle_login(api_name: str = Form(...), api_token: str = Form(...)):
    api_name = api_name.strip()
    api_token = api_token.strip()
    if not api_name or not api_token:
        raise HTTPException(status_code=400, detail="api_name and api_token required")
    creds = wigle_mod.WigleCreds(api_name=api_name, api_token=api_token)
    ok, msg = wigle_mod.validate_creds(creds)
    if not ok:
        raise HTTPException(status_code=401, detail=msg)
    try:
        wigle_mod.save_creds(creds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"could not persist creds: {e}")
    return {"logged_in": True, "api_name": api_name, "message": msg}


@app.post("/wigle/logout")
async def wigle_logout():
    wigle_mod.clear_creds()
    return {"logged_in": False}


@app.get("/wardrive/files")
async def wardrive_files():
    if not WARDRIVE_DIR.is_dir():
        return {"files": []}
    items = []
    for p in sorted(WARDRIVE_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file() and p.suffix in (".csv", ".gz"):
            items.append({
                "name": p.name,
                "size": p.stat().st_size,
                "mtime": int(p.stat().st_mtime),
            })
    return {"files": items}


@app.post("/wardrive/upload/{name}")
async def wardrive_upload(name: str):
    safe = os.path.basename(name)
    target = WARDRIVE_DIR / safe
    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    creds = wigle_mod.load_creds()
    if not creds:
        raise HTTPException(status_code=401, detail="not signed in to WiGLE")
    ok, msg = wigle_mod.upload(target, creds)
    if not ok:
        raise HTTPException(status_code=502, detail=msg)
    return {"status": "uploaded", "message": msg, "filename": safe}


# ---------------- Games / ROMs ---------------------------------------------

@app.get("/roms")
async def list_roms():
    """Quick listing of what's in each folder, for the web UI to show."""
    return emu_mod.list_all_roms()


@app.post("/roms/upload")
async def roms_upload(
    file: UploadFile = File(...),
    system: str = Form(...),
):
    if system not in emu_mod.WEB_SYSTEMS:
        raise HTTPException(
            status_code=400,
            detail=f"system must be one of {emu_mod.WEB_SYSTEMS}",
        )
    target_dir = emu_mod.upload_target_dir(system)
    if target_dir is None:
        raise HTTPException(status_code=400, detail="invalid system")
    safe_name = os.path.basename(file.filename or "")
    if not safe_name:
        raise HTTPException(status_code=400, detail="missing filename")

    allowed = emu_mod.allowed_extensions(system)
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"{safe_name!r} has extension {ext or '(none)'}; "
                   f"{system} accepts {', '.join(allowed)}",
        )

    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / safe_name
    try:
        with file_path.open("wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                buffer.write(chunk)
    except Exception as e:
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(status_code=500, detail=f"write failed: {e}")
    finally:
        await file.close()

    if _bb_app and getattr(_bb_app, "games_view", None):
        try:
            _bb_app.games_view.refresh()
        except Exception as e:
            print(f"[web] games refresh failed: {e}")

    return {"status": "uploaded", "system": system, "filename": safe_name}


@app.delete("/roms/{system}/{name}")
async def roms_delete(system: str, name: str):
    target_dir = emu_mod.upload_target_dir(system)
    if target_dir is None:
        raise HTTPException(status_code=400, detail="invalid system")
    safe = os.path.basename(name)
    target = target_dir / safe
    if not target.is_file():
        raise HTTPException(status_code=404, detail="rom not found")
    try:
        target.unlink()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"delete failed: {e}")
    if _bb_app and getattr(_bb_app, "games_view", None):
        try:
            _bb_app.games_view.refresh()
        except Exception:
            pass
    return {"status": "deleted", "system": system, "filename": safe}


# ---------------- BoxShop --------------------------------------------------

@app.get("/shop")
async def shop_list():
    """Cached catalog + per-item installed flag."""
    items = []
    for it in shop_mod.list_items():
        entry = dict(it)
        entry["installed"] = shop_mod.is_installed(it["id"])
        items.append(entry)
    return {"items": items}


@app.post("/shop/refresh")
async def shop_refresh():
    ok, msg = shop_mod.refresh()
    if not ok:
        raise HTTPException(status_code=502, detail=msg)
    return {"status": "ok", "message": msg}


@app.post("/shop/install/{item_id}")
async def shop_install(item_id: str):
    ok, msg = shop_mod.install(item_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "installed", "message": msg}


@app.delete("/shop/install/{item_id}")
async def shop_uninstall(item_id: str):
    ok, msg = shop_mod.uninstall(item_id)
    if not ok:
        raise HTTPException(status_code=404, detail=msg)
    return {"status": "removed", "message": msg}


# ---------------- RetroAchievements ----------------------------------------

@app.get("/retroachievements/status")
async def ra_status():
    creds = ra_mod.load_creds()
    if not creds:
        return {"logged_in": False}
    return {"logged_in": True, "username": creds.username}


@app.post("/retroachievements/login")
async def ra_login(username: str = Form(...), password: str = Form(...)):
    username = username.strip()
    if not username or not password:
        raise HTTPException(status_code=400,
                            detail="username and password required")
    ok, msg, creds = ra_mod.login(username, password)
    if not ok or not creds:
        raise HTTPException(status_code=401, detail=msg)
    try:
        ra_mod.save_creds(creds)
        ra_mod.apply_to_mgba_config(creds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"persist failed: {e}")
    return {"logged_in": True, "username": creds.username, "message": msg}


@app.post("/retroachievements/logout")
async def ra_logout():
    ra_mod.clear_creds()
    try:
        ra_mod.remove_from_mgba_config()
    except Exception:
        pass
    return {"logged_in": False}


# ---------------- Webhook --------------------------------------------------

@app.get("/webhook/status")
async def webhook_status():
    url = webhook_mod.load_webhook_url()
    return {"url": url or ""}


@app.post("/webhook/save")
async def webhook_save(url: str = Form(...)):
    url = url.strip()
    try:
        webhook_mod.save_webhook_url(url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"could not save webhook: {e}")
    return {"status": "ok", "url": url}


# ---------------- External GPS ---------------------------------------------

@app.post("/gps/phone")
async def gps_phone(
    lat: float = Form(...),
    lon: float = Form(...),
    alt: float = Form(0.0),
    hdop: float = Form(1.0),
):
    """Receive GPS fix from a phone browser."""
    GPSReader.inject_external_fix(lat, lon, alt, hdop)
    return {"status": "ok"}


@app.get("/gps/link", response_class=HTMLResponse)
async def gps_link(request: Request):
    """Page for the phone to open to share its GPS."""
    return templates.TemplateResponse(request, "gps_link.html")
