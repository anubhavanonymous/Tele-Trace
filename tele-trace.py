import os
import asyncio
import base64
import hashlib
import json
import threading
import re
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template
from telethon.errors import SessionPasswordNeededError
import secrets

# Ensure Flask finds templates relative to this file's location
app = Flask(__name__, 
    template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates'),
    static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
)
app.secret_key = secrets.token_hex(32)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(BASE_DIR, "tg_osint.session")
CONFIG_FILE  = os.path.join(BASE_DIR, "tg_config.json")

_loop = asyncio.new_event_loop()
def _run_loop():
    asyncio.set_event_loop(_loop)
    _loop.run_forever()
threading.Thread(target=_run_loop, daemon=True).start()

def run_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, _loop).result()

_state = {"client": None, "phone_code_hash": None, "login_phone": None}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f: return json.load(f)
    return None

def save_config(api_id, api_hash):
    with open(CONFIG_FILE, "w") as f:
        json.dump({"api_id": api_id, "api_hash": api_hash}, f)

# ── ACCOUNT AGE ESTIMATION ──
def estimate_account_age(user_id: int) -> dict:
    """
    Estimate Telegram account creation date from user_id.
    Telegram IDs are roughly sequential with known reference points.
    """
    milestones = [
        (100000000,  "2013-08"),
        (200000000,  "2014-06"),
        (300000000,  "2015-06"),
        (400000000,  "2016-06"),
        (500000000,  "2017-06"),
        (600000000,  "2018-01"),
        (700000000,  "2018-08"),
        (800000000,  "2019-01"),
        (900000000,  "2019-06"),
        (1000000000, "2019-11"),
        (1100000000, "2020-03"),
        (1200000000, "2020-06"),
        (1300000000, "2020-09"),
        (1400000000, "2020-12"),
        (1500000000, "2021-03"),
        (1600000000, "2021-05"),
        (1700000000, "2021-08"),
        (1800000000, "2021-11"),
        (1900000000, "2022-01"),
        (2000000000, "2022-03"),
        (2100000000, "2022-06"),
        (2500000000, "2022-10"),
        (3000000000, "2023-02"),
        (4000000000, "2023-08"),
        (5000000000, "2024-01"),
        (6000000000, "2024-06"),
        (7000000000, "2024-11"),
    ]
    lower_date = "2013-08"
    upper_date = datetime.now(timezone.utc).strftime("%Y-%m")
    for i, (mid, date) in enumerate(milestones):
        if user_id < mid:
            lower_date = milestones[i-1][1] if i > 0 else "2013-08"
            upper_date = date
            break

    def fmt(ym):
        try:
            dt = datetime.strptime(ym, "%Y-%m")
            return dt.strftime("%b %Y")
        except:
            return ym

    # Rough account age in years
    try:
        ref_dt = datetime.strptime(lower_date, "%Y-%m").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        months = (now.year - ref_dt.year)*12 + (now.month - ref_dt.month)
        years = months // 12
        rem_months = months % 12
        if years > 0:
            age_str = f"~{years}y {rem_months}m old" if rem_months else f"~{years}y old"
        else:
            age_str = f"~{rem_months} months old"
    except:
        age_str = "Unknown"

    return {
        "range": f"{fmt(lower_date)} – {fmt(upper_date)}",
        "age": age_str,
        "user_id": user_id,
    }

# ── AUTH COROUTINES ──
async def _make_client(api_id, api_hash):
    from telethon import TelegramClient
    if _state["client"]:
        try: await _state["client"].disconnect()
        except: pass
    _state["client"] = TelegramClient(SESSION_FILE, api_id, api_hash)

async def _check_auth():
    c = _state["client"]
    if c is None: return False
    await c.connect()
    return await c.is_user_authorized()

async def _restore_client():
    cfg = load_config()
    if cfg and _state["client"] is None:
        await _make_client(int(cfg["api_id"]), cfg["api_hash"])

async def _send_code(phone):
    c = _state["client"]
    await c.connect()
    result = await c.send_code_request(phone)
    _state["phone_code_hash"] = result.phone_code_hash
    _state["login_phone"] = phone

async def _verify_code(code, password=None):
    c = _state["client"]
    await c.connect()
    phone = _state["login_phone"]
    phash = _state["phone_code_hash"]
    if password: await c.sign_in(password=password)
    else: await c.sign_in(phone, code, phone_code_hash=phash)
    me = await c.get_me()
    return me.first_name or me.username or "User"

async def _logout():
    if _state["client"]:
        try: await _state["client"].disconnect()
        except: pass
        _state["client"] = None

