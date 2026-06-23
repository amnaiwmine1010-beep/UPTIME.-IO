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
import uuid
import secrets
import asyncio
import httpx
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager

# --- TELEGRAM BOT CORE ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

BOT_TOKEN = "8853802336:AAE1_izH6uR7H-sWrr7jnMd06eP5MHL2x54"
OWNER_ID = 7224513731  # Replace with your actual Telegram User ID

DB_FILE = "matrix_database.json"

# --- CORE CENTRAL DATABASE CONFIGURATION ---
def load_db() -> Dict:
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "users": {},         # {user_id: {expiry: timestamp or "lifetime", link_limit: int, devices: [], banned: bool, web_session: str}}
        "monitors": [],      # [{id, user_id, name, url, interval, status, is_active, ...}]
        "redeem_codes": {},  # {code: {days: int, link_limit: int, max_devices: int, used: bool}}
        "web_keys": []       # [keys...]
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

# --- ENGINE BACKGROUND CHECKERS ---
async_client_pool: httpx.AsyncClient = None

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
            # Check user license status prior to pinging
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

# --- TELEGRAM BOT ROUTING INTERFACE ---
async def bot_start_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid_str = str(user.id)
    current_time = time.time()
    
    # Check Ban Matrix
    if db["users"].get(uid_str, {}).get("banned", False):
        await update.message.reply_text("❌ Your mainframe identity profile has been BANNED by the Owner.")
        return

    # Owner Dashboard Route
    if user.id == OWNER_ID:
        msg = (
            f"⚡ *VIP MASTER CONTROL PANEL* ⚡\n\n"
            f"👑 *Role:* System Owner\n"
            f"Use the buttons below or terminal commands to configure license allocation sequences."
        )
        keyboard = [
            [InlineKeyboardButton("📊 System Global Statistics", callback_data="adm_stats")],
            [InlineKeyboardButton("🖥️ Master Targets Grid", callback_data="adm_grid")],
            [InlineKeyboardButton("🔑 Backup Database Dump", callback_data="adm_backup")]
        ]
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # Check Active Licensing
    user_data = db["users"].get(uid_str)
    if not user_data or (user_data["expiry"] != "lifetime" and user_data["expiry"] < current_time):
        welcome_unauth = (
            f"🛸 *VIP UPTIME MATRIX NETWORK* 🛸\n\n"
            f"⚠️ *Access Refused:* Unauthorized Node ID: `{user.id}`\n"
            f"You do not possess an active subscription key runtime.\n\n"
            f"🛒 Contact the Administrator below to acquire a premium matrix license."
        )
        keyboard = [[InlineKeyboardButton("🛍️ BUY PREMIUM LICENSE", url="https://t.me/NIROB_BBZ")]]
        await update.message.reply_text(welcome_unauth, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # Standard Authenticated Client Route
    exp_time = "LIFETIME REIGN" if user_data["expiry"] == "lifetime" else time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(user_data["expiry"]))
    client_msg = (
        f"🛡️ *VIP CLIENT MAINFRAME NODE* 🛡️\n\n"
        f"✅ *Status:* Authorized Premium\n"
        f"📅 *Valid Till:* `{exp_time}`\n"
        f"🚀 *Link Capacity Allocation:* `{len([m for m in db['monitors'] if m['user_id'] == user.id])}/{user_data['link_limit']}`"
    )
    keyboard = [
        [InlineKeyboardButton("🖥️ Manage My Target Channels", callback_data="usr_grid")],
        [InlineKeyboardButton("➕ Inject New Endpoint", callback_data="usr_add")]
    ]
    await update.message.reply_text(client_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_redeem_attempt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid_str = str(user.id)
    text = update.message.text.strip()
    
    if text.startswith("nirobxuptime_"):
        if db["users"].get(uid_str, {}).get("banned", False):
            return
            
        code_data = db["redeem_codes"].get(text)
        if not code_data or code_data.get("used", False):
            await update.message.reply_text("❌ Transmission Error: Invalid or expired redeem token signature.")
            return
        
        # Initialize or Update User Profile
        days = code_data["days"]
        expiry_val = "lifetime" if days == 0 else time.time() + (days * 86400)
        
        db["users"][uid_str] = {
            "expiry": expiry_val,
            "link_limit": code_data["link_limit"],
            "max_devices": code_data["max_devices"],
            "devices": [],
            "banned": false
        }
        code_data["used"] = True
        await sync_db()
        
        await update.message.reply_text(
            f"🧬 *MATRIX LICENSE ACTIVATED* 🧬\n\n"
            f"🔑 Token Verified Successfully.\n"
            f"📊 Link Max Capacity: {code_data['link_limit']}\n"
            f"⏳ Access Duration: {'LIFETIME' if days == 0 else f'{days} Days'}\n\n"
            f"Run /start to launch your control matrix interface.", parse_mode="Markdown"
        )

# --- BOT EXCLUSIVE COMMAND LAYER FOR OWNER ---
async def cmd_generate_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    try:
        # Syntax: /genkey <days> <links> <devices> (0 days means Lifetime)
        days = int(context.args[0])
        links = int(context.args[1])
        devices = int(context.args[2])
        
        token = f"nirobxuptime_{secrets.token_hex(4)}"
        db["redeem_codes"][token] = {
            "days": days,
            "link_limit": links,
            "max_devices": devices,
            "used": False
        }
        await sync_db()
        
        duration = "LIFETIME" if days == 0 else f"{days} Days"
        await update.message.reply_text(
            f"🎫 *VIP LICENSE TOKEN GENERATED* 🎫\n\n"
            f"`{token}`\n\n"
            f"⚙️ Config: {duration} | {links} Max Links | {devices} Devices Limit\n"
            f"Send this payload string to the intended sub-admin recipient.", parse_mode="Markdown"
        )
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Owner Format: `/genkey <days_count> <links_limit> <devices_limit>` (Pass 0 days for Lifetime)")

async def cmd_ban_infrastructure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    try:
        target_uid = str(context.args[0])
        if target_uid not in db["users"]: db["users"][target_uid] = {}
        db["users"][target_uid]["banned"] = True
        await sync_db()
        await update.message.reply_text(f"⚔️ Mainframe Identity {target_uid} isolated and BANNED.")
    except IndexError:
        await update.message.reply_text("Usage: `/ban <USER_ID>`")

async def cmd_unban_infrastructure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    try:
        target_uid = str(context.args[0])
        if target_uid in db["users"]:
            db["users"][target_uid]["banned"] = False
            await sync_db()
            await update.message.reply_text(f"🧬 Mainframe Isolation Revoked for ID {target_uid}.")
    except IndexError:
        await update.message.reply_text("Usage: `/unban <USER_ID>`")

async def cmd_modify_link_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    try:
        target_uid = str(context.args[0])
        new_lim = int(context.args[1])
        if target_uid in db["users"]:
            db["users"][target_uid]["link_limit"] = new_lim
            await sync_db()
            await update.message.reply_text(f"🛡️ Target {target_uid} updated with custom max link restriction: {new_lim}")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: `/setlimit <USER_ID> <new_limit>`")

async def cmd_generate_webkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    wkey = f"matrix_key_{secrets.token_urlsafe(16)}"
    db["web_keys"].append(wkey)
    await sync_db()
    await update.message.reply_text(f"🔑 *WEB DASHBOARD GATEWAY ACCESS KEY*\n\n`{wkey}`\n\nUse this authentication signature string to pass the web portal perimeter protection system.", parse_mode="Markdown")

async def cmd_backup_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    await sync_db()
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'rb') as doc:
            await update.message.reply_document(document=doc, filename="matrix_database_backup.json", caption="⚡ Live Matrix Database Vector Stream Dump Complete.")

