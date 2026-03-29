“””
TELE-TRACE Intelligence — Telegram OSINT Tool v2.1 (Patched)
Author: @anubhavanonymous
Contributor: @xPloits3c
Patches: See IMPROVEMENTS.md for full rationale behind each change.

Changes applied:
[1.1] SSL verification re-enabled
[1.2] Timeout on run_async()
[1.3] Bare except:pass eliminated, structured logging added
[1.4] Input validation on API endpoints
[1.5] Basic rate limiting
[2.1] _scan / _scan_username duplication eliminated via shared helpers
[2.2] Threading lock on global state
[2.3] Centralized SangMata parsing
[3.1] Configuration via environment variables
[3.2] Health check endpoint
[3.3] Graceful shutdown
[3.4] MIME detection fix
[3.5] Structured logging replaces print()
“””

import os
import asyncio
import base64
import hashlib
import json
import threading
import re
import ssl
import signal
import time
import logging
import urllib.request
import urllib.parse
import concurrent.futures
import random
import secrets
from datetime import datetime, timezone
from collections import defaultdict
from functools import wraps

from flask import Flask, request, jsonify, render_template
from telethon.errors import SessionPasswordNeededError

# ══════════════════════════════════════════════════════════════════════════════

# [3.5] STRUCTURED LOGGING

# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
level=logging.INFO,
format=”%(asctime)s [%(levelname)s] %(name)s — %(message)s”,
datefmt=”%H:%M:%S”,
)
logger = logging.getLogger(“tele-trace”)

# ══════════════════════════════════════════════════════════════════════════════

# [3.1] CONFIGURATION VIA ENVIRONMENT VARIABLES

# ══════════════════════════════════════════════════════════════════════════════

CONFIG = {
“HOST”:              os.environ.get(“TELETRACE_HOST”, “0.0.0.0”),
“PORT”:              int(os.environ.get(“TELETRACE_PORT”, “7777”)),
“DEBUG”:             os.environ.get(“TELETRACE_DEBUG”, “false”).lower() == “true”,
“ASYNC_TIMEOUT”:     int(os.environ.get(“TELETRACE_TIMEOUT”, “120”)),
“RATE_LIMIT_MAX”:    int(os.environ.get(“TELETRACE_RATE_MAX”, “5”)),
“RATE_LIMIT_WINDOW”: int(os.environ.get(“TELETRACE_RATE_WINDOW”, “60”)),
}

# ══════════════════════════════════════════════════════════════════════════════

# FLASK APP SETUP

# ══════════════════════════════════════════════════════════════════════════════

app = Flask(
**name**,
template_folder=os.path.join(os.path.dirname(os.path.abspath(**file**)), “templates”),
static_folder=os.path.join(os.path.dirname(os.path.abspath(**file**)), “static”),
)
app.secret_key = secrets.token_hex(32)

BASE_DIR      = os.path.dirname(os.path.abspath(**file**))
SESSION_FILE  = os.path.join(BASE_DIR, “tg_osint.session”)
CONFIG_FILE   = os.path.join(BASE_DIR, “tg_config.json”)

# ══════════════════════════════════════════════════════════════════════════════

# ASYNC EVENT LOOP (background thread)

# ══════════════════════════════════════════════════════════════════════════════

_loop = asyncio.new_event_loop()

def _run_loop():
asyncio.set_event_loop(_loop)
_loop.run_forever()

threading.Thread(target=_run_loop, daemon=True).start()

# [1.2] TIMEOUT ON run_async()

def run_async(coro, timeout=None):
“”“Run a coroutine in the async event loop with a safety timeout.”””
if timeout is None:
timeout = CONFIG[“ASYNC_TIMEOUT”]
future = asyncio.run_coroutine_threadsafe(coro, _loop)
try:
return future.result(timeout=timeout)
except asyncio.TimeoutError:
future.cancel()
raise TimeoutError(
f”Operation timed out after {timeout}s. “
“The Telegram server may be slow or unresponsive.”
)

# ══════════════════════════════════════════════════════════════════════════════

# [2.2] GLOBAL STATE WITH THREADING LOCK

# ══════════════════════════════════════════════════════════════════════════════

_state_lock = threading.Lock()
_state = {“client”: None, “phone_code_hash”: None, “login_phone”: None}

# ══════════════════════════════════════════════════════════════════════════════

# [1.5] RATE LIMITER

# ══════════════════════════════════════════════════════════════════════════════

class SimpleRateLimiter:
“”“In-memory per-IP rate limiter.”””

```
def __init__(self, max_requests=10, window_seconds=60):
    self.max_requests = max_requests
    self.window = window_seconds
    self._requests: dict[str, list[float]] = defaultdict(list)

def is_allowed(self, key: str) -> bool:
    now = time.time()
    self._requests[key] = [
        t for t in self._requests[key] if now - t < self.window
    ]
    if len(self._requests[key]) >= self.max_requests:
        return False
    self._requests[key].append(now)
    return True
```

rate_limiter = SimpleRateLimiter(
max_requests=CONFIG[“RATE_LIMIT_MAX”],
window_seconds=CONFIG[“RATE_LIMIT_WINDOW”],
)

def rate_limited(f):
“”“Decorator — reject requests that exceed the rate limit.”””
@wraps(f)
def decorated(*args, **kwargs):
client_ip = request.remote_addr or “unknown”
if not rate_limiter.is_allowed(client_ip):
return jsonify({“error”: “Rate limit exceeded. Try again in a minute.”}), 429
return f(*args, **kwargs)
return decorated

# ══════════════════════════════════════════════════════════════════════════════

# [1.4] INPUT VALIDATION

# ══════════════════════════════════════════════════════════════════════════════