# ── SANGMATA SCRAPING ──
async def _get_history(user_id: int) -> dict:
    """Send user_id to @SangMata_BOT and parse response."""
    c = _state["client"]
    await c.connect()
    result = {"names": [], "usernames": [], "error": None, "quota_error": None}
    try:
        bot = await c.get_entity("SangMata_BOT")
        old_msgs = await c.get_messages(bot, limit=1)
        last_id = old_msgs[0].id if old_msgs else 0
        print(f"[History] last_id before send: {last_id}")

        await c.send_message(bot, str(user_id))
        print(f"[History] Sent user_id {user_id} to bot, polling...")

        response_text = None
        for attempt in range(15):
            await asyncio.sleep(1)
            new_msgs = await c.get_messages(bot, limit=5)
            latest = new_msgs[0].id if new_msgs else 0
            print(f"[History] attempt {attempt+1}: latest_id={latest}")
            for msg in new_msgs:
                if msg.id <= last_id:
                    break
                if not msg.out and msg.text:
                    response_text = msg.text
                    print(f"[History] Got response at attempt {attempt+1}")
                    break
            if response_text:
                break

        # Fallback: scan last 20 messages for one containing the user_id
        if not response_text:
            all_msgs = await c.get_messages(bot, limit=20)
            for msg in all_msgs:
                if not msg.out and msg.text and str(user_id) in msg.text:
                    response_text = msg.text
                    print(f"[History] Found via fallback")
                    break

        if not response_text:
            result["error"] = "Bot did not respond"
            return result

        print(f"[History] Response: {repr(response_text[:300])}")
        text = response_text

        # Quota check
        if "quota" in text.lower() or "sorry" in text.lower():
            time_match = re.search(r"(\d+\s*hours?\s*\d*\s*minutes?|\d+\s*minutes?)", text, re.IGNORECASE)
            result["quota_error"] = time_match.group(0) if time_match else None
            result["error"] = "quota_exceeded"
            return result

        # Parse entries from a section block
        def parse_entries(block):
            out = []
            for line in block.split("\n"):
                line = line.strip()
                if not line:
                    continue
                m = re.search(r'`?[0-9]*[.]?\s*\[([0-9/\-\.:\s]+)\]`?\s*(.*)', line)
                if m:
                    val = m.group(2).strip().lstrip("`").strip()
                    if val and val.lower() not in ("(empty)", "empty"):
                        out.append({"date": m.group(1).strip(), "value": val})
            return out

        # Split text into lines and find section headers
        lines = text.split("\n")
        current_section = None
        section_lines = {"names": [], "usernames": []}

        for line in lines:
            stripped = line.strip()
            # Handle both plain "Names" and markdown "**Names**"
            if re.match(r"^\*{0,2}Names?\*{0,2}$", stripped, re.IGNORECASE):
                current_section = "names"
            elif re.match(r"^\*{0,2}Usernames?\*{0,2}$", stripped, re.IGNORECASE):
                current_section = "usernames"
            elif current_section:
                section_lines[current_section].append(line)

        result["names"] = parse_entries("\n".join(section_lines["names"]))
        result["usernames"] = parse_entries("\n".join(section_lines["usernames"]))

        print(f"[History] names={len(result['names'])}, usernames={len(result['usernames'])}")

        if not result["names"] and not result["usernames"]:
            result["error"] = "No history recorded"

    except Exception as e:
        result["error"] = str(e)
        print(f"[History] Exception: {e}")
    return result