# --- TELEGRAM INLINE CALLBACK PROCESSING ROUTINES ---
async def bot_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    uid_str = str(uid)
    data = query.data

    # OWNER CALLBACK MATCHERS
    if uid == OWNER_ID:
        if data == "adm_stats":
            total_users = len(db["users"])
            total_links = len(db["monitors"])
            up_links = len([m for m in db["monitors"] if m["status"] == "UP"])
            msg = f"📊 *GLOBAL ADMINISTRATIVE METRICS*\n\n🔹 Total Systems Profiles: {total_users}\n🔹 Registered Targets: {total_links}\n🟢 Synchronized Secure Nodes: {up_links}"
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Return Dashboard", callback_data="adm_home")]]))
        elif data == "adm_grid":
            msg = "🖥️ *GLOBAL TARGET ALLOCATION NETWORKS*:\n\n"
            for m in db["monitors"][:15]:
                status_ico = "🟢" if m["status"] == "UP" else "🔴" if m["status"] == "DOWN" else "⚪"
                msg += f"{status_ico} ID:`{m['id']}` | User:`{m['user_id']}`\n📌 Name: *{m['name']}*\n🌐 `{m['url']}`\n\n"
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Return Dashboard", callback_data="adm_home")]]))
        elif data == "adm_home":
            msg = "⚡ *VIP MASTER CONTROL PANEL* ⚡"
            keyboard = [
                [InlineKeyboardButton("📊 System Global Statistics", callback_data="adm_stats")],
                [InlineKeyboardButton("🖥️ Master Targets Grid", callback_data="adm_grid")]
            ]
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # USER INLINE WORKFLOWS
    user_conf = db["users"].get(uid_str)
    if not user_conf or user_conf.get("banned", False): return

    if data == "usr_grid":
        my_nodes = [m for m in db["monitors"] if m["user_id"] == uid]
        if not my_nodes:
            msg = "⚠️ Your sub-allocation profile contains no active network traces inside the database core."
        else:
            msg = "🖥️ *YOUR OPERATIONAL CHANNELS*:\n\n"
            for m in my_nodes:
                status_ico = "🟢" if m["status"] == "UP" else "🔴" if m["status"] == "DOWN" else "⚪"
                msg += f"{status_ico} *{m['name']}* ({m['uptime']}% Health)\n`{m['url']}`\n⚙️ Active Status: {m['is_active']}\n\n"
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="usr_home")]]))
    elif data == "usr_home":
        client_msg = f"🛡️ *VIP CLIENT MAINFRAME NODE* 🛡️\n\n🚀 Resource Utilization Matrix Panel Loading..."
        keyboard = [
            [InlineKeyboardButton("🖥️ Manage My Target Channels", callback_data="usr_grid")]
        ]
        await query.edit_message_text(client_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

# --- FASTAPI WEB LIFECYCLE MANAGEMENT ---
@asynccontextmanager
async def app_lifespan(app: FastAPI):
    global async_client_pool
    async_client_pool = httpx.AsyncClient(limits=httpx.Limits(max_connections=200, max_keepalive_connections=50))
    
    # Initialize Application Bot Orchestration Layer
    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", bot_start_router))
    bot_app.add_handler(CommandHandler("genkey", cmd_generate_token))
    bot_app.add_handler(CommandHandler("ban", cmd_ban_infrastructure))
    bot_app.add_handler(CommandHandler("unban", cmd_unban_infrastructure))
    bot_app.add_handler(CommandHandler("setlimit", cmd_modify_link_limit))
    bot_app.add_handler(CommandHandler("webkey", cmd_generate_webkey))
    bot_app.add_handler(CommandHandler("backup", cmd_backup_json))
    bot_app.add_handler(CallbackQueryHandler(bot_callback_handler))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_redeem_attempt))
    
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