def validate_phone(phone: str) -> str:
“”“Validate and normalize a phone number.”””
cleaned = re.sub(r”[\s-()]”, “”, phone)
if not re.match(r”^+?[1-9]\d{6,14}$”, cleaned):
raise ValueError(“Invalid phone number format”)
return cleaned

def validate_username(username: str) -> str:
“”“Validate a Telegram / social username.”””
cleaned = username.strip().lstrip(”@”)
if not re.match(r”^[a-zA-Z0-9_.]{1,64}$”, cleaned):
raise ValueError(“Invalid username format”)
return cleaned

# ══════════════════════════════════════════════════════════════════════════════

# CONFIG PERSISTENCE

# ══════════════════════════════════════════════════════════════════════════════

def load_config():
if os.path.exists(CONFIG_FILE):
with open(CONFIG_FILE) as f:
return json.load(f)
return None

def save_config(api_id, api_hash):
with open(CONFIG_FILE, “w”) as f:
json.dump({“api_id”: api_id, “api_hash”: api_hash}, f)

# ══════════════════════════════════════════════════════════════════════════════

# [3.4] MIME DETECTION (fixed magic-byte offsets)

# ══════════════════════════════════════════════════════════════════════════════

def detect_mime(raw: bytes) -> str:
“”“Detect MIME type from magic bytes.”””
if len(raw) < 12:
return “image/jpeg”
if raw[:8] == b”\x89PNG\r\n\x1a\n”:
return “image/png”
if raw[:4] == b”RIFF” and raw[8:12] == b”WEBP”:
return “image/webp”
if raw[:2] == b”\xff\xd8”:
return “image/jpeg”
if raw[:4] == b”GIF8”:
return “image/gif”
return “image/jpeg”  # fallback

# ══════════════════════════════════════════════════════════════════════════════

# ACCOUNT AGE ESTIMATION

# ══════════════════════════════════════════════════════════════════════════════

def estimate_account_age(user_id: int) -> dict:
“””
Estimate Telegram account creation date from user_id.
Telegram IDs are roughly sequential with known reference points.
“””
milestones = [
(100_000_000,  “2013-08”),
(200_000_000,  “2014-06”),
(300_000_000,  “2015-06”),
(400_000_000,  “2016-06”),
(500_000_000,  “2017-06”),
(600_000_000,  “2018-01”),
(700_000_000,  “2018-08”),
(800_000_000,  “2019-01”),
(900_000_000,  “2019-06”),
(1_000_000_000, “2019-11”),
(1_100_000_000, “2020-03”),
(1_200_000_000, “2020-06”),
(1_300_000_000, “2020-09”),
(1_400_000_000, “2020-12”),
(1_500_000_000, “2021-03”),
(1_600_000_000, “2021-05”),
(1_700_000_000, “2021-08”),
(1_800_000_000, “2021-11”),
(1_900_000_000, “2022-01”),
(2_000_000_000, “2022-03”),
(2_100_000_000, “2022-06”),
(2_500_000_000, “2022-10”),
(3_000_000_000, “2023-02”),
(4_000_000_000, “2023-08”),
(5_000_000_000, “2024-01”),
(6_000_000_000, “2024-06”),
(7_000_000_000, “2024-11”),
]

```
lower_date = "2013-08"
upper_date = datetime.now(timezone.utc).strftime("%Y-%m")
for i, (mid, date) in enumerate(milestones):
    if user_id < mid:
        lower_date = milestones[i - 1][1] if i > 0 else "2013-08"
        upper_date = date
        break

def fmt(ym):
    try:
        return datetime.strptime(ym, "%Y-%m").strftime("%b %Y")
    except ValueError:
        return ym

try:
    ref_dt = datetime.strptime(lower_date, "%Y-%m").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    months = (now.year - ref_dt.year) * 12 + (now.month - ref_dt.month)
    years, rem = divmod(months, 12)
    if years > 0:
        age_str = f"~{years}y {rem}m old" if rem else f"~{years}y old"
    else:
        age_str = f"~{rem} months old"
except ValueError:
    age_str = "Unknown"

return {"range": f"{fmt(lower_date)} – {fmt(upper_date)}", "age": age_str, "user_id": user_id}
```

# ══════════════════════════════════════════════════════════════════════════════

# AUTH COROUTINES  [2.2] with lock

# ══════════════════════════════════════════════════════════════════════════════

async def _make_client(api_id, api_hash):
from telethon import TelegramClient

```
with _state_lock:
    if _state["client"]:
        try:
            await _state["client"].disconnect()
        except Exception as e:
            logger.debug("Disconnect old client: %s", e)
    _state["client"] = TelegramClient(SESSION_FILE, api_id, api_hash)
```

async def _check_auth():
c = _state[“client”]
if c is None:
return False
await c.connect()
return await c.is_user_authorized()

async def _restore_client():
cfg = load_config()
if cfg and _state[“client”] is None:
await _make_client(int(cfg[“api_id”]), cfg[“api_hash”])

async def _send_code(phone):
c = _state[“client”]
await c.connect()
result = await c.send_code_request(phone)
with _state_lock:
_state[“phone_code_hash”] = result.phone_code_hash
_state[“login_phone”] = phone

async def _verify_code(code, password=None):
c = _state[“client”]
await c.connect()
phone = _state[“login_phone”]
phash = _state[“phone_code_hash”]
if password:
await c.sign_in(password=password)
else:
await c.sign_in(phone, code, phone_code_hash=phash)
me = await c.get_me()
return me.first_name or me.username or “User”

async def _logout():
with _state_lock:
if _state[“client”]:
try:
await _state[“client”].disconnect()
except Exception as e:
logger.debug(“Logout disconnect: %s”, e)
_state[“client”] = None
_state[“phone_code_hash”] = None
_state[“login_phone”] = None