async def _scan(phone: str):
    from telethon.tl.types import (
        InputPhoneContact, InputPeerUser,
        UserStatusOnline, UserStatusRecently,
        UserStatusLastWeek, UserStatusLastMonth, UserStatusOffline,
    )
    from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
    from telethon.tl.functions.users import GetFullUserRequest
    from telethon.tl.functions.photos import GetUserPhotosRequest

    c = _state["client"]
    await c.connect()

    temp = InputPhoneContact(0, phone, "Tmp", "Lookup")
    result = await c(ImportContactsRequest([temp]))
    if not result.users:
        return {"error": "No Telegram account found for this number"}
    user = result.users[0]
    user_id     = user.id
    access_hash = user.access_hash
    username    = user.username
    try: await c(DeleteContactsRequest([user.id]))
    except: pass

    peer = InputPeerUser(user_id, access_hash)
    full = await c(GetFullUserRequest(peer))
    uobj = None
    if hasattr(full, "user") and full.user: uobj = full.user
    elif hasattr(full, "users") and full.users: uobj = full.users[0]

    # Name
    name = "Name not visible"
    try:
        parts = [p for p in [uobj.first_name, uobj.last_name] if p]
        if parts: name = " ".join(parts)
    except: pass

    # Bio
    bio = "Not visible"
    try:
        if hasattr(full, "full_user") and getattr(full.full_user, "about", None):
            bio = full.full_user.about
        elif getattr(full, "about", None):
            bio = full.about
    except: pass

    # Status
    status = "Hidden"
    status_class = "hidden"
    try:
        st = uobj.status
        if isinstance(st, UserStatusOnline):       status, status_class = "Online now", "online"
        elif isinstance(st, UserStatusRecently):   status, status_class = "Last seen recently", "recently"
        elif isinstance(st, UserStatusLastWeek):   status, status_class = "Last seen within a week", "week"
        elif isinstance(st, UserStatusLastMonth):  status, status_class = "Last seen within a month", "month"
        elif isinstance(st, UserStatusOffline):
            status = f"Last seen {st.was_online.strftime('%d %b %Y, %H:%M')}"
            status_class = "offline"
    except: pass

    flags = {
        "is_bot":      getattr(uobj, "bot",      False),
        "is_fake":     getattr(uobj, "fake",     False),
        "is_scam":     getattr(uobj, "scam",     False),
        "is_premium":  getattr(uobj, "premium",  False),
        "is_verified": getattr(uobj, "verified", False),
    }

    # Extra fields from UserFull
    extra = {}
    try:
        fu = full.full_user if hasattr(full, "full_user") else full
        extra["blocked"]                = getattr(fu, "blocked", False) or False
        extra["phone_calls_available"]  = getattr(fu, "phone_calls_available", None)
        extra["phone_calls_private"]    = getattr(fu, "phone_calls_private", None)
        extra["voice_messages_forbidden"] = getattr(fu, "voice_messages_forbidden", None)
        extra["contact_require_premium"] = getattr(fu, "contact_require_premium", None)
        extra["read_dates_private"]     = getattr(fu, "read_dates_private", None)
        extra["common_chats_count"]     = getattr(fu, "common_chats_count", None)
        extra["stories_pinned_available"] = getattr(fu, "stories_pinned_available", None)
        extra["has_scheduled"]          = getattr(fu, "has_scheduled", None)
        # ttl_period (auto-delete timer in seconds)
        ttl = getattr(fu, "ttl_period", None)
        if ttl:
            if ttl <= 86400: extra["ttl_period"] = "1 day"
            elif ttl <= 604800: extra["ttl_period"] = "1 week"
            elif ttl <= 2678400: extra["ttl_period"] = "1 month"
            else: extra["ttl_period"] = f"{ttl}s"
        else:
            extra["ttl_period"] = None
        # Theme emoticon
        extra["theme_emoticon"] = getattr(fu, "theme_emoticon", None)
        # Private forward name
        extra["private_forward_name"] = getattr(fu, "private_forward_name", None)
    except Exception as e:
        print("Extra fields error:", e)

    # All usernames (Telegram supports multiple now)
    all_usernames = []
    try:
        if hasattr(uobj, "usernames") and uobj.usernames:
            all_usernames = [u.username for u in uobj.usernames if u.username]
        elif username:
            all_usernames = [username]
    except:
        if username: all_usernames = [username]

    # Emoji status
    emoji_status = None
    try:
        es = getattr(uobj, "emoji_status", None)
        if es and hasattr(es, "document_id"):
            emoji_status = str(es.document_id)
    except: pass

    # Account age
    age_info = estimate_account_age(user_id)

    # Send history request NOW before photo downloads so bot can respond in parallel
    _hist_bot, _hist_last_id = None, 0
    try:
        _hist_bot = await c.get_entity("SangMata_BOT")
        _old = await c.get_messages(_hist_bot, limit=1)
        _hist_last_id = _old[0].id if _old else 0
        await c.send_message(_hist_bot, str(user_id))
        print(f"[History] Sent {user_id}, last_id={_hist_last_id}")
    except Exception as _he:
        print(f"[History] Send error: {_he}")

    # Photos
    all_photo_objs = []
    try:
        pr = await c(GetUserPhotosRequest(
            user_id=InputPeerUser(user_id, access_hash),
            offset=0, max_id=0, limit=100
        ))
        all_photo_objs = pr.photos or []
    except Exception as e:
        print("Photos error:", e)

    def fmt_date(ph_obj):
        """Extract and format the date from a Photo object."""
        try:
            ts = getattr(ph_obj, "date", None)
            if ts:
                if hasattr(ts, "strftime"):
                    return ts.strftime("%d %b %Y")
                else:
                    from datetime import datetime, timezone
                    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%d %b %Y")
        except: pass
        return None

    videos = []
    static_photo_objs = []
    for ph_obj in all_photo_objs:
        has_vid = hasattr(ph_obj, "video_sizes") and ph_obj.video_sizes
        if has_vid:
            best_vs = None
            for vs in ph_obj.video_sizes:
                if getattr(vs, "type", "") in ("u", "v"):
                    best_vs = vs; break
            if best_vs is None: best_vs = ph_obj.video_sizes[-1]
            try:
                raw = await c.download_media(ph_obj, file=bytes, thumb=best_vs)
                if raw and len(raw) > 500:
                    videos.append({"type":"video","data":base64.b64encode(raw).decode(),"mime":"video/mp4","date":fmt_date(ph_obj)})
                else:
                    static_photo_objs.append(ph_obj)
            except:
                static_photo_objs.append(ph_obj)
        else:
            static_photo_objs.append(ph_obj)

    static = []
    seen_hashes = set()
    for p in static_photo_objs:
        try:
            raw = await c.download_media(p, file=bytes)
            if not raw or len(raw) < 500: continue
            mime = "image/jpeg"
            if raw[1:4] == b"PNG": mime = "image/png"
            elif raw[8:12] == b"WEBP": mime = "image/webp"
            h = hashlib.sha256(raw).hexdigest()
            if h in seen_hashes: continue
            seen_hashes.add(h)
            static.append({"type":"photo","data":base64.b64encode(raw).decode(),"mime":mime,"date":fmt_date(p)})
        except: continue

    if not static and not videos and uobj:
        try:
            raw = await c.download_profile_photo(uobj, file=bytes, download_big=True)
            if raw and len(raw) > 500:
                mime = "image/jpeg"
                if raw[1:4] == b"PNG": mime = "image/png"
                elif raw[8:12] == b"WEBP": mime = "image/webp"
                static.append({"type":"photo","data":base64.b64encode(raw).decode(),"mime":mime,"date":None})
        except: pass

    media = videos + static
    scan_time = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")

    # Collect history reply — bot had time to respond during photo downloads
    history = {"names": [], "usernames": [], "error": None, "quota_error": None}
    if _hist_bot:
        try:
            response_text = None
            for _attempt in range(8):
                await asyncio.sleep(1)
                _new_msgs = await c.get_messages(_hist_bot, limit=5)
                for _msg in _new_msgs:
                    if _msg.id <= _hist_last_id:
                        break
                    if not _msg.out and _msg.text:
                        response_text = _msg.text
                        print(f"[History] Got reply at poll {_attempt+1}")
                        break
                if response_text:
                    break
            # Fallback
            if not response_text:
                _all = await c.get_messages(_hist_bot, limit=20)
                for _msg in _all:
                    if not _msg.out and _msg.text and str(user_id) in _msg.text:
                        response_text = _msg.text
                        print(f"[History] Got reply via fallback")
                        break
            if response_text:
                print(f"[History] Response: {repr(response_text[:200])}")
                if "quota" in response_text.lower() or "sorry" in response_text.lower():
                    _tm = re.search(r"(\d+\s*hours?\s*\d*\s*minutes?|\d+\s*minutes?)", response_text, re.IGNORECASE)
                    history["quota_error"] = _tm.group(0) if _tm else None
                    history["error"] = "quota_exceeded"
                else:
                    _lines = response_text.split("\n")
                    _sec = None
                    _buckets = {"names": [], "usernames": []}
                    for _line in _lines:
                        _s = _line.strip()
                        if re.match(r"^\*{0,2}Names?\*{0,2}$", _s, re.IGNORECASE): _sec = "names"
                        elif re.match(r"^\*{0,2}Usernames?\*{0,2}$", _s, re.IGNORECASE): _sec = "usernames"
                        elif _sec: _buckets[_sec].append(_line)
                    for _k, _block in _buckets.items():
                        for _line in _block:
                            _m = re.search(r'`?[0-9]*[.]?\s*\[([0-9/\-\.:\s]+)\]`?\s*(.*)', _line.strip())
                            if _m:
                                _val = _m.group(2).strip().lstrip("`").strip()
                                if _val and _val.lower() not in ("(empty)", "empty"):
                                    history[_k].append({"date": _m.group(1).strip(), "value": _val})
                    print(f"[History] names={len(history['names'])} usernames={len(history['usernames'])}")
                    if not history["names"] and not history["usernames"]:
                        history["error"] = "No history recorded"
            else:
                history["error"] = "Bot did not respond"
        except Exception as _he:
            history["error"] = str(_he)
            print(f"[History] Collect error: {_he}")

    return {
        "user_id":      user_id,
        "username":     username or "No username",
        "all_usernames": all_usernames,
        "name":         name,
        "bio":          bio,
        "phone":        phone,
        "status":       status,
        "status_class": status_class,
        "flags":        flags,
        "extra":        extra,
        "emoji_status": emoji_status,
        "age_info":     age_info,
        "history":      history,
        "scan_time":    scan_time,
        "media_count":  len(media),
        "media":        media,
    }

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/status")
def api_status():
    run_async(_restore_client())
    if _state["client"] is None:
        return jsonify({"status": "no_config"})
    try:
        authorized = run_async(_check_auth())
        return jsonify({"status": "authorized" if authorized else "need_login"})
    except:
        return jsonify({"status": "need_login"})