# --- BACKEND REST API ENDPOINTS CONTROLLERS ---
@app.post("/api/auth/verify")
async def verify_web_key(payload: Dict):
    key = payload.get("key")
    device_id = payload.get("device_id", "web_node")
    if not key: raise HTTPException(status_code=400, detail="Missing Authentication Matrix Key")
    
    # Owner Authorization Check
    if key in db["web_keys"]:
        return {"status": "authorized", "role": "owner", "token": key, "user_id": OWNER_ID}
    
    # Check if Key matches user subscription session token
    for uid_str, udata in db["users"].items():
        if udata.get("banned", False): continue
        # For simplicity, let sub-admins present their Active Redeem Code as Web Key 
        if key in db["redeem_codes"]:
            if device_id not in udata["devices"]:
                if len(udata["devices"]) >= udata["max_devices"]:
                    raise HTTPException(status_code=403, detail="Device Registration Matrix Denied: Hard Hardware Ceiling Hit.")
                udata["devices"].append(device_id)
                await sync_db()
            return {"status": "authorized", "role": "subadmin", "token": key, "user_id": int(uid_str)}
            
    raise HTTPException(status_code=401, detail="Cryptographic Security Check Failure: Unauthorized Key Pattern.")

@app.get("/api/monitors")
async def fetch_api_monitors(user_id: int, role: str):
    if role == "owner":
        return db["monitors"]
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

# --- MASTER DATABASE RE-UPLOAD SYSTEM MANAGEMENT ENDPOINTS ---
@app.post("/api/system/upload_db")
async def system_replace_db(payload: Dict):
    global db
    if payload.get("role") != "owner": raise HTTPException(status_code=403, detail="Access Denied")
    incoming_data = payload.get("database_json")
    if not incoming_data or "users" not in incoming_data or "monitors" not in incoming_data:
        raise HTTPException(status_code=400, detail="Malformed structure schematic architecture framework.")
    db = incoming_data
    await sync_db()
    return {"success": True, "detail": "Core Database structures overwritten successfully matching standard payload schema."}