# ══════════════════════════════════════════════════════════════════════════════

# [2.3] CENTRALIZED SANGMATA PARSING

# ══════════════════════════════════════════════════════════════════════════════

def _parse_sangmata_response(text: str) -> dict:
“”“Centralized parsing of @SangMata_BOT responses.”””
result = {“names”: [], “usernames”: [], “error”: None, “quota_error”: None}

```
if not text:
    result["error"] = "Bot did not respond"
    return result

text_lower = text.lower()
if "quota" in text_lower or "sorry" in text_lower:
    time_match = re.search(
        r"(\d+\s*hours?\s*\d*\s*minutes?|\d+\s*minutes?)", text, re.IGNORECASE
    )
    result["quota_error"] = time_match.group(0) if time_match else None
    result["error"] = "quota_exceeded"
    return result

lines = text.split("\n")
current_section = None
section_lines: dict[str, list[str]] = {"names": [], "usernames": []}

for line in lines:
    stripped = line.strip()
    if re.match(r"^\*{0,2}Names?\*{0,2}$", stripped, re.IGNORECASE):
        current_section = "names"
    elif re.match(r"^\*{0,2}Usernames?\*{0,2}$", stripped, re.IGNORECASE):
        current_section = "usernames"
    elif current_section:
        section_lines[current_section].append(line)

for key, block in section_lines.items():
    for line in block:
        match = re.search(r"`?[0-9]*[.]?\s*\[([0-9/\-\.:\s]+)\]`?\s*(.*)", line.strip())
        if match:
            value = match.group(2).strip().lstrip("`").strip()
            if value and value.lower() not in ("(empty)", "empty"):
                result[key].append({"date": match.group(1).strip(), "value": value})

if not result["names"] and not result["usernames"]:
    result["error"] = "No history recorded"

return result
```

# ══════════════════════════════════════════════════════════════════════════════

# [2.1] SHARED PROFILE-EXTRACTION HELPERS

# ══════════════════════════════════════════════════════════════════════════════

def _get_user_from_full(full):
“”“Extract the user object from a GetFullUserRequest result.”””
if hasattr(full, “user”) and full.user:
return full.user
if hasattr(full, “users”) and full.users:
return full.users[0]
return None

def _parse_status(uobj):
“”“Parse user online status.”””
from telethon.tl.types import (
UserStatusOnline, UserStatusRecently,
UserStatusLastWeek, UserStatusLastMonth, UserStatusOffline,
)
try:
st = uobj.status
if isinstance(st, UserStatusOnline):
return “Online now”, “online”
elif isinstance(st, UserStatusRecently):
return “Last seen recently”, “recently”
elif isinstance(st, UserStatusLastWeek):
return “Last seen within a week”, “week”
elif isinstance(st, UserStatusLastMonth):
return “Last seen within a month”, “month”
elif isinstance(st, UserStatusOffline):
return f”Last seen {st.was_online.strftime(’%d %b %Y, %H:%M’)}”, “offline”
except (AttributeError, TypeError):
pass
return “Hidden”, “hidden”

def _extract_extra_fields(full) -> dict:
“”“Extract extra fields from UserFull.”””
extra = {}
try:
fu = getattr(full, “full_user”, full)
extra[“blocked”]                  = getattr(fu, “blocked”, False) or False
extra[“phone_calls_available”]    = getattr(fu, “phone_calls_available”, None)
extra[“phone_calls_private”]      = getattr(fu, “phone_calls_private”, None)
extra[“voice_messages_forbidden”] = getattr(fu, “voice_messages_forbidden”, None)
extra[“contact_require_premium”]  = getattr(fu, “contact_require_premium”, None)
extra[“read_dates_private”]       = getattr(fu, “read_dates_private”, None)
extra[“common_chats_count”]       = getattr(fu, “common_chats_count”, None)
extra[“stories_pinned_available”] = getattr(fu, “stories_pinned_available”, None)
extra[“has_scheduled”]            = getattr(fu, “has_scheduled”, None)

```
    ttl = getattr(fu, "ttl_period", None)
    if ttl:
        if ttl <= 86400:
            extra["ttl_period"] = "1 day"
        elif ttl <= 604800:
            extra["ttl_period"] = "1 week"
        elif ttl <= 2678400:
            extra["ttl_period"] = "1 month"
        else:
            extra["ttl_period"] = f"{ttl}s"
    else:
        extra["ttl_period"] = None

    extra["theme_emoticon"]       = getattr(fu, "theme_emoticon", None)
    extra["private_forward_name"] = getattr(fu, "private_forward_name", None)
except Exception as e:
    logger.warning("Extra fields extraction error: %s", e)