@app.route("/api/send_code", methods=["POST"])
def send_code():
    data = request.json
    api_id   = data.get("api_id","").strip()
    api_hash = data.get("api_hash","").strip()
    phone    = data.get("phone","").strip()
    if not all([api_id, api_hash, phone]):
        return jsonify({"error": "Missing fields"}), 400
    try: api_id_int = int(api_id)
    except: return jsonify({"error": "API ID must be a number"}), 400
    save_config(api_id_int, api_hash)
    try:
        run_async(_make_client(api_id_int, api_hash))
        run_async(_send_code(phone))
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/verify_code", methods=["POST"])
def verify_code():
    data = request.json
    code     = data.get("code","").strip()
    password = (data.get("password") or "").strip() or None
    if not code: return jsonify({"error": "Missing code"}), 400
    if _state["client"] is None: return jsonify({"error": "Session expired"}), 400
    try:
        name = run_async(_verify_code(code, password))
        return jsonify({"success": True, "name": name})
    except SessionPasswordNeededError:
        return jsonify({"error": "2fa_required"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/logout", methods=["POST"])
def logout():
    run_async(_logout())
    for f in os.listdir(BASE_DIR):
        if f.startswith("tg_osint.session"):
            try: os.remove(os.path.join(BASE_DIR, f))
            except: pass
    if os.path.exists(CONFIG_FILE):
        try: os.remove(CONFIG_FILE)
        except: pass
    return jsonify({"success": True})

@app.route("/api/history", methods=["POST"])
def history():
    user_id = (request.json or {}).get("user_id")
    if not user_id: return jsonify({"error": "Missing user_id"}), 400
    try:
        result = run_async(_get_history(int(user_id)))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/scan", methods=["POST"])
def api_scan():
    data = request.json or {}
    phone    = data.get("phone","").strip()
    username = data.get("username","").strip().lstrip("@")
    if not phone and not username:
        return jsonify({"error": "Missing phone number or username"}), 400
    try:
        if username:
            result = run_async(_scan_username(username))
        else:
            result = run_async(_scan(phone))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


async def _scan_username(username: str):
    from telethon.tl.types import (
        InputPeerUser, UserStatusOnline, UserStatusRecently,
        UserStatusLastWeek, UserStatusLastMonth, UserStatusOffline,
    )
    from telethon.tl.functions.users import GetFullUserRequest
    from telethon.tl.functions.photos import GetUserPhotosRequest

    c = _state["client"]
    await c.connect()

    try:
        entity = await c.get_entity(username)
    except Exception as e:
        return {"error": f"Username not found: {e}"}

    user_id     = entity.id
    access_hash = entity.access_hash
    uname       = entity.username

    peer = InputPeerUser(user_id, access_hash)
    full = await c(GetFullUserRequest(peer))
    uobj = None
    if hasattr(full, "user") and full.user: uobj = full.user
    elif hasattr(full, "users") and full.users: uobj = full.users[0]

    # Name
    name = "Name not visible"
    try:
        parts = [p for p in [uobj.first_name, uobj.last_name] if p]
        if parts: name = " ".join(parts)
    except: pass

    # Bio
    bio = "Not visible"
    try:
        if hasattr(full, "full_user") and getattr(full.full_user, "about", None):
            bio = full.full_user.about
        elif getattr(full, "about", None):
            bio = full.about
    except: pass

    # Status
    status = "Hidden"
    status_class = "hidden"
    try:
        st = uobj.status
        if isinstance(st, UserStatusOnline):      status, status_class = "Online now", "online"
        elif isinstance(st, UserStatusRecently):  status, status_class = "Last seen recently", "recently"
        elif isinstance(st, UserStatusLastWeek):  status, status_class = "Last seen within a week", "week"
        elif isinstance(st, UserStatusLastMonth): status, status_class = "Last seen within a month", "month"
        elif isinstance(st, UserStatusOffline):
            status = f"Last seen {st.was_online.strftime('%d %b %Y, %H:%M')}"
            status_class = "offline"
    except: pass

    flags = {
        "is_bot":      getattr(uobj, "bot",      False),
        "is_fake":     getattr(uobj, "fake",     False),
        "is_scam":     getattr(uobj, "scam",     False),
        "is_premium":  getattr(uobj, "premium",  False),
        "is_verified": getattr(uobj, "verified", False),
    }

    extra = {}
    try:
        fu = full.full_user if hasattr(full, "full_user") else full
        extra["blocked"]                  = getattr(fu, "blocked", False) or False
        extra["phone_calls_available"]    = getattr(fu, "phone_calls_available", None)
        extra["phone_calls_private"]      = getattr(fu, "phone_calls_private", None)
        extra["voice_messages_forbidden"] = getattr(fu, "voice_messages_forbidden", None)
        extra["contact_require_premium"]  = getattr(fu, "contact_require_premium", None)
        extra["read_dates_private"]       = getattr(fu, "read_dates_private", None)
        extra["common_chats_count"]       = getattr(fu, "common_chats_count", None)
        extra["stories_pinned_available"] = getattr(fu, "stories_pinned_available", None)
        extra["has_scheduled"]            = getattr(fu, "has_scheduled", None)
        ttl = getattr(fu, "ttl_period", None)
        if ttl:
            if ttl <= 86400: extra["ttl_period"] = "1 day"
            elif ttl <= 604800: extra["ttl_period"] = "1 week"
            elif ttl <= 2678400: extra["ttl_period"] = "1 month"
            else: extra["ttl_period"] = f"{ttl}s"
        else: extra["ttl_period"] = None
        extra["theme_emoticon"]       = getattr(fu, "theme_emoticon", None)
        extra["private_forward_name"] = getattr(fu, "private_forward_name", None)
    except: pass

    all_usernames = []
    try:
        if hasattr(uobj, "usernames") and uobj.usernames:
            all_usernames = [u.username for u in uobj.usernames if u.username]
        elif uname: all_usernames = [uname]
    except:
        if uname: all_usernames = [uname]

    emoji_status = None
    try:
        es = getattr(uobj, "emoji_status", None)
        if es and hasattr(es, "document_id"):
            emoji_status = str(es.document_id)
    except: pass

    age_info = estimate_account_age(user_id)

    # Send history request BEFORE photo downloads so bot can respond in parallel
    _hist_bot, _hist_last_id = None, 0
    try:
        _hist_bot = await c.get_entity("SangMata_BOT")
        _old = await c.get_messages(_hist_bot, limit=1)
        _hist_last_id = _old[0].id if _old else 0
        await c.send_message(_hist_bot, str(user_id))
        print(f"[History] Sent {user_id}, last_id={_hist_last_id}")
    except Exception as _he:
        print(f"[History] Send error: {_he}")

    # Photos
    all_photo_objs = []
    try:
        pr = await c(GetUserPhotosRequest(
            user_id=InputPeerUser(user_id, access_hash),
            offset=0, max_id=0, limit=100
        ))
        all_photo_objs = pr.photos or []
    except Exception as e:
        print("Photos error:", e)

    def fmt_date(ph_obj):
        """Extract and format the date from a Photo object."""
        try:
            ts = getattr(ph_obj, "date", None)
            if ts:
                if hasattr(ts, "strftime"):
                    return ts.strftime("%d %b %Y")
                else:
                    from datetime import datetime, timezone
                    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%d %b %Y")
        except: pass
        return None

    videos = []
    static_photo_objs = []
    for ph_obj in all_photo_objs:
        has_vid = hasattr(ph_obj, "video_sizes") and ph_obj.video_sizes
        if has_vid:
            best_vs = None
            for vs in ph_obj.video_sizes:
                if getattr(vs, "type", "") in ("u", "v"):
                    best_vs = vs; break
            if best_vs is None: best_vs = ph_obj.video_sizes[-1]
            try:
                raw = await c.download_media(ph_obj, file=bytes, thumb=best_vs)
                if raw and len(raw) > 500:
                    videos.append({"type":"video","data":base64.b64encode(raw).decode(),"mime":"video/mp4","date":fmt_date(ph_obj)})
                else:
                    static_photo_objs.append(ph_obj)
            except:
                static_photo_objs.append(ph_obj)
        else:
            static_photo_objs.append(ph_obj)

    static = []
    seen_hashes = set()
    for p in static_photo_objs:
        try:
            raw = await c.download_media(p, file=bytes)
            if not raw or len(raw) < 500: continue
            mime = "image/jpeg"
            if raw[1:4] == b"PNG": mime = "image/png"
            elif raw[8:12] == b"WEBP": mime = "image/webp"
            h = hashlib.sha256(raw).hexdigest()
            if h in seen_hashes: continue
            seen_hashes.add(h)
            static.append({"type":"photo","data":base64.b64encode(raw).decode(),"mime":mime,"date":fmt_date(p)})
        except: continue

    if not static and not videos and uobj:
        try:
            raw = await c.download_profile_photo(uobj, file=bytes, download_big=True)
            if raw and len(raw) > 500:
                mime = "image/jpeg"
                if raw[1:4] == b"PNG": mime = "image/png"
                elif raw[8:12] == b"WEBP": mime = "image/webp"
                static.append({"type":"photo","data":base64.b64encode(raw).decode(),"mime":mime,"date":None})
        except: pass

    media = videos + static
    # Collect history reply — bot had time to respond during photo downloads
    history = {"names": [], "usernames": [], "error": None, "quota_error": None}
    if _hist_bot:
        try:
            response_text = None
            for _attempt in range(8):
                await asyncio.sleep(1)
                _new_msgs = await c.get_messages(_hist_bot, limit=5)
                for _msg in _new_msgs:
                    if _msg.id <= _hist_last_id:
                        break
                    if not _msg.out and _msg.text:
                        response_text = _msg.text
                        print(f"[History] Got reply at poll {_attempt+1}")
                        break
                if response_text:
                    break
            if not response_text:
                _all = await c.get_messages(_hist_bot, limit=20)
                for _msg in _all:
                    if not _msg.out and _msg.text and str(user_id) in _msg.text:
                        response_text = _msg.text
                        print(f"[History] Got reply via fallback")
                        break
            if response_text:
                print(f"[History] Response: {repr(response_text[:200])}")
                if "quota" in response_text.lower() or "sorry" in response_text.lower():
                    _tm = re.search(r"(\d+\s*hours?\s*\d*\s*minutes?|\d+\s*minutes?)", response_text, re.IGNORECASE)
                    history["quota_error"] = _tm.group(0) if _tm else None
                    history["error"] = "quota_exceeded"
                else:
                    _lines = response_text.split("\n")
                    _sec = None
                    _buckets = {"names": [], "usernames": []}
                    for _line in _lines:
                        _s = _line.strip()
                        if re.match(r"^\*{0,2}Names?\*{0,2}$", _s, re.IGNORECASE): _sec = "names"
                        elif re.match(r"^\*{0,2}Usernames?\*{0,2}$", _s, re.IGNORECASE): _sec = "usernames"
                        elif _sec: _buckets[_sec].append(_line)
                    for _k, _block in _buckets.items():
                        for _line in _block:
                            _m = re.search(r'`?[0-9]*[.]?\s*\[([0-9/\-\.:\s]+)\]`?\s*(.*)', _line.strip())
                            if _m:
                                _val = _m.group(2).strip().lstrip("`").strip()
                                if _val and _val.lower() not in ("(empty)", "empty"):
                                    history[_k].append({"date": _m.group(1).strip(), "value": _val})
                    print(f"[History] names={len(history['names'])} usernames={len(history['usernames'])}")
                    if not history["names"] and not history["usernames"]:
                        history["error"] = "No history recorded"
            else:
                history["error"] = "Bot did not respond"
        except Exception as _he:
            history["error"] = str(_he)
            print(f"[History] Collect error: {_he}")
    scan_time = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")

    # Phone not available via username lookup
    phone_display = "Not available (username lookup)"

    return {
        "user_id":       user_id,
        "username":      uname or username,
        "all_usernames": all_usernames,
        "name":          name,
        "bio":           bio,
        "phone":         phone_display,
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

# ── CROSS-PLATFORM USERNAME SCAN ──

import ssl
import urllib.request
import urllib.parse
import concurrent.futures
import random

_USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
]

def _random_ua():
    return random.choice(_USER_AGENTS)

def _http_get(url, headers=None, follow_redirects=True, timeout=8):
    """Simple GET using urllib, returns (status_code, text) or (None, None) on error."""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return None, None

def _http_post_json(url, data, headers=None, timeout=6):
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        body = json.dumps(data).encode("utf-8")
        h = {"Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(url, data=body, headers=h, method="POST")
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try: return e.code, e.read().decode("utf-8", errors="replace")
        except: return e.code, ""
    except Exception:
        return None, None

# ── PLATFORM CHECKERS ──

def check_github(user):
    # Primary: signup check API (200=available, 422=taken)
    api_url = f"https://github.com/signup_check/username?value={user}"
    api_headers = {
        "User-Agent": _random_ua(),
        "referer": "https://github.com/signup?source=form-home-signup",
        "accept-language": "en-US,en;q=0.9",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "x-requested-with": "XMLHttpRequest",
    }
    status, text = _http_get(api_url, headers=api_headers)
    if status == 200: return "available"
    if status == 422:
        if "cannot begin or end with a hyphen" in (text or "").lower(): return "invalid"
        return "found"
    # Fallback: direct profile page
    profile_url = f"https://github.com/{user}"
    profile_headers = {"User-Agent": _random_ua(), "Accept-Language": "en-US,en;q=0.9"}
    status2, text2 = _http_get(profile_url, headers=profile_headers)
    if status2 == 200:
        if "Not Found" in (text2 or "") or f"/{user}" not in (text2 or ""): return "available"
        return "found"
    if status2 == 404: return "available"
    return "error"

def check_reddit(user):
    url = f"https://www.reddit.com/user/{user}/"
    headers = {"User-Agent": _random_ua(), "Accept-Language": "en-US,en;q=0.9"}
    status, text = _http_get(url, headers=headers)
    if status == 200:
        if "Sorry, nobody on Reddit goes by that name." in (text or ""):
            return "available"
        return "found"
    if status == 404: return "available"
    if status is None: return "error"
    return "error"

def check_instagram(user):
    # Method 1: web_profile_info API
    api_url = "https://www.instagram.com/api/v1/users/web_profile_info/"
    params = urllib.parse.urlencode({"username": user})
    api_headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Mobile Safari/537.36",
        "x-ig-app-id": "936619743392459",
        "x-requested-with": "XMLHttpRequest",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "sec-ch-ua-full-version-list": '"Not(A:Brand";v="8.0.0.0", "Chromium";v="144.0.7559.132"',
        "sec-ch-ua-platform": '"Linux"',
        "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144"',
        "sec-ch-ua-mobile": "?0",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "referer": f"https://www.instagram.com/{user}/",
        "accept-language": "en-US,en;q=0.9",
    }
    status1, text1 = _http_get(f"{api_url}?{params}", headers=api_headers)
    if status1 == 200: return "found"
    if status1 == 404: return "available"

    # Method 2: public profile page with body detection
    page_headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
    }
    status2, text2 = _http_get(f"https://www.instagram.com/{user}/", headers=page_headers)
    if status2 == 200:
        t = (text2 or "").lower()
        # Profile not found indicators
        if "page not found" in t or "sorry, this page" in t or "isn\'t available" in t:
            return "available"
        # Found indicators
        if f'"username":"{user.lower()}"' in t or f"@{user.lower()}" in t or "follower" in t:
            return "found"
        return "found"  # 200 with no not-found marker = likely exists
    if status2 == 404: return "available"
    return "error"

def check_tiktok(user):
    import re
    if not (2 <= len(user) <= 24): return "invalid"
    if user.isdigit(): return "invalid"
    if not re.match(r"^[a-zA-Z0-9_.]+$", user): return "invalid"
    if user.startswith(".") or user.endswith("."): return "invalid"
    url = f"https://www.tiktok.com/@{user}"
    headers = {
        "User-Agent": _random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "identity",
        "Accept-Language": "en-US,en;q=0.9",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "Connection": "keep-alive",
    }
    status, text = _http_get(url, headers=headers, timeout=8)
    if status == 200:
        t = (text or "").lower()
        # 10202 = user doesn't exist, 10221 = banned (user EXISTS)
        if '"statuscode":10202' in t or 'statuscode\":10202' in t:
            return "available"
        # These all mean the user exists (banned, private, etc.)
        if any(code in t for code in ['"statuscode":10221', '"statuscode":10223',
               '"statuscode":10225', 'uniqueid']):
            return "found"
        # Generic not-found page indicators
        if "couldn't find this account" in t or "this account doesn't exist" in t:
            return "available"
        if status == 200:
            return "found"
    if status == 404: return "available"
    if status is None: return "error"
    return "error"

def check_snapchat(user):
    url = f"https://www.snapchat.com/@{user}"
    headers = {
        "User-Agent": _random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "sec-ch-ua-platform": '"Android"',
        "sec-fetch-dest": "document",
    }
    status, _ = _http_get(url, headers=headers)
    if status == 200: return "found"
    if status == 404: return "available"
    if status is None: return "error"
    return "error"

def check_pinterest(user):
    url = f"https://www.pinterest.com/{user}/"
    headers = {"User-Agent": _random_ua(), "Accept-Language": "en-US,en;q=0.9"}
    status, text = _http_get(url, headers=headers)
    if status == 200:
        if "User not found." in (text or ""): return "available"
        return "found"
    if status is None: return "error"
    return "error"

def check_discord(user):
    url = "https://discord.com/api/v9/unique-username/username-attempt-unauthed"
    headers = {
        "authority": "discord.com",
        "content-type": "application/json",
        "origin": "https://discord.com",
        "referer": "https://discord.com/register",
        "User-Agent": _random_ua(),
    }
    status, text = _http_post_json(url, {"username": user}, headers=headers)
    if status == 200:
        try:
            taken = json.loads(text).get("taken")
            if taken is True: return "found"
            if taken is False: return "available"
        except: pass
    if status is None: return "error"
    return "error"

def check_linkedin(user):
    url = f"https://www.linkedin.com/in/{user}"
    headers = {"User-Agent": "Twitterbot/1.0"}
    status, _ = _http_get(url, headers=headers, follow_redirects=False)
    if status in (200, 301): return "found"
    if status == 404: return "available"
    if status is None: return "error"
    return "error"

def check_medium(user):
    url = f"https://medium.com/@{user}"
    headers = {
        "User-Agent": _random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "identity",
        "Accept-Language": "en-US,en;q=0.9",
        "sec-ch-ua-platform": '"Linux"',
        "sec-ch-ua-mobile": "?0",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
    }
    status, text = _http_get(url, headers=headers)
    if status == 404: return "available"
    if status == 200:
        t = text or ""
        # Not found indicators
        if "this page doesn" in t.lower() or "not found" in t.lower() or "404" in t[:500]:
            return "available"
        # Found indicators — check multiple patterns
        if (f'property="profile:username" content="{user}"' in t or
            f'property="profile:username" content="{user.lower()}"' in t or
            f'"@{user}"' in t.lower() or
            f'"username":"{user.lower()}"' in t.lower() or
            f"medium.com/@{user.lower()}" in t.lower()):
            return "found"
        # If 200 but no clear indicator — assume found (better false positive than false negative)
        return "found"
    if status is None: return "error"
    return "error"

PLATFORMS = [
    {"id": "github",    "name": "GitHub",    "icon": "🐙", "url": "https://github.com/{user}",           "check": check_github},
    {"id": "instagram", "name": "Instagram", "icon": "📸", "url": "https://instagram.com/{user}",        "check": check_instagram},
    {"id": "reddit",    "name": "Reddit",    "icon": "🤖", "url": "https://reddit.com/user/{user}",      "check": check_reddit},
    {"id": "tiktok",    "name": "TikTok",    "icon": "🎵", "url": "https://tiktok.com/@{user}",          "check": check_tiktok},
    {"id": "snapchat",  "name": "Snapchat",  "icon": "👻", "url": "https://snapchat.com/add/{user}",     "check": check_snapchat},
    {"id": "pinterest", "name": "Pinterest", "icon": "📌", "url": "https://pinterest.com/{user}",        "check": check_pinterest},
    {"id": "discord",   "name": "Discord",   "icon": "💬", "url": "https://discord.com",                 "check": check_discord},
    {"id": "linkedin",  "name": "LinkedIn",  "icon": "💼", "url": "https://linkedin.com/in/{user}",      "check": check_linkedin},
    {"id": "medium",    "name": "Medium",    "icon": "✍️", "url": "https://medium.com/@{user}",          "check": check_medium},
]

def scan_platforms(username: str) -> list:
    """Run all platform checks in parallel threads."""
    results = []
    def run_check(p):
        try:
            status = p["check"](username)
        except Exception as e:
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
    # Sort by platform name for consistent display
    results.sort(key=lambda x: x["name"])
    return results

@app.route("/api/platform_scan", methods=["POST"])
def platform_scan():
    username = (request.json or {}).get("username", "").strip().lstrip("@")
    if not username:
        return jsonify({"error": "Missing username"}), 400
    try:
        results = scan_platforms(username)
        found_count = sum(1 for r in results if r["status"] == "found")
        return jsonify({"username": username, "results": results, "found_count": found_count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── IMAGE UPLOAD FOR REVERSE SEARCH ──
@app.route("/api/upload_for_search", methods=["POST"])
def upload_for_search():
    """Upload image to catbox.moe and return public URL for reverse search."""
    import urllib.request
    import urllib.parse
    data = request.json or {}
    b64 = data.get("b64", "")
    mime = data.get("mime", "image/jpeg")
    if not b64:
        return jsonify({"error": "Missing image data"}), 400
    try:
        img_bytes = base64.b64decode(b64.replace(" ", ""))
        ext = "jpg"
        if mime == "image/png": ext = "png"
        elif mime == "image/webp": ext = "webp"
        elif mime == "image/gif": ext = "gif"
        filename = f"tele_trace_ris.{ext}"

        # Build multipart form data for catbox.moe
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
                "User-Agent": "TeleTrace/1.0"
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            url = resp.read().decode("utf-8").strip()

        if not url.startswith("http"):
            return jsonify({"error": f"Upload failed: {url}"}), 500

        return jsonify({
            "url": url,
            "google": f"https://lens.google.com/uploadbyurl?url={urllib.parse.quote(url, safe='')}",
            "yandex": f"https://yandex.com/images/search?rpt=imageview&url={urllib.parse.quote(url, safe='')}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    banner = """
\033[37m  ──────────────────────────────────────────────\033[0m
\033[97m         ◈  TELE-TRACE  \033[36mINTELLIGENCE\033[0m  \033[97m◈\033[0m
\033[37m            Telegram OSINT Tool v2.0\033[0m
\033[37m  ──────────────────────────────────────────────\033[0m"""

    info = """
\033[36m  Platform:\033[0m  TERMUX / LINUX

\033[32m  ✔\033[0m  Flask + Telethon
\033[32m  ✔\033[0m  9-Platform Scanner
\033[32m  ✔\033[0m  Username History

\033[37m  ──────────────────────────────────────────────\033[0m
\033[36m  Server :\033[0m  http://localhost:7777
\033[36m  Author :\033[0m  @anubhavanonymous
\033[37m  ──────────────────────────────────────────────\033[0m

\033[33m  ⚠  For educational and research use only\033[0m
\033[33m  ⚠  Press Ctrl+C to stop\033[0m
"""
    os.system('clear')
    print(banner)
    print(info)
    print("\033[32m  ● RUNNING\033[0m  →  http://localhost:7777\n")
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host="0.0.0.0", port=7777, debug=False, threaded=True)