# --- FULL NEXT-GEN REDESIGNED VIP MATRICES WEB FRONTEND APPLICATION LAYER ---
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
            // Hardware fingerprints mapping strategy
            function fetchHardwareNodeSignature() {
                let sig = localStorage.getItem('matrix_hardware_signature');
                if(!sig) { sig = 'node_hw_' + Math.random().toString(36).substring(2, 15); localStorage.setItem('matrix_hardware_signature', sig); }
                return sig;
            }
        </script>
    </head>
    <body class="min-h-screen relative p-4 flex items-center justify-center">
        <!-- AUTH GATEWAY PROTECTION INTERFACE CONSOLE -->
        <div id="auth-wall-container" class="w-full max-w-md vip-panel p-8 rounded-2xl border-t-4 border-t-purple-600 z-50 relative">
            <div class="text-center mb-6">
                <div class="inline-block p-3 bg-purple-950/40 rounded-full mb-3 border border-purple-500/30">
                    <i class="fa-solid fa-user-shield text-3xl text-purple-400"></i>
                </div>
                <h1 class="text-2xl font-black tracking-widest font-vip text-white text-vip-neon">SECURITY CHECKPOINT</h1>
                <p class="text-[11px] text-gray-500 uppercase tracking-widest mt-1">OPERATOR ENCRYPTED GATEWAY SIGNATURE PERIMETER</p>
            </div>
            <div class="space-y-4">
                <div>
                    <label class="block text-xs font-bold text-purple-400 uppercase mb-1">Enter Master Key or Token Profile</label>
                    <input type="password" id="gateway-security-key" class="w-full crypto-input rounded-xl px-4 py-3 text-xs tracking-widest text-center" placeholder="matrix_key_... or nirobxuptime_...">
                </div>
                <button onclick="attemptPerimeterAuthentication()" class="w-full bg-purple-600 hover:bg-purple-500 text-black font-black py-3 rounded-xl tracking-widest uppercase text-xs font-vip transition-all shadow-lg">VERIFY SCHEMATIC IDENTITY</button>
            </div>
        </div>

        <!-- PRINCIPAL WORKSPACE LOGISTICS MATRIX LAYOUT CONTAINER -->
        <div id="mainframe-application-workspace" class="w-full max-w-6xl mx-auto space-y-6 hidden my-6">
            <header class="vip-panel p-6 rounded-2xl flex flex-col md:flex-row justify-between items-center gap-4 border-l-4 border-l-purple-500">
                <div>
                    <h1 class="text-3xl font-black font-vip text-white tracking-widest text-vip-neon">VIP INTEGRATED SECURITY MATRIX</h1>
                    <p class="text-xs text-gray-500 tracking-wider">SECURED CONTROLS ARCHITECTURE • POWERED BY SPEED_X</p>
                </div>
                <div class="flex items-center gap-3">
                    <span id="role-badge" class="px-4 py-1.5 bg-purple-950/40 border border-purple-500/40 text-purple-300 font-black text-xs uppercase tracking-widest rounded-lg">SUBADMIN CONSOLE ACTIVE</span>
                    <button onclick="destroyLocalSession()" class="px-3 py-1.5 bg-rose-950/40 border border-rose-900/50 hover:border-rose-500 text-rose-400 font-bold text-xs rounded-lg transition-all">TERMINATE ACCESS</button>
                </div>
            </header>

            <!-- OWNER PANELS STORAGE CONFIG BOX EXTENSIONS -->
            <div id="owner-exclusive-operations-box" class="hidden vip-panel p-6 rounded-2xl border border-dashed border-purple-500/40 space-y-4">
                <h2 class="text-xs font-bold text-purple-400 font-vip uppercase tracking-widest"><i class="fa-solid fa-triangle-exclamation mr-1.5"></i> Live Core Infrastructure Maintenance Console Engine</h2>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div class="bg-black/40 border border-purple-950 p-4 rounded-xl">
                        <h3 class="text-xs font-bold text-white mb-2 uppercase">Overwrite/Restore Remote Active JSON Database Structure</h3>
                        <input type="file" id="db-file-picker" accept=".json" class="block w-full text-xs text-gray-400 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-bold file:bg-purple-950 file:text-purple-400 cursor-pointer">
                        <button onclick="commitDatabaseOverrideUpload()" class="mt-3 px-4 py-2 bg-purple-600 hover:bg-purple-500 text-black text-xs font-black rounded-lg uppercase tracking-wider transition-all">EXECUTE FULL SYNC HOT-REPLACE</button>
                    </div>
                    <div class="bg-black/40 border border-purple-950 p-4 rounded-xl flex flex-col justify-between">
                        <h3 class="text-xs font-bold text-white mb-2 uppercase">Dump/Extract Remote Database Matrix Snapshot</h3>
                        <p class="text-[11px] text-gray-500">Extract an instantaneous exact state cryptographic configuration of all active nodes, monitors, profiles, and tickets inside the mainframe database storage layer.</p>
                        <button onclick="triggerDatabaseExportDownload()" class="mt-2 px-4 py-2 border border-purple-500 text-purple-400 hover:bg-purple-950 text-xs font-bold rounded-lg uppercase tracking-wider transition-all">EXTRACT SNAPSHOT BACKUP</button>
                    </div>
                </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <!-- Injection Panel Card -->
                <div class="vip-panel p-6 rounded-2xl space-y-4 h-fit">
                    <h2 class="text-xs font-bold text-white font-vip uppercase tracking-widest flex items-center gap-1.5 text-vip-neon"><i class="fa-solid fa-circle-plus text-purple-400"></i> Inject Operational Vector Target</h2>
                    <div class="space-y-3 text-xs">
                        <div>
                            <label class="block text-gray-400 mb-1 font-bold uppercase">Alias / Name</label>
                            <input type="text" id="target-name" class="w-full crypto-input rounded-lg p-2.5" placeholder="VIP Target API Host">
                        </div>
                        <div>
                            <label class="block text-gray-400 mb-1 font-bold uppercase">Routing URL / Connection Destination</label>
                            <input type="url" id="target-url" class="w-full crypto-input rounded-lg p-2.5" placeholder="https://host.com/health">
                        </div>
                        <div>
                            <label class="block text-gray-400 mb-1 font-bold uppercase">Polling Cycle Schedule Duration</label>
                            <select id="target-interval" class="w-full crypto-input rounded-lg p-2.5 cursor-pointer">
                                <option value="1">1 Minute Sequence Hyper-Pulse</option>
                                <option value="5" selected>5 Minutes Standard Premium Sequence</option>
                                <option value="15">15 Minutes Conservative Allocation Mode</option>
                            </select>
                        </div>
                        <button onclick="injectTargetNodePipeline()" class="w-full py-3 bg-purple-600 hover:bg-purple-500 text-black font-black uppercase tracking-wider rounded-xl font-vip transition-all">DEPLOY ENDPOINT PIPELINE</button>
                    </div>
                </div>

                <!-- Live Monitoring Dynamic Streams Grid Panel Layout -->
                <div class="lg:col-span-2 vip-panel p-6 rounded-2xl space-y-4">
                    <h2 class="text-xs font-bold text-white font-vip uppercase tracking-widest flex items-center gap-1.5 text-vip-neon"><i class="fa-solid fa-network-wired text-purple-400"></i> LIVE DESIGNATED NETWORK CHANNELS TARGET TRACKS GRID</h2>
                    <div id="channels-grid-container" class="grid grid-cols-1 md:grid-cols-2 gap-4 max-h-[500px] overflow-y-auto pr-2"></div>
                </div>
            </div>
        </div>

        <script>
            let sessionState = { token: "", role: "", user_id: null };

            async function attemptPerimeterAuthentication() {
                const key = document.getElementById("gateway-security-key").value.trim();
                if(!key) return alert("Access Key Required.");
                const devId = fetchHardwareNodeSignature();
                try {
                    const res = await fetch("/api/auth/verify", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ key: key, device_id: devId })
                    });
                    if(!res.ok) { const err = await res.json(); alert(err.detail || "Authentication Refused."); return; }
                    
                    const data = await res.json();
                    sessionState.token = data.token;
                    sessionState.role = data.role;
                    sessionState.user_id = data.user_id;

                    document.getElementById("auth-wall-container").classList.add("hidden");
                    const appWorkspace = document.getElementById("mainframe-application-workspace");
                    appWorkspace.classList.remove("hidden");
                    
                    document.getElementById("role-badge").innerText = `${data.role.toUpperCase()} CORE ACCESS`;
                    if(data.role === "owner") {
                        document.getElementById("owner-exclusive-operations-box").classList.remove("hidden");
                    }
                    synchronizeChannelsGrid();
                    setInterval(synchronizeChannelsGrid, 10000);
                } catch(e) { alert("Matrix Core Connection Exception Refused System Network Entry."); }
            }

            async function synchronizeChannelsGrid() {
                try {
                    const res = await fetch(`/api/monitors?user_id=${sessionState.user_id}&role=${sessionState.role}`);
                    const data = await res.json();
                    const container = document.getElementById("channels-grid-container");
                    container.innerHTML = data.length === 0 ? '<div class="text-xs text-gray-600 col-span-2 text-center p-12 tracking-widest">NO SIGNALS ROUTED TO CURRENT MATRIX PIPELINE.</div>' : '';
                    
                    data.forEach(m => {
                        const div = document.createElement("div");
                        let isUp = m.status === 'UP';
                        let borderStyle = isUp ? 'border-l-emerald-500 vip-glow-glow' : m.status === 'DOWN' ? 'border-l-rose-500' : 'border-l-gray-600';
                        div.className = `vip-panel p-4 rounded-xl border-l-4 ${borderStyle} text-xs space-y-2 transition-all`;
                        div.innerHTML = `
                            <div class="flex justify-between items-start">
                                <div>
                                    <h4 class="font-bold text-white tracking-wide uppercase">${m.name} <span class="text-purple-500 font-mono">[${m.status_code}]</span></h4>
                                    <p class="text-[11px] text-purple-400/60 break-all select-all mt-0.5">${m.url}</p>
                                </div>
                                <span class="px-2 py-0.5 text-[9px] font-black tracking-widest rounded border ${isUp ? 'bg-emerald-950/40 text-emerald-400 border-emerald-500/20' : 'bg-rose-950/40 text-rose-400 border-rose-500/20'}">${m.status}</span>
                            </div>
                            <div class="grid grid-cols-2 gap-2 bg-black/40 border border-purple-950/30 p-2 rounded text-[11px] text-gray-400">
                                <div>Latency: <span class="text-purple-400 font-bold">${m.response_time}ms</span></div>
                                <div>Health Metrics: <span class="text-white font-bold">${m.uptime}%</span></div>
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
                if(!name || !url) return alert("All profile properties must be specified prior to pipeline initialization.");
                
                const res = await fetch("/api/monitors", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ user_id: sessionState.user_id, role: sessionState.role, name, url, interval })
                });
                if(res.ok) {
                    document.getElementById("target-name").value = "";
                    document.getElementById("target-url").value = "";
                    synchronizeChannelsGrid();
                } else { const err = await res.json(); alert(err.detail || "Injection Refused."); }
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
                if(confirm("Are you sure you want to terminate this endpoint channel sequence?")) {
                    await fetch(`/api/monitors/${mid}?user_id=${sessionState.user_id}&role=${sessionState.role}`, { method: "DELETE" });
                    synchronizeChannelsGrid();
                }
            }

            function destroyLocalSession() { window.location.reload(); }

            async function triggerDatabaseExportDownload() {
                const res = await fetch(`/api/monitors?user_id=${sessionState.user_id}&role=${sessionState.role}`);
                const monitorsList = await res.json();
                const blob = new Blob([JSON.stringify({users: {}, monitors: monitorsList, redeem_codes: {}, web_keys: []}, null, 4)], {type : 'application/json'});
                const anchor = document.createElement('a'); anchor.href = URL.createObjectURL(blob);
                anchor.download = "matrix_snapshot_backup.json"; anchor.click(); anchor.remove();
            }

            function commitDatabaseOverrideUpload() {
                const filePicker = document.getElementById("db-file-picker");
                if(filePicker.files.length === 0) return alert("Select a template JSON structural matrix configuration payload asset array first.");
                const fileReader = new FileReader();
                fileReader.onload = async function(e) {
                    try {
                        const dataObj = JSON.parse(e.target.result);
                        const res = await fetch("/api/system/upload_db", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ role: sessionState.role, token: sessionState.token, database_json: dataObj })
                        });
                        if(res.ok) { alert("Core Database registries completely replaced and synchronized successfully."); synchronizeChannelsGrid(); }
                        else { alert("Internal Error executing file replacement override layer mapping pipeline."); }
                    } catch(err) { alert("JSON structural framing error compilation syntax failure analysis rejected."); }
                };
                fileReader.readAsText(filePicker.files[0]);
            }
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