return extra
```

def _extract_usernames(uobj) -> list[str]:
“”“Extract all usernames (Telegram supports multiple).”””
try:
if hasattr(uobj, “usernames”) and uobj.usernames:
return [u.username for u in uobj.usernames if u.username]
except (AttributeError, TypeError):
pass
username = getattr(uobj, “username”, None)
return [username] if username else []

def _extract_emoji_status(uobj):
“”“Extract emoji status document ID if present.”””
try:
es = getattr(uobj, “emoji_status”, None)
if es and hasattr(es, “document_id”):
return str(es.document_id)
except (AttributeError, TypeError):
pass
return None

def _fmt_photo_date(ph_obj):
“”“Extract and format the date from a Photo object.”””
try:
ts = getattr(ph_obj, “date”, None)
if ts:
if hasattr(ts, “strftime”):
return ts.strftime(”%d %b %Y”)
return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime(”%d %b %Y”)
except (ValueError, TypeError, OSError):
pass
return None

async def _send_history_request(c, user_id: int):
“”“Send user_id to @SangMata_BOT; returns (bot_entity, last_msg_id).”””
try:
bot = await c.get_entity(“SangMata_BOT”)
old_msgs = await c.get_messages(bot, limit=1)
last_id = old_msgs[0].id if old_msgs else 0
await c.send_message(bot, str(user_id))
logger.info(“Sent user_id %d to SangMata_BOT (last_id=%d)”, user_id, last_id)
return bot, last_id
except Exception as e:
logger.warning(“SangMata send error: %s”, e)
return None, 0

async def _collect_history_response(c, bot, last_id: int, user_id: int) -> dict:
“”“Poll for @SangMata_BOT response and parse it.”””
if bot is None:
return {“names”: [], “usernames”: [], “error”: “Bot unavailable”, “quota_error”: None}

```
response_text = None
try:
    for attempt in range(8):
        await asyncio.sleep(1)
        new_msgs = await c.get_messages(bot, limit=5)
        for msg in new_msgs:
            if msg.id <= last_id:
                break
            if not msg.out and msg.text:
                response_text = msg.text
                logger.info("History response received at attempt %d", attempt + 1)
                break
        if response_text:
            break

    # Fallback: scan last 20 messages
    if not response_text:
        all_msgs = await c.get_messages(bot, limit=20)
        for msg in all_msgs:
            if not msg.out and msg.text and str(user_id) in msg.text:
                response_text = msg.text
                logger.info("History response found via fallback")
                break
except Exception as e:
    logger.warning("History collection error: %s", e)
    return {"names": [], "usernames": [], "error": str(e), "quota_error": None}

return _parse_sangmata_response(response_text)
```

async def _download_all_media(c, uobj, user_id: int, access_hash: int) -> list[dict]:
“”“Download all profile photos and videos, return list of media dicts.”””
from telethon.tl.types import InputPeerUser
from telethon.tl.functions.photos import GetUserPhotosRequest

```
all_photo_objs = []
try:
    pr = await c(GetUserPhotosRequest(
        user_id=InputPeerUser(user_id, access_hash),
        offset=0, max_id=0, limit=100,
    ))
    all_photo_objs = pr.photos or []
except Exception as e:
    logger.warning("Photos fetch error: %s", e)

videos = []
static_photo_objs = []

for ph_obj in all_photo_objs:
    has_vid = hasattr(ph_obj, "video_sizes") and ph_obj.video_sizes
    if has_vid:
        best_vs = None
        for vs in ph_obj.video_sizes:
            if getattr(vs, "type", "") in ("u", "v"):
                best_vs = vs
                break
        if best_vs is None:
            best_vs = ph_obj.video_sizes[-1]
        try:
            raw = await c.download_media(ph_obj, file=bytes, thumb=best_vs)
            if raw and len(raw) > 500:
                videos.append({
                    "type": "video",
                    "data": base64.b64encode(raw).decode(),
                    "mime": "video/mp4",
                    "date": _fmt_photo_date(ph_obj),
                })
            else:
                static_photo_objs.append(ph_obj)
        except Exception as e:
            logger.debug("Video download failed: %s", e)
            static_photo_objs.append(ph_obj)
    else:
        static_photo_objs.append(ph_obj)

static = []
seen_hashes: set[str] = set()

for p in static_photo_objs:
    try:
        raw = await c.download_media(p, file=bytes)
        if not raw or len(raw) < 500:
            continue
        mime = detect_mime(raw)
        h = hashlib.sha256(raw).hexdigest()
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        static.append({
            "type": "photo",
            "data": base64.b64encode(raw).decode(),
            "mime": mime,
            "date": _fmt_photo_date(p),
        })
    except Exception as e:
        logger.debug("Photo download failed: %s", e)
        continue

# Fallback: download current profile photo if nothing else found
if not static and not videos and uobj:
    try:
        raw = await c.download_profile_photo(uobj, file=bytes, download_big=True)
        if raw and len(raw) > 500:
            static.append({
                "type": "photo",
                "data": base64.b64encode(raw).decode(),
                "mime": detect_mime(raw),
                "date": None,
            })
    except Exception as e:
        logger.debug("Profile photo fallback failed: %s", e)

return videos + static
```

async def _extract_profile(c, uobj, full, user_id: int, access_hash: int) -> dict:
“”“Extract full profile — shared logic for phone and username scans.”””

```
# Name
name = "Name not visible"
try:
    parts = [p for p in [uobj.first_name, uobj.last_name] if p]
    if parts:
        name = " ".join(parts)
except (AttributeError, TypeError):
    pass

# Bio
bio = "Not visible"
try:
    fu_obj = getattr(full, "full_user", full)
    about = getattr(fu_obj, "about", None)
    if about:
        bio = about
except (AttributeError, TypeError):
    pass

status, status_class = _parse_status(uobj)
flags = {
    "is_bot":      getattr(uobj, "bot", False) or False,
    "is_fake":     getattr(uobj, "fake", False) or False,
    "is_scam":     getattr(uobj, "scam", False) or False,
    "is_premium":  getattr(uobj, "premium", False) or False,
    "is_verified": getattr(uobj, "verified", False) or False,
}
extra          = _extract_extra_fields(full)
all_usernames  = _extract_usernames(uobj)
emoji_status   = _extract_emoji_status(uobj)
age_info       = estimate_account_age(user_id)

# Fire history request BEFORE photo downloads (parallel work)
hist_bot, hist_last_id = await _send_history_request(c, user_id)

# Download photos & videos (bot responds in parallel)
media = await _download_all_media(c, uobj, user_id, access_hash)

# Collect bot response
history = await _collect_history_response(c, hist_bot, hist_last_id, user_id)

scan_time = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")

