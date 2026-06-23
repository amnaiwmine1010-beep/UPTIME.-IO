# ==============================================================================
# [1] PRODUCTION REQUIREMENTS (Optimized for Render & Cloud Environments)
# ==============================================================================
# fastapi>=0.115.11
# uvicorn==0.34.0
# httpx==0.28.1
# python-telegram-bot==21.10
# pydantic>=2.10.0

import os
import time
import json
import secrets
import asyncio
import httpx
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager

# --- TELEGRAM BOT CORE ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

BOT_TOKEN = "8853802336:AAE1_izH6uR7H-sWrr7jnMd06eP5MHL2x54"
OWNER_ID = 7224513731

DB_FILE = "matrix_database.json"

def load_db() -> Dict:
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "users": {},         # {user_id: {expiry: timestamp or "lifetime", link_limit: int, max_devices: int, devices: [], banned: bool}}
        "monitors": [],      # [{id, user_id, name, url, interval, status, is_active}]
        "redeem_codes": {},  # {code: {days: int, link_limit: int, max_devices: int, used: bool}}
        "web_keys": []       
    }

def save_db(data: Dict):
    try:
        with open(DB_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[!] DB Save Exception: {e}")

db = load_db()
db_lock = asyncio.Lock()

async def sync_db():
    async with db_lock:
        save_db(db)

async_client_pool: httpx.AsyncClient = None

# --- ENGINE BACKGROUND CHECKERS ---
async def check_target_pulse(monitor: Dict):
    start_time = time.time()
    url = monitor['url']
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    try:
        response = await async_client_pool.get(url, timeout=12.0, follow_redirects=True)
        monitor['response_time'] = int((time.time() - start_time) * 1000)
        monitor['status_code'] = response.status_code
        if 200 <= response.status_code < 400:
            monitor['status'] = 'UP'
            monitor['success_checks'] += 1
        else:
            monitor['status'] = 'DOWN'
    except Exception:
        monitor['status'] = 'DOWN'
        monitor['response_time'] = 0
        monitor['status_code'] = "ERR"
    finally:
        monitor['total_checks'] += 1
        monitor['last_check'] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        if monitor['total_checks'] > 0:
            monitor['uptime'] = round((monitor['success_checks'] / monitor['total_checks']) * 100, 2)

async def core_monitor_scheduler():
    while True:
        tasks = []
        current_time = time.time()
        for m in db["monitors"]:
            uid = str(m['user_id'])
            user_info = db["users"].get(uid, {})
            if user_info.get("banned", False):
                m['is_active'] = False
                m['status'] = 'SUSPENDED'
                continue
            if user_info.get("expiry") != "lifetime" and user_info.get("expiry", 0) < current_time:
                m['is_active'] = False
                m['status'] = 'EXPIRED'
                continue

            if m.get('is_active', True):
                last_run = m.get('_last_run_timestamp', 0)
                interval_seconds = m.get('interval', 5) * 60
                if current_time - last_run >= interval_seconds:
                    m['_last_run_timestamp'] = current_time
                    tasks.append(check_target_pulse(m))
        if tasks:
            await asyncio.gather(*tasks)
            await sync_db()
        await asyncio.sleep(5)

# --- ONE-MENU BUTTON CONTROLLER ROUTER ---
async def launch_main_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid_str = str(user.id)
    current_time = time.time()

    if db["users"].get(uid_str, {}).get("banned", False):
        await update.message.reply_text("❌ Your account signature is completely BANNED from this mainframe infrastructure.")
        return

    # OWNER INTERFACE (BUTTON BASED ONLY)
    if user.id == OWNER_ID:
        msg = "⚡ *SPEED_X VIP MASTER CENTRAL ENGINE* ⚡\n\nWelcome back, Owner. Choose operations directly via physical buttons below."
        keyboard = [
            [InlineKeyboardButton("🎫 GEN REDEEM KEY", callback_data="own_step1_time")],
            [InlineKeyboardButton("👥 MANAGED USERS (BAN/LIMIT)", callback_data="own_users_list")],
            [InlineKeyboardButton("🌐 WEB DASHBOARD KEY", callback_data="own_webkey")],
            [InlineKeyboardButton("💾 BACKUP DATABASE DUMP", callback_data="own_backup_db")]
        ]
        if update.message:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # SUBADMIN INTERFACE
    user_data = db["users"].get(uid_str)
    if not user_data or (user_data["expiry"] != "lifetime" and user_data["expiry"] < current_time):
        msg = f"🛸 *VIP UPTIME MATRIX PLATFORM* 🛸\n\n⚠️ Unauthorized Profile Node Detected: `{user.id}`\nAccess completely locked. Contact administration to purchase premium verification routines."
        keyboard = [
            [InlineKeyboardButton("🛒 BUY PREMIUM LICENSE", url="https://t.me/NIROB_BBZ")],
            [InlineKeyboardButton("🔑 ENTER REDEEM CODE", callback_data="usr_trigger_redeem")]
        ]
        if update.message:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    exp_text = "LIFETIME REIGN" if user_data["expiry"] == "lifetime" else time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(user_data["expiry"]))
    my_links = [m for m in db["monitors"] if m["user_id"] == user.id]
    
    msg = (
        f"🛡️ *VIP CLIENT MAINFRAME OPERATIONAL* 🛡️\n\n"
        f"📌 *Identity Node:* `{user.id}`\n"
        f"📅 *Valid Till:* `{exp_text}`\n"
        f"🚀 *Capacity Load:* `{len(my_links)}/{user_data['link_limit']}` Links"
    )
    keyboard = [
        [InlineKeyboardButton("🖥️ VIEW & TOGGLE MY LINKS", callback_data="usr_view_links")]
    ]
    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def catch_all_messages_and_redeems(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid_str = str(user.id)
    text = update.message.text.strip()

    # Intercept State Actions
    state = context.user_data.get("state")
    
    if state == "WAITING_REDEEM_CODE":
        if text.startswith("nirobxuptime_"):
            code_data = db["redeem_codes"].get(text)
            if not code_data or code_data.get("used", False):
                await update.message.reply_text("❌ Token signature corrupted or already exhausted.")
                return
            
            days = code_data["days"]
            expiry_val = "lifetime" if days == 0 else time.time() + (days * 86400)
            db["users"][uid_str] = {
                "expiry": expiry_val,
                "link_limit": code_data["link_limit"],
                "max_devices": code_data["max_devices"],
                "devices": [],
                "banned": False
            }
            code_data["used"] = True
            await sync_db()
            context.user_data["state"] = None
            
            keyboard = [[InlineKeyboardButton("🚀 LAUNCH MAINFRAME", callback_data="usr_home_return")]]
            await update.message.reply_text("🧬 *PREMIUM LICENSE CONNECTED SUCCESSFULY!*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if state == "WAITING_CUSTOM_LIMIT" and update.effective_user.id == OWNER_ID:
        t_user = context.user_data.get("target_user")
        try:
            new_lim = int(text)
            if t_user in db["users"]:
                db["users"][t_user]["link_limit"] = new_lim
                await sync_db()
                context.user_data["state"] = None
                keyboard = [[InlineKeyboardButton("⬅️ Back to Users", callback_data="own_users_list")]]
                await update.message.reply_text(f"✅ User ID {t_user} max link limit shifted to: {new_lim}", reply_markup=InlineKeyboardMarkup(keyboard))
        except ValueError:
            await update.message.reply_text("Provide a clean integer value configuration.")
        return

    # Fallback default route if user enters random text
    await launch_main_dashboard(update, context)

# --- COMPREHENSIVE INTERACTIVE CALLBACK BUTTON PROCESSING ENGINE ---
async def interface_buttons_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    uid_str = str(uid)
    data = query.data

    # User Triggers
    if data == "usr_trigger_redeem":
        context.user_data["state"] = "WAITING_REDEEM_CODE"
        await query.edit_message_text("🔑 *INPUT MODE ACTIVE:*\nPlease type or paste your validation key string directly here (`nirobxuptime_*******`):", parse_mode="Markdown")
        return
        
    if data == "usr_home_return":
        await launch_main_dashboard(update, context)
        return

    if data == "usr_view_links":
        my_links = [m for m in db["monitors"] if m["user_id"] == uid]
        if not my_links:
            await query.edit_message_text("⚠️ No tracks mapped to your matrix stream.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="usr_home_return")]]))
            return
        msg = "🖥️ *YOUR ACTIVE DESIGNATED TARGET PIPELINES*:\n\n"
        keyboard = []
        for m in my_links:
            status_ico = "🟢" if m["status"] == "UP" else "🔴" if m["status"] == "DOWN" else "⚪"
            msg += f"{status_ico} Name: *{m['name']}* | Health: `{m['uptime']}%`\n🌐 `{m['url']}`\n\n"
            toggle_label = f"⚙️ Toggle: {m['name']} [{'ON' if m['is_active'] else 'OFF'}]"
            keyboard.append([InlineKeyboardButton(toggle_label, callback_data=f"usr_toggle_{m['id']}")])
        keyboard.append([InlineKeyboardButton("⬅️ Back Dashboard", callback_data="usr_home_return")])
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("usr_toggle_"):
        mid = data.split("_")[2]
        for m in db["monitors"]:
            if m["id"] == mid and m["user_id"] == uid:
                m["is_active"] = not m["is_active"]
                m["status"] = "PENDING" if m["is_active"] else "STOPPED"
                await sync_db()
                break
        query.data = "usr_view_links"
        await interface_buttons_dispatcher(update, context)
        return

    # OWNER CALLBACK EXCLUSIONS
    if uid != OWNER_ID: return

    if data == "own_main_panel":
        await launch_main_dashboard(update, context)
        return

    if data == "own_webkey":
        wkey = f"matrix_key_{secrets.token_urlsafe(16)}"
        db["web_keys"].append(wkey)
        await sync_db()
        keyboard = [[InlineKeyboardButton("⬅️ Back Menu", callback_data="own_main_panel")]]
        await query.edit_message_text(f"🔑 *LIVE NEW WEB SECURITY TOKEN:*\n\n`{wkey}`\n\nAuthorized for access configuration schema bypass sequence.", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "own_backup_db":
        await sync_db()
        keyboard = [[InlineKeyboardButton("⬅️ Back Menu", callback_data="own_main_panel")]]
        if os.path.exists(DB_FILE):
            with open(DB_FILE, 'rb') as doc:
                await context.bot.send_document(chat_id=OWNER_ID, document=doc, filename="matrix_database.json", caption="⚡ Complete System Database Schema Struct Vector Dump Transmitted.")
            await query.edit_message_text("✅ File emitted safely into secure room pipeline.", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # Wizard Steps for Key Generation
    if data == "own_step1_time":
        keyboard = [
            [InlineKeyboardButton("🗓️ 30 Days Cycle", callback_data="own_step2_links_30")],
            [InlineKeyboardButton("🗓️ 90 Days Cycle", callback_data="own_step2_links_90")],
            [InlineKeyboardButton("👑 LIFETIME UNLIMITED", callback_data="own_step2_links_0")]
        ]
        await query.edit_message_text("⚡ *KEY GENERATION STAGE [1/3]*:\nSelect license duration criteria:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("own_step2_links_"):
        days = data.split("_")[3]
        keyboard = [
            [InlineKeyboardButton("🚀 5 Channels", callback_data=f"own_step3_devs_{days}_5")],
            [InlineKeyboardButton("🚀 15 Channels", callback_data=f"own_step3_devs_{days}_15")],
            [InlineKeyboardButton("🚀 50 Channels Max", callback_data=f"own_step3_devs_{days}_50")]
        ]
        await query.edit_message_text("⚡ *KEY GENERATION STAGE [2/3]*:\nSelect Maximum quantitative track payload allocations limits:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("own_step3_devs_"):
        parts = data.split("_")
        days = int(parts[3])
        links = int(parts[4])
        
        keyboard = [
            [InlineKeyboardButton("📱 1 Hardware Identity", callback_data=f"own_finish_gen_{days}_{links}_1")],
            [InlineKeyboardButton("📱 3 Multi-Device Nodes", callback_data=f"own_finish_gen_{days}_{links}_3")],
            [InlineKeyboardButton("📱 5 Concurrent Rig Rings", callback_data=f"own_finish_gen_{days}_{links}_5")]
        ]
        await query.edit_message_text("⚡ *KEY GENERATION STAGE [3/3]*:\nSelect concurrent secure active hardware device threshold limit:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("own_finish_gen_"):
        parts = data.split("_")
        days, links, devs = int(parts[3]), int(parts[4]), int(parts[5])
        token = f"nirobxuptime_{secrets.token_hex(4).upper()}"
        
        db["redeem_codes"][token] = {
            "days": days, "link_limit": links, "max_devices": devs, "used": False
        }
        await sync_db()
        keyboard = [[InlineKeyboardButton("⬅️ Main Dashboard Engine", callback_data="own_main_panel")]]
        duration_text = "LIFETIME REIGN" if days == 0 else f"{days} Days"
        await query.edit_message_text(f"🎫 *VIP QUANTUM TICKET GENERATED SUCCESSFULLY* 🎫\n\n`{token}`\n\n⚙️ Config Payload:\n🔹 Duration: {duration_text}\n🔹 Monitor Capacity: {links} Tracks\n🔹 Device Ceiling: {devs} HW Nodes", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # User Management Block Buttons Layer Routines
    if data == "own_users_list":
        if not db["users"]:
            await query.edit_message_text("⚠️ No records inside active profile ledger database arrays.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back Menu", callback_data="own_main_panel")]]))
            return
        msg = "👥 *MASTER SYSTEM MANAGEMENT PROFILES LEDGER*:\nSelect target user string execution node:\n\n"
        keyboard = []
        for uid_key, ucon in db["users"].items():
            ban_status_label = "🚫 BANNED" if ucon.get("banned") else "🟢 ACTIVE"
            keyboard.append([InlineKeyboardButton(f"User: {uid_key} [{ban_status_label}]", callback_data=f"own_manageuser_{uid_key}")])
        keyboard.append([InlineKeyboardButton("⬅️ Back Dashboard Menu", callback_data="own_main_panel")])
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("own_manageuser_"):
        t_uid = data.split("_")[2]
        ucon = db["users"].get(t_uid, {})
        my_links = [m for m in db["monitors"] if m["user_id"] == int(t_uid)]
        
        msg = (
            f"👤 *PROFILE MAINTENANCE CONSOLE INTERFACE* 👤\n\n"
            f"🔹 User Core ID Node: `{t_uid}`\n"
            f"🔹 Status: `{'BANNED BLOCK' if ucon.get('banned') else 'OPERATIONAL SECURE'}`\n"
            f"🔹 Config Limit Trace Ceiling: `{ucon.get('link_limit')}` Links\n"
            f"🔹 Running Tracks Mapped: `{len(my_links)}` Active Objects"
        )
        keyboard = [
            [InlineKeyboardButton("🚫 INSTANT BAN", callback_data=f"own_execban_{t_uid}"), InlineKeyboardButton("🔓 REMOVE BAN", callback_data=f"own_execunban_{t_uid}")],
            [InlineKeyboardButton("⚙️ ADJUST MAX LINK CAPACITY", callback_data=f"own_execlimit_{t_uid}")],
            [InlineKeyboardButton("⬅️ Back List Ledger", callback_data="own_users_list")]
        ]
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("own_execban_"):
        t_uid = data.split("_")[2]
        db["users"][t_uid]["banned"] = True
        await sync_db()
        query.data = f"own_manageuser_{t_uid}"
        await interface_buttons_dispatcher(update, context)
        return

    if data.startswith("own_execunban_"):
        t_uid = data.split("_")[2]
        db["users"][t_uid]["banned"] = False
        await sync_db()
        query.data = f"own_manageuser_{t_uid}"
        await interface_buttons_dispatcher(update, context)
        return

    if data.startswith("own_execlimit_"):
        t_uid = data.split("_")[2]
        context.user_data["state"] = "WAITING_CUSTOM_LIMIT"
        context.user_data["target_user"] = t_uid
        await query.edit_message_text(f"🔢 Input new max quantitative channel constraint count integer value for ID `{t_uid}`:", parse_mode="Markdown")
        return

# --- FASTAPI WEB LIFECYCLE MANAGEMENT ---
@asynccontextmanager
async def app_lifespan(app: FastAPI):
    global async_client_pool
    async_client_pool = httpx.AsyncClient(limits=httpx.Limits(max_connections=200, max_keepalive_connections=50))
    
    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", launch_main_dashboard))
    bot_app.add_handler(CallbackQueryHandler(interface_buttons_dispatcher))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, catch_all_messages_and_redeems))
    
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()
    
    asyncio.create_task(core_monitor_scheduler())
    yield
    await bot_app.updater.stop()
    await bot_app.stop()
    await bot_app.shutdown()
    await async_client_pool.aclose()

app = FastAPI(title="VIP Central Matrix System By SPEED_X", lifespan=app_lifespan)

# --- WEB BACKEND API ENDPOINTS ROUTERS ---
@app.post("/api/auth/verify")
async def verify_web_key(payload: Dict):
    key = payload.get("key")
    device_id = payload.get("device_id", "web_node")
    if not key: raise HTTPException(status_code=400, detail="Missing Authentication Matrix Key")
    
    if key in db["web_keys"]:
        return {"status": "authorized", "role": "owner", "token": key, "user_id": OWNER_ID}
    
    for uid_str, udata in db["users"].items():
        if udata.get("banned", False): continue
        if key in db["redeem_codes"]:
            if device_id not in udata["devices"]:
                if len(udata["devices"]) >= udata["max_devices"]:
                    raise HTTPException(status_code=403, detail="Device Registration Matrix Denied: Hardware Limit Reached.")
                udata["devices"].append(device_id)
                await sync_db()
            return {"status": "authorized", "role": "subadmin", "token": key, "user_id": int(uid_str)}
            
    raise HTTPException(status_code=401, detail="Cryptographic Security Check Failure: Unauthorized Key Pattern.")

@app.get("/api/monitors")
async def fetch_api_monitors(user_id: int, role: str):
    if role == "owner": return db["monitors"]
    return [m for m in db["monitors"] if m["user_id"] == user_id]

@app.post("/api/monitors")
async def create_api_monitor(payload: Dict):
    uid_str = str(payload["user_id"])
    role = payload["role"]
    user_info = db["users"].get(uid_str)
    
    if role != "owner":
        if not user_info or user_info.get("banned", False):
            raise HTTPException(status_code=403, detail="Account suspension matrix active.")
        existing_count = len([m for m in db["monitors"] if m["user_id"] == int(payload["user_id"])])
        if existing_count >= user_info["link_limit"]:
            raise HTTPException(status_code=400, detail="Target tracking quantitative limit ceiling breached.")

    new_node = {
        "id": str(int(time.time() * 1000)),
        "user_id": int(payload["user_id"]),
        "name": payload["name"],
        "url": payload["url"],
        "interval": int(payload["interval"]),
        "status": "PENDING",
        "response_time": 0,
        "status_code": "N/A",
        "uptime": 100.0,
        "success_checks": 0,
        "total_checks": 0,
        "is_active": True,
        "_last_run_timestamp": 0
    }
    db["monitors"].append(new_node)
    await sync_db()
    return new_node

@app.post("/api/monitors/{mid}/toggle")
async def toggle_api_monitor(mid: str, payload: Dict):
    uid = int(payload["user_id"])
    role = payload["role"]
    for m in db["monitors"]:
        if m["id"] == mid:
            if role != "owner" and m["user_id"] != uid:
                raise HTTPException(status_code=403, detail="Security Intercept: Privilege Violation")
            m["is_active"] = not m["is_active"]
            m["status"] = "PENDING" if m["is_active"] else "STOPPED"
            await sync_db()
            return m
    raise HTTPException(status_code=404, detail="Node missing")

@app.delete("/api/monitors/{mid}")
async def delete_api_monitor(mid: str, user_id: int, role: str):
    global db
    initial_len = len(db["monitors"])
    if role == "owner":
        db["monitors"] = [m for m in db["monitors"] if m["id"] != mid]
    else:
        db["monitors"] = [m for m in db["monitors"] if not (m["id"] == mid and m["user_id"] == user_id)]
    if len(db["monitors"]) == initial_len:
        raise HTTPException(status_code=404, detail="Target not modified")
    await sync_db()
    return {"success": True}

@app.post("/api/system/upload_db")
async def system_replace_db(payload: Dict):
    global db
    if payload.get("role") != "owner": raise HTTPException(status_code=403, detail="Access Denied")
    incoming_data = payload.get("database_json")
    if not incoming_data or "users" not in incoming_data or "monitors" not in incoming_data:
        raise HTTPException(status_code=400, detail="Malformed structure schematic asset array.")
    db = incoming_data
    await sync_db()
    return {"success": True}

# --- NEXT-GEN REDESIGNED VIP MATRICES WEB FRONTEND APPLICATION LAYER ---
@app.get("/", response_class=HTMLResponse)
async def deliver_nextgen_ui():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>SPEED_X • NEXTGEN SECURITY GRID</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@600;900&family=Share+Tech+Mono&display=swap');
            body { background: #020204; color: #cbd5e1; font-family: 'Share Tech Mono', monospace; user-select: none; }
            .font-vip { font-family: 'Orbitron', sans-serif; }
            .vip-panel { background: rgba(6, 6, 14, 0.95); border: 1px solid rgba(147, 51, 234, 0.15); box-shadow: 0 0 40px rgba(0,0,0,0.8); }
            .vip-glow-glow { box-shadow: 0 0 25px rgba(147, 51, 234, 0.25); border-color: rgba(147, 51, 234, 0.5) !important; }
            .text-vip-neon { text-shadow: 0 0 12px rgba(192, 132, 252, 0.8); }
            .crypto-input { background: rgba(0, 0, 0, 0.8); border: 1px solid rgba(147, 51, 234, 0.3); color: #fff; }
            .crypto-input:focus { border-color: #a855f7; box-shadow: 0 0 15px rgba(147, 51, 234, 0.4); outline: none; }
        </style>
        <script>
            document.addEventListener('contextmenu', e => e.preventDefault());
            function fetchHardwareNodeSignature() {
                let sig = localStorage.getItem('matrix_hardware_signature');
                if(!sig) { sig = 'node_hw_' + Math.random().toString(36).substring(2, 15); localStorage.setItem('matrix_hardware_signature', sig); }
                return sig;
            }
        </script>
    </head>
    <body class="min-h-screen relative p-4 flex items-center justify-center">
        <div id="auth-wall-container" class="w-full max-w-md vip-panel p-8 rounded-2xl border-t-4 border-t-purple-600 z-50 relative">
            <div class="text-center mb-6">
                <div class="inline-block p-3 bg-purple-950/40 rounded-full mb-3 border border-purple-500/30">
                    <i class="fa-solid fa-user-shield text-3xl text-purple-400"></i>
                </div>
                <h1 class="text-2xl font-black tracking-widest font-vip text-white text-vip-neon">SECURITY CHECKPOINT</h1>
                <p class="text-[11px] text-gray-500 uppercase tracking-widest mt-1">OPERATOR SYSTEM ACCESS ENTRY VALIDATION KEY REQUIRED</p>
            </div>
            <div class="space-y-4">
                <div>
                    <label class="block text-xs font-bold text-purple-400 uppercase mb-1">Passcode / Key Token Structure</label>
                    <input type="password" id="gateway-security-key" class="w-full crypto-input rounded-xl px-4 py-3 text-xs tracking-widest text-center" placeholder="matrix_key_... or nirobxuptime_...">
                </div>
                <button onclick="attemptPerimeterAuthentication()" class="w-full bg-purple-600 hover:bg-purple-500 text-black font-black py-3 rounded-xl tracking-widest uppercase text-xs font-vip transition-all shadow-lg">VERIFY INFRASTRUCTURE CORE</button>
            </div>
        </div>

        <div id="mainframe-application-workspace" class="w-full max-w-6xl mx-auto space-y-6 hidden my-6">
            <header class="vip-panel p-6 rounded-2xl flex flex-col md:flex-row justify-between items-center gap-4 border-l-4 border-l-purple-500">
                <div>
                    <h1 class="text-3xl font-black font-vip text-white tracking-widest text-vip-neon">VIP CENTRAL MANAGEMENT STORAGE SERVER</h1>
                    <p class="text-xs text-gray-500 tracking-wider">SECURED ENGINE INTERFACES • DEVELOPED BY SPEED_X</p>
                </div>
                <div class="flex items-center gap-3">
                    <span id="role-badge" class="px-4 py-1.5 bg-purple-950/40 border border-purple-500/40 text-purple-300 font-black text-xs uppercase tracking-widest rounded-lg">SUBADMIN CONSOLE ACTIVE</span>
                    <button onclick="window.location.reload()" class="px-3 py-1.5 bg-rose-950/40 border border-rose-900/50 hover:border-rose-500 text-rose-400 font-bold text-xs rounded-lg transition-all">TERMINATE ACCESS</button>
                </div>
            </header>

            <div id="owner-exclusive-operations-box" class="hidden vip-panel p-6 rounded-2xl border border-dashed border-purple-500/40 space-y-4">
                <h2 class="text-xs font-bold text-purple-400 font-vip uppercase tracking-widest"><i class="fa-solid fa-triangle-exclamation mr-1.5"></i> Hot Database Engine Registry Overwrite Realtime Interface System</h2>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div class="bg-black/40 border border-purple-950 p-4 rounded-xl">
                        <h3 class="text-xs font-bold text-white mb-2 uppercase">Hot Swap Central Json Registry File</h3>
                        <input type="file" id="db-file-picker" accept=".json" class="block w-full text-xs text-gray-400 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-bold file:bg-purple-950 file:text-purple-400 cursor-pointer">
                        <button onclick="commitDatabaseOverrideUpload()" class="mt-3 px-4 py-2 bg-purple-600 hover:bg-purple-500 text-black text-xs font-black rounded-lg uppercase tracking-wider transition-all">EXECUTE FULL HOT OVERWRITE</button>
                    </div>
                    <div class="bg-black/40 border border-purple-950 p-4 rounded-xl flex flex-col justify-between">
                        <h3 class="text-xs font-bold text-white mb-2 uppercase">Dump/Extract Realtime Live Backup</h3>
                        <p class="text-[11px] text-gray-500">Extract an instantaneous exact state cryptographic configuration of all active nodes inside the mainframe database storage layer.</p>
                        <button onclick="triggerDatabaseExportDownload()" class="mt-2 px-4 py-2 border border-purple-500 text-purple-400 hover:bg-purple-950 text-xs font-bold rounded-lg uppercase tracking-wider transition-all">EXTRACT BACKUP STREAM DUMP</button>
                    </div>
                </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div class="vip-panel p-6 rounded-2xl space-y-4 h-fit">
                    <h2 class="text-xs font-bold text-white font-vip uppercase tracking-widest flex items-center gap-1.5 text-vip-neon"><i class="fa-solid fa-circle-plus text-purple-400"></i> Inject Operational Vector Target</h2>
                    <div class="space-y-3 text-xs">
                        <div>
                            <label class="block text-gray-400 mb-1 font-bold uppercase">Alias Tag</label>
                            <input type="text" id="target-name" class="w-full crypto-input rounded-lg p-2.5" placeholder="VIP System Channel">
                        </div>
                        <div>
                            <label class="block text-gray-400 mb-1 font-bold uppercase">Routing URL Destination</label>
                            <input type="url" id="target-url" class="w-full crypto-input rounded-lg p-2.5" placeholder="https://host.com/health">
                        </div>
                        <div>
                            <label class="block text-gray-400 mb-1 font-bold uppercase">Polling Cycle Frequency</label>
                            <select id="target-interval" class="w-full crypto-input rounded-lg p-2.5 cursor-pointer">
                                <option value="1">1 Minute Hyper Polling Pulse</option>
                                <option value="5" selected>5 Minutes Standard Polling Logic</option>
                                <option value="15">15 Minutes Conservative Mode</option>
                            </select>
                        </div>
                        <button onclick="injectTargetNodePipeline()" class="w-full py-3 bg-purple-600 hover:bg-purple-500 text-black font-black uppercase tracking-wider rounded-xl font-vip transition-all">DEPLOY MONITOR NODE</button>
                    </div>
                </div>

                <div class="lg:col-span-2 vip-panel p-6 rounded-2xl space-y-4">
                    <h2 class="text-xs font-bold text-white font-vip uppercase tracking-widest flex items-center gap-1.5 text-vip-neon"><i class="fa-solid fa-network-wired text-purple-400"></i> DYNAMIC TARGET CHANNELS MONITOR STRATIFIED GRID</h2>
                    <div id="channels-grid-container" class="grid grid-cols-1 md:grid-cols-2 gap-4 max-h-[500px] overflow-y-auto pr-2"></div>
                </div>
            </div>
        </div>

        <script>
            let sessionState = { token: "", role: "", user_id: null };

            async function attemptPerimeterAuthentication() {
                const key = document.getElementById("gateway-security-key").value.trim();
                if(!key) return alert("Access Entry Key Signature Required.");
                const devId = fetchHardwareNodeSignature();
                try {
                    const res = await fetch("/api/auth/verify", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ key: key, device_id: devId })
                    });
                    if(!res.ok) { const err = await res.json(); alert(err.detail || "Access Key Refused by Firewall."); return; }
                    
                    const data = await res.json();
                    sessionState.token = data.token;
                    sessionState.role = data.role;
                    sessionState.user_id = data.user_id;

                    document.getElementById("auth-wall-container").classList.add("hidden");
                    document.getElementById("mainframe-application-workspace").classList.remove("hidden");
                    
                    document.getElementById("role-badge").innerText = `${data.role.toUpperCase()} LEVEL PERMISSION`;
                    if(data.role === "owner") {
                        document.getElementById("owner-exclusive-operations-box").classList.remove("hidden");
                    }
                    synchronizeChannelsGrid();
                    setInterval(synchronizeChannelsGrid, 8000);
                } catch(e) { alert("Matrix Registry Denied System Endpoint Connection Thread."); }
            }

            async function synchronizeChannelsGrid() {
                try {
                    const res = await fetch(`/api/monitors?user_id=${sessionState.user_id}&role=${sessionState.role}`);
                    const data = await res.json();
                    const container = document.getElementById("channels-grid-container");
                    container.innerHTML = data.length === 0 ? '<div class="text-xs text-gray-600 col-span-2 text-center p-12 tracking-widest">NO SIGNALS ROUTED TO DYNAMIC DATA LAYER.</div>' : '';
                    
                    data.forEach(m => {
                        const div = document.createElement("div");
                        let isUp = m.status === 'UP';
                        let borderStyle = isUp ? 'border-l-emerald-500 vip-glow-glow' : m.status === 'DOWN' ? 'border-l-rose-500' : 'border-l-gray-600';
                        div.className = `vip-panel p-4 rounded-xl border-l-4 ${borderStyle} text-xs space-y-2`;
                        div.innerHTML = `
                            <div class="flex justify-between items-start">
                                <div>
                                    <h4 class="font-bold text-white tracking-wide uppercase">${m.name} <span class="text-purple-400 font-mono">[${m.status_code}]</span></h4>
                                    <p class="text-[11px] text-gray-500 break-all mt-0.5">${m.url}</p>
                                </div>
                                <span class="px-2 py-0.5 text-[9px] font-black tracking-widest rounded border ${isUp ? 'bg-emerald-950/40 text-emerald-400 border-emerald-500/20' : 'bg-rose-950/40 text-rose-400 border-rose-500/20'}">${m.status}</span>
                            </div>
                            <div class="grid grid-cols-2 gap-2 bg-black/40 border border-purple-950/30 p-2 rounded text-[11px] text-gray-400">
                                <div>Latency: <span class="text-purple-400 font-bold">${m.response_time}ms</span></div>
                                <div>Uptime Score: <span class="text-white font-bold">${m.uptime}%</span></div>
                            </div>
                            <div class="flex gap-2 pt-1">
                                <button onclick="executeNodeToggle('${m.id}')" class="px-3 py-1 bg-purple-950/40 border border-purple-900 text-purple-300 rounded hover:border-purple-500 transition-all">${m.is_active ? 'Suspend' : 'Activate'}</button>
                                <button onclick="executeNodeIsolationTermination('${m.id}')" class="px-3 py-1 text-rose-400 border border-transparent hover:border-rose-950 rounded font-bold ml-auto transition-all">Terminate</button>
                            </div>
                        `;
                        container.appendChild(div);
                    });
                } catch(e) {}
            }

            async function injectTargetNodePipeline() {
                const name = document.getElementById("target-name").value.trim();
                const url = document.getElementById("target-url").value.trim();
                const interval = document.getElementById("target-interval").value;
                if(!name || !url) return alert("Properties fields mandatory matrix allocation profiles requirements.");
                
                const res = await fetch("/api/monitors", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ user_id: sessionState.user_id, role: sessionState.role, name, url, interval })
                });
                if(res.ok) {
                    document.getElementById("target-name").value = "";
                    document.getElementById("target-url").value = "";
                    synchronizeChannelsGrid();
                } else { const err = await res.json(); alert(err.detail || "Allocation injection denied."); }
            }

            async function executeNodeToggle(mid) {
                await fetch(`/api/monitors/${mid}/toggle`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ user_id: sessionState.user_id, role: sessionState.role })
                });
                synchronizeChannelsGrid();
            }

            async function executeNodeIsolationTermination(mid) {
                if(confirm("Terminate object channel connection pathway asset?")) {
                    await fetch(`/api/monitors/${mid}?user_id=${sessionState.user_id}&role=${sessionState.role}`, { method: "DELETE" });
                    synchronizeChannelsGrid();
                }
            }

            function commitDatabaseOverrideUpload() {
                const filePicker = document.getElementById("db-file-picker");
                if(filePicker.files.length === 0) return alert("Select standard source .json asset file cluster pool first.");
                const fileReader = new FileReader();
                fileReader.onload = async function(e) {
                    try {
                        const dataObj = JSON.parse(e.target.result);
                        const res = await fetch("/api/system/upload_db", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ role: sessionState.role, database_json: dataObj })
                        });
                        if(res.ok) { alert("Core registries database structure completely hot-replaced."); synchronizeChannelsGrid(); }
                    } catch(err) { alert("Syntax architecture framing error asset compile rejection analysis."); }
                };
                fileReader.readAsText(filePicker.files[0]);
            }

            async function triggerDatabaseExportDownload() {
                const res = await fetch(`/api/monitors?user_id=${sessionState.user_id}&role=${sessionState.role}`);
                const list = await res.json();
                const blob = new Blob([JSON.stringify({users: {}, monitors: list, redeem_codes: {}, web_keys: []}, null, 4)], {type : 'application/json'});
                const anchor = document.createElement('a'); anchor.href = URL.createObjectURL(blob);
                anchor.download = "matrix_hot_backup.json"; anchor.click(); anchor.remove();
            }
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