return {
    "user_id":       user_id,
    "username":      getattr(uobj, "username", None) or "No username",
    "all_usernames": all_usernames,
    "name":          name,
    "bio":           bio,
    "status":        status,
    "status_class":  status_class,
    "flags":         flags,
    "extra":         extra,
    "emoji_status":  emoji_status,
    "age_info":      age_info,
    "history":       history,
    "scan_time":     scan_time,
    "media_count":   len(media),
    "media":         media,
}
```

# ══════════════════════════════════════════════════════════════════════════════

# [2.1] LEAN SCAN FUNCTIONS (phone & username)

# ══════════════════════════════════════════════════════════════════════════════

async def _scan(phone: str):
“”“Scan by phone number.”””
from telethon.tl.types import InputPhoneContact, InputPeerUser
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.functions.users import GetFullUserRequest

```
c = _state["client"]
await c.connect()

temp = InputPhoneContact(0, phone, "Tmp", "Lookup")
result = await c(ImportContactsRequest([temp]))
if not result.users:
    return {"error": "No Telegram account found for this number"}

user = result.users[0]
try:
    await c(DeleteContactsRequest([user.id]))
except Exception as e:
    logger.warning("Failed to delete temp contact %d: %s", user.id, e)

peer = InputPeerUser(user.id, user.access_hash)
full = await c(GetFullUserRequest(peer))
uobj = _get_user_from_full(full)

profile = await _extract_profile(c, uobj, full, user.id, user.access_hash)
profile["phone"] = phone
return profile
```

async def _scan_username(username: str):
“”“Scan by username.”””
from telethon.tl.types import InputPeerUser
from telethon.tl.functions.users import GetFullUserRequest

```
c = _state["client"]
await c.connect()

try:
    entity = await c.get_entity(username)
except Exception as e:
    return {"error": f"Username not found: {e}"}

peer = InputPeerUser(entity.id, entity.access_hash)
full = await c(GetFullUserRequest(peer))
uobj = _get_user_from_full(full)

profile = await _extract_profile(c, uobj, full, entity.id, entity.access_hash)
profile["phone"] = "Not available (username lookup)"
return profile
```

# ══════════════════════════════════════════════════════════════════════════════

# SANGMATA STANDALONE ENDPOINT (kept for backward compatibility)

# ══════════════════════════════════════════════════════════════════════════════

async def _get_history(user_id: int) -> dict:
“”“Send user_id to @SangMata_BOT and parse response (standalone).”””
c = _state[“client”]
await c.connect()

```
try:
    bot = await c.get_entity("SangMata_BOT")
    old_msgs = await c.get_messages(bot, limit=1)
    last_id = old_msgs[0].id if old_msgs else 0
    logger.info("History standalone: sending %d (last_id=%d)", user_id, last_id)

    await c.send_message(bot, str(user_id))

    response_text = None
    for attempt in range(15):
        await asyncio.sleep(1)
        new_msgs = await c.get_messages(bot, limit=5)
        for msg in new_msgs:
            if msg.id <= last_id:
                break
            if not msg.out and msg.text:
                response_text = msg.text
                logger.info("History standalone: response at attempt %d", attempt + 1)
                break
        if response_text:
            break

    # Fallback
    if not response_text:
        all_msgs = await c.get_messages(bot, limit=20)
        for msg in all_msgs:
            if not msg.out and msg.text and str(user_id) in msg.text:
                response_text = msg.text
                logger.info("History standalone: found via fallback")
                break

    return _parse_sangmata_response(response_text)

except Exception as e:
    logger.error("History standalone error: %s", e)
    return {"names": [], "usernames": [], "error": str(e), "quota_error": None}
```

# ══════════════════════════════════════════════════════════════════════════════

# [1.1] HTTP HELPERS — SSL VERIFICATION RE-ENABLED

# ══════════════════════════════════════════════════════════════════════════════

_USER_AGENTS = [
“Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Mobile Safari/537.36”,
“Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36”,
“Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36”,
“Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36”,
]

def _random_ua():
return random.choice(_USER_AGENTS)

def _http_get(url, headers=None, follow_redirects=True, timeout=8):
“”“GET request with SSL verification ENABLED.”””
try:
ctx = ssl.create_default_context()  # [1.1] verification on
req = urllib.request.Request(url, headers=headers or {})
with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
return r.status, r.read().decode(“utf-8”, errors=“replace”)
except urllib.error.HTTPError as e:
return e.code, “”
except ssl.SSLCertVerificationError:
logger.warning(”[SSL] Certificate verification failed for %s”, url)
return None, None
except Exception:
return None, None

def _http_post_json(url, data, headers=None, timeout=6):
“”“POST JSON with SSL verification ENABLED.”””
try:
ctx = ssl.create_default_context()  # [1.1] verification on
body = json.dumps(data).encode(“utf-8”)
h = {“Content-Type”: “application/json”, **(headers or {})}
req = urllib.request.Request(url, data=body, headers=h, method=“POST”)
with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
return r.status, r.read().decode(“utf-8”, errors=“replace”)
except urllib.error.HTTPError as e:
try:
return e.code, e.read().decode(“utf-8”, errors=“replace”)
except Exception:
return e.code, “”
except ssl.SSLCertVerificationError:
logger.warning(”[SSL] Certificate verification failed for %s”, url)
return None, None
except Exception:
return None, None

# ══════════════════════════════════════════════════════════════════════════════

# CROSS-PLATFORM USERNAME CHECKERS

# ══════════════════════════════════════════════════════════════════════════════

def check_github(user):
api_url = f”https://github.com/signup_check/username?value={user}”
api_headers = {
“User-Agent”: _random_ua(),
“referer”: “https://github.com/signup?source=form-home-signup”,
“accept-language”: “en-US,en;q=0.9”,
“sec-fetch-site”: “same-origin”,
“sec-fetch-mode”: “cors”,
“x-requested-with”: “XMLHttpRequest”,
}
status, text = _http_get(api_url, headers=api_headers)
if status == 200:
return “available”
if status == 422:
if “cannot begin or end with a hyphen” in (text or “”).lower():
return “invalid”
return “found”
profile_url = f”https://github.com/{user}”
status2, text2 = _http_get(profile_url, headers={“User-Agent”: _random_ua()})
if status2 == 200:
if “Not Found” in (text2 or “”) or f”/{user}” not in (text2 or “”):
return “available”
return “found”
if status2 == 404:
return “available”
return “error”

def check_reddit(user):
url = f”https://www.reddit.com/user/{user}/”
headers = {“User-Agent”: _random_ua(), “Accept-Language”: “en-US,en;q=0.9”}
status, text = _http_get(url, headers=headers)
if status == 200:
if “Sorry, nobody on Reddit goes by that name.” in (text or “”):
return “available”
return “found”
if status == 404:
return “available”
return “error”

def check_instagram(user):
api_url = “https://www.instagram.com/api/v1/users/web_profile_info/”
params = urllib.parse.urlencode({“username”: user})
api_headers = {
“User-Agent”: “Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Mobile Safari/537.36”,
“x-ig-app-id”: “936619743392459”,
“x-requested-with”: “XMLHttpRequest”,
“Accept”: “*/*”,
“sec-fetch-site”: “same-origin”,
“sec-fetch-mode”: “cors”,
“referer”: f”https://www.instagram.com/{user}/”,
“accept-language”: “en-US,en;q=0.9”,
}
status1, _ = _http_get(f”{api_url}?{params}”, headers=api_headers)
if status1 == 200:
return “found”
if status1 == 404:
return “available”
page_headers = {
“User-Agent”: “Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Mobile Safari/537.36”,
“Accept”: “text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8”,
“sec-fetch-dest”: “document”,
“sec-fetch-mode”: “navigate”,
}
status2, text2 = _http_get(f”https://www.instagram.com/{user}/”, headers=page_headers)
if status2 == 200:
t = (text2 or “”).lower()
if “page not found” in t or “sorry, this page” in t or “isn’t available” in t:
return “available”
return “found”
if status2 == 404:
return “available”
return “error”

def check_tiktok(user):
if not (2 <= len(user) <= 24):
return “invalid”
if user.isdigit():
return “invalid”
if not re.match(r”^[a-zA-Z0-9_.]+$”, user):
return “invalid”
if user.startswith(”.”) or user.endswith(”.”):
return “invalid”
url = f”https://www.tiktok.com/@{user}”
headers = {
“User-Agent”: _random_ua(),
“Accept”: “text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8”,
“Accept-Encoding”: “identity”,
“Accept-Language”: “en-US,en;q=0.9”,
“sec-fetch-dest”: “document”,
“sec-fetch-mode”: “navigate”,
}
status, text = _http_get(url, headers=headers, timeout=8)
if status == 200:
t = (text or “”).lower()
if ‘“statuscode”:10202’ in t or ‘statuscode":10202’ in t:
return “available”
if any(code in t for code in [’“statuscode”:10221’, ‘“statuscode”:10223’,
‘“statuscode”:10225’, ‘uniqueid’]):
return “found”
if “couldn’t find this account” in t or “this account doesn’t exist” in t:
return “available”
return “found”
if status == 404:
return “available”
return “error”

def check_snapchat(user):
url = f”https://www.snapchat.com/@{user}”
headers = {“User-Agent”: _random_ua(), “sec-fetch-dest”: “document”}
status, _ = _http_get(url, headers=headers)
if status == 200:
return “found”
if status == 404:
return “available”
return “error”

def check_pinterest(user):
url = f”https://www.pinterest.com/{user}/”
headers = {“User-Agent”: _random_ua()}
status, text = _http_get(url, headers=headers)
if status == 200:
if “User not found.” in (text or “”):
return “available”
return “found”
return “error”

def check_discord(user):
url = “https://discord.com/api/v9/unique-username/username-attempt-unauthed”
headers = {
“authority”: “discord.com”,
“content-type”: “application/json”,
“origin”: “https://discord.com”,
“referer”: “https://discord.com/register”,
“User-Agent”: _random_ua(),
}
status, text = _http_post_json(url, {“username”: user}, headers=headers)
if status == 200:
try:
taken = json.loads(text).get(“taken”)
if taken is True:
return “found”
if taken is False:
return “available”
except (json.JSONDecodeError, AttributeError):
pass
return “error”

def check_linkedin(user):
url = f”https://www.linkedin.com/in/{user}”
headers = {“User-Agent”: “Twitterbot/1.0”}
status, _ = _http_get(url, headers=headers, follow_redirects=False)
if status in (200, 301):
return “found”
if status == 404:
return “available”
return “error”

def check_medium(user):
url = f”https://medium.com/@{user}”
headers = {
“User-Agent”: _random_ua(),
“Accept”: “text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8”,
“Accept-Encoding”: “identity”,
“sec-fetch-dest”: “document”,
“sec-fetch-mode”: “navigate”,
}
status, text = _http_get(url, headers=headers)
if status == 404:
return “available”
if status == 200:
t = (text or “”).lower()
if “this page doesn” in t or “not found” in t or “404” in (text or “”)[:500]:
return “available”
return “found”
return “error”

PLATFORMS = [
{“id”: “github”,    “name”: “GitHub”,    “icon”: “🐙”, “url”: “https://github.com/{user}”,       “check”: check_github},
{“id”: “instagram”, “name”: “Instagram”, “icon”: “📸”, “url”: “https://instagram.com/{user}”,    “check”: check_instagram},
{“id”: “reddit”,    “name”: “Reddit”,    “icon”: “🤖”, “url”: “https://reddit.com/user/{user}”,  “check”: check_reddit},
{“id”: “tiktok”,    “name”: “TikTok”,    “icon”: “🎵”, “url”: “https://tiktok.com/@{user}”,      “check”: check_tiktok},
{“id”: “snapchat”,  “name”: “Snapchat”,  “icon”: “👻”, “url”: “https://snapchat.com/add/{user}”, “check”: check_snapchat},
{“id”: “pinterest”, “name”: “Pinterest”, “icon”: “📌”, “url”: “https://pinterest.com/{user}”,    “check”: check_pinterest},
{“id”: “discord”,   “name”: “Discord”,   “icon”: “💬”, “url”: “https://discord.com”,             “check”: check_discord},
{“id”: “linkedin”,  “name”: “LinkedIn”,  “icon”: “💼”, “url”: “https://linkedin.com/in/{user}”,  “check”: check_linkedin},
{“id”: “medium”,    “name”: “Medium”,    “icon”: “✍️”,  “url”: “https://medium.com/@{user}”,      “check”: check_medium},
]

def scan_platforms(username: str) -> list[dict]:
“”“Run all platform checks in parallel threads.”””
results = []

```
def run_check(p):
    try:
        status = p["check"](username)
    except Exception:
        status = "error"
    return {
        "id":     p["id"],
        "name":   p["name"],
        "icon":   p["icon"],
        "url":    p["url"].replace("{user}", urllib.parse.quote(username)),
        "status": status,
    }

with concurrent.futures.ThreadPoolExecutor(max_workers=9) as ex:
    futures = {ex.submit(run_check, p): p for p in PLATFORMS}
    for f in concurrent.futures.as_completed(futures):
        results.append(f.result())

results.sort(key=lambda x: x["name"])
return results
```

# ══════════════════════════════════════════════════════════════════════════════

# FLASK ROUTES

# ══════════════════════════════════════════════════════════════════════════════

@app.route(”/”)
def index():
return render_template(“index.html”)

# [3.2] HEALTH CHECK

@app.route(”/api/health”)
def health():
“”“Health check endpoint.”””
checks = {
“server”: “ok”,
“event_loop”: _loop.is_running(),
“client_initialized”: _state[“client”] is not None,
“session_file_exists”: os.path.exists(SESSION_FILE),
“config_file_exists”: os.path.exists(CONFIG_FILE),
}
try:
authorized = run_async(_check_auth(), timeout=10)
checks[“telegram_auth”] = authorized
except Exception:
checks[“telegram_auth”] = False

```
status_code = 200 if checks["server"] == "ok" else 503
return jsonify(checks), status_code
```

@app.route(”/api/status”)
def api_status():
run_async(_restore_client())
if _state[“client”] is None:
return jsonify({“status”: “no_config”})
try:
authorized = run_async(_check_auth())
return jsonify({“status”: “authorized” if authorized else “need_login”})
except Exception:
return jsonify({“status”: “need_login”})

@app.route(”/api/send_code”, methods=[“POST”])
def send_code():
data = request.json
api_id   = data.get(“api_id”, “”).strip()
api_hash = data.get(“api_hash”, “”).strip()
phone    = data.get(“phone”, “”).strip()
if not all([api_id, api_hash, phone]):
return jsonify({“error”: “Missing fields”}), 400
try:
api_id_int = int(api_id)
except ValueError:
return jsonify({“error”: “API ID must be a number”}), 400
try:
phone = validate_phone(phone)
except ValueError as e:
return jsonify({“error”: str(e)}), 400

```
save_config(api_id_int, api_hash)
try:
    run_async(_make_client(api_id_int, api_hash))
    run_async(_send_code(phone))
    return jsonify({"success": True})
except Exception as e:
    logger.error("send_code failed: %s", e, exc_info=True)
    return jsonify({"error": str(e)}), 500
```

@app.route(”/api/verify_code”, methods=[“POST”])
def verify_code():
data = request.json
code     = data.get(“code”, “”).strip()
password = (data.get(“password”) or “”).strip() or None
if not code:
return jsonify({“error”: “Missing code”}), 400
if _state[“client”] is None:
return jsonify({“error”: “Session expired”}), 400
try:
name = run_async(_verify_code(code, password))
return jsonify({“success”: True, “name”: name})
except SessionPasswordNeededError:
return jsonify({“error”: “2fa_required”}), 401
except Exception as e:
logger.error(“verify_code failed: %s”, e, exc_info=True)
return jsonify({“error”: str(e)}), 500

@app.route(”/api/logout”, methods=[“POST”])
def logout():
run_async(_logout())
for f in os.listdir(BASE_DIR):
if f.startswith(“tg_osint.session”):
try:
os.remove(os.path.join(BASE_DIR, f))
except OSError as e:
logger.warning(“Failed to remove session file %s: %s”, f, e)
if os.path.exists(CONFIG_FILE):
try:
os.remove(CONFIG_FILE)
except OSError as e:
logger.warning(“Failed to remove config file: %s”, e)
return jsonify({“success”: True})

@app.route(”/api/history”, methods=[“POST”])
def history():
user_id = (request.json or {}).get(“user_id”)
if not user_id:
return jsonify({“error”: “Missing user_id”}), 400
try:
result = run_async(_get_history(int(user_id)))
return jsonify(result)
except (ValueError, TypeError):
return jsonify({“error”: “user_id must be a number”}), 400
except TimeoutError as e:
return jsonify({“error”: str(e)}), 504
except Exception as e:
logger.error(“History failed: %s”, e, exc_info=True)
return jsonify({“error”: str(e)}), 500

@app.route(”/api/scan”, methods=[“POST”])
@rate_limited
def api_scan():
data = request.json or {}
phone    = data.get(“phone”, “”).strip()
username = data.get(“username”, “”).strip().lstrip(”@”)

```
if not phone and not username:
    return jsonify({"error": "Missing phone number or username"}), 400

try:
    if username:
        username = validate_username(username)
        result = run_async(_scan_username(username))
    else:
        phone = validate_phone(phone)
        result = run_async(_scan(phone))
    return jsonify(result)
except ValueError as e:
    return jsonify({"error": str(e)}), 400
except TimeoutError as e:
    return jsonify({"error": str(e)}), 504
except Exception as e:
    logger.error("Scan failed: %s", e, exc_info=True)
    return jsonify({"error": "Internal error during scan"}), 500
```

@app.route(”/api/platform_scan”, methods=[“POST”])
@rate_limited
def platform_scan():
username = (request.json or {}).get(“username”, “”).strip().lstrip(”@”)
if not username:
return jsonify({“error”: “Missing username”}), 400
try:
username = validate_username(username)
except ValueError as e:
return jsonify({“error”: str(e)}), 400

```
try:
    results = scan_platforms(username)
    found_count = sum(1 for r in results if r["status"] == "found")
    return jsonify({"username": username, "results": results, "found_count": found_count})
except Exception as e:
    logger.error("Platform scan failed: %s", e, exc_info=True)
    return jsonify({"error": str(e)}), 500
```

# ── IMAGE UPLOAD FOR REVERSE SEARCH ──

@app.route(”/api/upload_for_search”, methods=[“POST”])
@rate_limited
def upload_for_search():
“”“Upload image to catbox.moe and return public URL for reverse search.”””
data = request.json or {}
b64  = data.get(“b64”, “”)
mime = data.get(“mime”, “image/jpeg”)
if not b64:
return jsonify({“error”: “Missing image data”}), 400

```
try:
    img_bytes = base64.b64decode(b64.replace(" ", ""))
    ext_map = {"image/png": "png", "image/webp": "webp", "image/gif": "gif"}
    ext = ext_map.get(mime, "jpg")
    filename = f"tele_trace_ris.{ext}"

    boundary = "----TeleTraceBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="reqtype"\r\n\r\n'
        f"fileupload\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="fileToUpload"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8") + img_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        "https://catbox.moe/user/api.php",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "TeleTrace/2.1",
        },
    )
    ctx = ssl.create_default_context()  # [1.1] SSL on
    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
        url = resp.read().decode("utf-8").strip()

    if not url.startswith("http"):
        return jsonify({"error": f"Upload failed: {url}"}), 500

    return jsonify({
        "url":    url,
        "google": f"https://lens.google.com/uploadbyurl?url={urllib.parse.quote(url, safe='')}",
        "yandex": f"https://yandex.com/images/search?rpt=imageview&url={urllib.parse.quote(url, safe='')}",
    })

except Exception as e:
    logger.error("Image upload failed: %s", e, exc_info=True)
    return jsonify({"error": str(e)}), 500
```

# ══════════════════════════════════════════════════════════════════════════════

# [3.3] GRACEFUL SHUTDOWN

# ══════════════════════════════════════════════════════════════════════════════

def graceful_shutdown(signum, frame):
“”“Clean shutdown: disconnect client and stop the event loop.”””
logger.info(“Shutting down gracefully…”)
if _state[“client”]:
try:
run_async(_state[“client”].disconnect(), timeout=5)
except Exception:
pass
_loop.call_soon_threadsafe(_loop.stop)
logger.info(“Event loop stopped. Bye!”)
raise SystemExit(0)

# ══════════════════════════════════════════════════════════════════════════════

# MAIN

# ══════════════════════════════════════════════════════════════════════════════

if **name** == “**main**”:

```
signal.signal(signal.SIGINT, graceful_shutdown)
signal.signal(signal.SIGTERM, graceful_shutdown)

banner = """
```

\033[37m  ──────────────────────────────────────────────\033[0m
\033[97m         ◈  TELE-TRACE  \033[36mINTELLIGENCE\033[0m  \033[97m◈\033[0m
\033[37m            Telegram OSINT Tool v2.1\033[0m
\033[37m  ──────────────────────────────────────────────\033[0m”””

```
info = f"""
```

\033[36m  Platform:\033[0m  TERMUX / LINUX

\033[32m  ✔\033[0m  Flask + Telethon
\033[32m  ✔\033[0m  9-Platform Scanner
\033[32m  ✔\033[0m  Username History
\033[32m  ✔\033[0m  SSL Verification Enabled
\033[32m  ✔\033[0m  Rate Limiting ({CONFIG[‘RATE_LIMIT_MAX’]}/min)
\033[32m  ✔\033[0m  Input Validation

\033[37m  ──────────────────────────────────────────────\033[0m
\033[36m  Server :\033[0m  http://localhost:{CONFIG[‘PORT’]}
\033[36m  Author :\033[0m  @anubhavanonymous
\033[36m  Patches:\033[0m  See IMPROVEMENTS.md
\033[37m  ──────────────────────────────────────────────\033[0m

\033[33m  ⚠  For educational and research use only\033[0m
\033[33m  ⚠  Press Ctrl+C to stop\033[0m
“””

```
os.system("clear")
print(banner)
print(info)
print(f"\033[32m  ● RUNNING\033[0m  →  http://localhost:{CONFIG['PORT']}\n")

log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

app.run(
    host=CONFIG["HOST"],
    port=CONFIG["PORT"],
    debug=CONFIG["DEBUG"],
    threaded=True,
)
```
