# ==============================================================================
# Created by SPEED_X / NIROB BBZ
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
from typing import Dict
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

BOT_TOKEN = "8853802336:AAH0nWjUSvB7wBOeBsSuwMURBQdRQk4vznU"
OWNER_ID = 7224513731
DB_FILE = "matrix_database.json"

def load_db() -> Dict:
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f: return json.load(f)
        except Exception: pass
    return {"users": {}, "monitors": [], "redeem_codes": {}, "web_keys": []}

def save_db(data: Dict):
    try:
        with open(DB_FILE, "w") as f: json.dump(data, f, indent=4)
    except Exception as e: print(f"[!] DB Save Error: {e}")

db = load_db()
db_lock = asyncio.Lock()

async def sync_db():
    async with db_lock: save_db(db)

async_client_pool: httpx.AsyncClient = None

# --- ENGINE BACKGROUND CHECKERS ---
async def check_target_pulse(monitor: Dict):
    start_time = time.time()
    url = monitor['url']
    if not url.startswith(('http://', 'https://')): url = 'https://' + url
    try:
        response = await async_client_pool.get(url, timeout=10.0, follow_redirects=True)
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
        monitor['last_check'] = time.strftime("%H:%M:%S", time.localtime())
        if monitor['total_checks'] > 0:
            monitor['uptime'] = round((monitor['success_checks'] / monitor['total_checks']) * 100, 2)

async def core_monitor_scheduler():
    while True:
        tasks = []
        current_time = time.time()
        for m in db["monitors"]:
            uid = str(m['user_id'])
            user_info = db["users"].get(uid, {})
            if user_info.get("banned", False) or (user_info.get("expiry") != "lifetime" and user_info.get("expiry", 0) < current_time):
                m['is_active'] = False
                m['status'] = 'SUSPENDED'
                continue
            if m.get('is_active', True):
                last_run = m.get('_last_run_timestamp', 0)
                if current_time - last_run >= (m.get('interval', 5) * 60):
                    m['_last_run_timestamp'] = current_time
                    tasks.append(check_target_pulse(m))
        if tasks:
            await asyncio.gather(*tasks)
            await sync_db()
        await asyncio.sleep(3)

# --- 100% SMART BUTTON CONTROLLER ENGINE ---
async def launch_main_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid_str = str(user.id)
    current_time = time.time()

    if db["users"].get(uid_str, {}).get("banned", False):
        await update.message.reply_text("❌ UNKNOWN EXCLUSION: ACCESS COMPROMISED.")
        return

    # 👑 OWNER VIP PORTAL BUTTONS
    if user.id == OWNER_ID:
        msg = "⚡ *SPEED_X CENTRAL SECURITY INFRASTRUCTURE* ⚡\n\n[OWNER MODE ACTIVE]\nবটের সমস্ত ইন্টারফেস নিচে থাকা ফিজিক্যাল বাটন দিয়ে রিয়েল-টাইম কন্ট্রোল করুন।"
        keyboard = [
            [InlineKeyboardButton("🎫 GEN REDEEM KEY", callback_data="own_step1_time"), InlineKeyboardButton("👥 MANAGED USERS", callback_data="own_users_list")],
            [InlineKeyboardButton("📊 QUICK STATUS", callback_data="own_quick_status"), InlineKeyboardButton("🔑 LIVE WEB TOKEN", callback_data="own_webkey")],
            [InlineKeyboardButton("💾 BACKUP DATABASE", callback_data="own_backup_db"), InlineKeyboardButton("🔄 RESTART CORE", callback_data="own_restart_core")]
        ]
        if update.message: await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        else: await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # 👤 CLIENT PORTAL ROUTER
    user_data = db["users"].get(uid_str)
    if not user_data or (user_data["expiry"] != "lifetime" and user_data["expiry"] < current_time):
        msg = f"🛸 *VIP UPTIME MATRIX PLATFORM* 🛸\n\n⚠️ Unauthorized Node: `{user.id}`\nলাইসেন্স কি ভেরিফাই করুন অথবা এডমিনের সাথে যোগাযোগ করুন।"
        keyboard = [
            [InlineKeyboardButton("🛒 BUY PREMIUM LICENSE", url="https://t.me/NIROB_BBZ")],
            [InlineKeyboardButton("🔑 ENTER REDEEM CODE", callback_data="usr_trigger_redeem")]
        ]
        if update.message: await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        else: await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # PRE-CALCULATED USER INTERFACES (SMOOTH BUTTONS POOL)
    my_links = [m for m in db["monitors"] if m["user_id"] == user.id]
    exp_text = "LIFETIME" if user_data["expiry"] == "lifetime" else time.strftime("%Y-%m-%d", time.localtime(user_data["expiry"]))
    
    msg = (
        f"🛡️ *MAINFRAME CLIENT CONTROLLER* 🛡️\n\n"
        f"👤 *Profile:* `{user.first_name}`\n"
        f"📅 *Valid Until:* `{exp_text}`\n"
        f"🚀 *Capacity Load:* `{len(my_links)}/{user_data['link_limit']}` Links"
    )
    keyboard = [
        [InlineKeyboardButton("➕ ADD TARGET LINK", callback_data="usr_add_link"), InlineKeyboardButton("❌ REMOVE TRACK LINK", callback_data="usr_remove_select")],
        [InlineKeyboardButton("⚙️ TOGGLE ACTIVE STATE", callback_data="usr_toggle_select"), InlineKeyboardButton("📊 CURRENT STREAM STATS", callback_data="usr_view_stats")],
        [InlineKeyboardButton("🔄 REFRESH PANEL", callback_data="usr_home_return")]
    ]
    if update.message: await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    else: await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def catch_all_messages_and_redeems(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid_str = str(user.id)
    text = update.message.text.strip()
    state = context.user_data.get("state")
    
    if state == "WAITING_REDEEM_CODE":
        if text.startswith("nirobxuptime_"):
            code_data = db["redeem_codes"].get(text)
            if not code_data or code_data.get("used", False):
                await update.message.reply_text("❌ Token signature corrupted or already exhausted.")
                return
            db["users"][uid_str] = {
                "expiry": "lifetime" if code_data["days"] == 0 else time.time() + (code_data["days"] * 86400),
                "link_limit": code_data["link_limit"], "max_devices": code_data["max_devices"], "devices": [], "banned": False
            }
            code_data["used"] = True
            await sync_db()
            context.user_data["state"] = None
            await update.message.reply_text("🧬 *PREMIUM CORE LICENSE GRANTED SUCCESSFULLY!*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 OPEN DASHBOARD", callback_data="usr_home_return")]]))
        return

    if state == "WAITING_LINK_INPUT":
        context.user_data["temp_url"] = text
        context.user_data["state"] = "WAITING_NAME_INPUT"
        await update.message.reply_text("✏️ এখন লিংকটির একটি নাম বা **Alias Tag** টাইপ করে পাঠান:")
        return

    if state == "WAITING_NAME_INPUT":
        url = context.user_data.get("temp_url")
        name = text
        context.user_data["temp_name"] = name
        
        keyboard = [
            [InlineKeyboardButton("⚡ 1 Minute Pulse", callback_data="cfg_interval_1")],
            [InlineKeyboardButton("🚀 5 Minutes Standard", callback_data="cfg_interval_5")],
            [InlineKeyboardButton("🐢 15 Minutes Stable", callback_data="cfg_interval_15")]
        ]
        context.user_data["state"] = None
        await update.message.reply_text("⏱️ লিংকের মনিটরিং ইন্টারভাল বা পোলিং সাইকেল সিলেক্ট করুন (বাটন দিয়ে):", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if state == "WAITING_CUSTOM_LIMIT" and user.id == OWNER_ID:
        t_user = context.user_data.get("target_user")
        try:
            db["users"][t_user]["link_limit"] = int(text)
            await sync_db()
            context.user_data["state"] = None
            await update.message.reply_text(f"✅ User ID {t_user} এর লিংক লিমিট আপডেট করা হয়েছে।", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="own_users_list")]]))
        except ValueError: await update.message.reply_text("সঠিক সংখ্যা টাইপ করুন।")
        return

    await launch_main_dashboard(update, context)

# --- COMPLEX INTERACTIVE CALLBACK DISPATCHER ---
async def interface_buttons_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    uid_str = str(uid)
    data = query.data

    if data == "usr_home_return" or data == "own_main_panel":
        context.user_data["state"] = None
        await launch_main_dashboard(update, context)
        return

    if data == "usr_trigger_redeem":
        context.user_data["state"] = "WAITING_REDEEM_CODE"
        await query.edit_message_text("🔑 *INPUT MODE ACTIVE:*\nআপনার ভ্যালিডেশন কোডটি চ্যাটে টাইপ করুন (`nirobxuptime_*******`):", parse_mode="Markdown")
        return

    if data == "usr_add_link":
        user_info = db["users"].get(uid_str, {})
        existing = [m for m in db["monitors"] if m["user_id"] == uid]
        if len(existing) >= user_info.get("link_limit", 0):
            await query.edit_message_text("❌ আপনার লিংক ক্যাপাসিটি ফুল হয়ে গেছে! কাস্টম লিমিট বাড়াতে ওনারের সাথে যোগাযোগ করুন।", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="usr_home_return")]]))
            return
        context.user_data["state"] = "WAITING_LINK_INPUT"
        await query.edit_message_text("🌐 অনুগ্রহ করে আপনার টার্গেট **URL/Link** টি চ্যাটে টাইপ করুন:")
        return

    if data.startswith("cfg_interval_"):
        interval = int(data.split("_")[2])
        url = context.user_data.get("temp_url")
        name = context.user_data.get("temp_name")
        
        new_node = {
            "id": secrets.token_hex(4), "user_id": uid, "name": name, "url": url, "interval": interval,
            "status": "PENDING", "response_time": 0, "status_code": "N/A", "uptime": 100.0, "success_checks": 0, "total_checks": 0, "is_active": True, "_last_run_timestamp": 0
        }
        db["monitors"].append(new_node)
        await sync_db()
        await query.edit_message_text(f"✅ *SUCCESSFULLY DEPLOYED!*\nটার্গেট `{name}` ডাটাবেসে ইনজেক্ট করা হয়েছে।", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 BACK DASHBOARD", callback_data="usr_home_return")]]))
        return

    if data == "usr_remove_select" or data == "usr_toggle_select":
        my_links = [m for m in db["monitors"] if m["user_id"] == uid]
        if not my_links:
            await query.edit_message_text("⚠️ আপনার কোনো লিংক এখনো সিস্টেমে রেজিস্টার্ড নেই।", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="usr_home_return")]]))
            return
        action = "del" if "remove" in data else "tgl"
        keyboard = []
        for m in my_links:
            status_ico = "🟢" if m["status"] == "UP" else "🔴" if m["status"] == "DOWN" else "⚪"
            keyboard.append([InlineKeyboardButton(f"{status_ico} {m['name']} ({m['url'][:20]}...)", callback_data=f"usr_exec_{action}_{m['id']}")])
        keyboard.append([InlineKeyboardButton("⬅️ Back Dashboard", callback_data="usr_home_return")])
        await query.edit_message_text("🎯 অ্যাকশন পারফর্ম করতে নিচের যেকোনো একটি লিংক বাটন সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("usr_exec_del_"):
        mid = data.split("_")[3]
        db["monitors"] = [m for m in db["monitors"] if not (m["id"] == mid and m["user_id"] == uid)]
        await sync_db()
        await query.edit_message_text("🗑️ লিংকটি আপনার ম্যাট্রিক্স স্ট্রিম থেকে সম্পূর্ণ ডিলিট করা হয়েছে।", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back Menu", callback_data="usr_home_return")]]))
        return

    if data.startswith("usr_exec_tgl_"):
        mid = data.split("_")[3]
        for m in db["monitors"]:
            if m["id"] == mid and m["user_id"] == uid:
                m["is_active"] = not m["is_active"]
                m["status"] = "PENDING" if m["is_active"] else "STOPPED"
                await sync_db()
                break
        await query.edit_message_text("⚙️ লিংকের একটিভ স্ট্যাটাস সফলভাবে টগল (অন/অফ) করা হয়েছে।", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back Menu", callback_data="usr_home_return")]]))
        return

    if data == "usr_view_stats":
        my_links = [m for m in db["monitors"] if m["user_id"] == uid]
        if not my_links:
            await query.edit_message_text("⚠️ কোনো লাইভ সিগন্যাল পাওয়া যায়নি।", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="usr_home_return")]]))
            return
        msg = "📊 *LIVE REALTIME PIPELINES TARGETS REPORT*:\n\n"
        for m in my_links:
            status_ico = "🟢 UP" if m["status"] == "UP" else "🔴 DOWN" if m["status"] == "DOWN" else "⚪ PAUSED"
            msg += f"🖥️ *Name:* `{m['name']}`\n🌐 *URL:* `{m['url']}`\n🚦 *Status:* `{status_ico}` | ⏱️ *Ping:* `{m['response_time']}ms` | 📈 *Health:* `{m['uptime']}%` \n\n"
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back Dashboard", callback_data="usr_home_return")]]))
        return

    # --- OWNER ENGINE ACTIONS ---
    if uid != OWNER_ID: return

    if data == "own_quick_status":
        msg = f"📊 *GLOBAL SYSTEM REALTIME STATS*:\n\nTotal Registered Nodes: `{len(db['monitors'])}` Total Profiles: `{len(db['users'])}` \n\n"
        for m in db["monitors"]:
            status_ico = "🟢" if m["status"] == "UP" else "🔴"
            msg += f"{status_ico} User: `{m['user_id']}` | `{m['name']}` $\rightarrow$ `{m['uptime']}%`\n"
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="own_main_panel")]]))
        return

    if data == "own_restart_core":
        await query.edit_message_text("🔄 Core Engine Refreshing Processes Started Successfully...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="own_main_panel")]]))
        return

    if data == "own_webkey":
        wkey = f"matrix_key_{secrets.token_urlsafe(16)}"
        db["web_keys"].append(wkey)
        await sync_db()
        await query.edit_message_text(f"🔑 *LIVE NEW WEB SECURITY TOKEN:*\n\n`{wkey}`\n\nওয়েবসাইটে লগইন করতে এই টোকেনটি ব্যবহার করুন।", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back Menu", callback_data="own_main_panel")]]))
        return

    if data == "own_backup_db":
        await sync_db()
        if os.path.exists(DB_FILE):
            with open(DB_FILE, 'rb') as doc:
                await context.bot.send_document(chat_id=OWNER_ID, document=doc, filename="matrix_database.json", caption="⚡ Live State Complete Database Transmitted Securely.")
            await query.edit_message_text("✅ Backup file database completely dumped into your private room channel.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="own_main_panel")]]))
        return

    if data == "own_step1_time":
        keyboard = [
            [InlineKeyboardButton("🗓️ 30 Days Cycle", callback_data="own_step2_links_30")],
            [InlineKeyboardButton("🗓️ 90 Days Cycle", callback_data="own_step2_links_90")],
            [InlineKeyboardButton("👑 LIFETIME UNLIMITED", callback_data="own_step2_links_0")]
        ]
        await query.edit_message_text("⚡ *KEY GENERATION [STAGE 1]*:\nলাইসেন্সের মেয়াদ সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("own_step2_links_"):
        days = data.split("_")[3]
        keyboard = [
            [InlineKeyboardButton("🚀 5 Links", callback_data=f"own_step3_devs_{days}_5")],
            [InlineKeyboardButton("🚀 15 Links", callback_data=f"own_step3_devs_{days}_15")],
            [InlineKeyboardButton("🚀 50 Links Max", callback_data=f"own_step3_devs_{days}_50")]
        ]
        await query.edit_message_text("⚡ *KEY GENERATION [STAGE 2]*:\nলিংক ট্র্যাকিং ক্যাপাসিটি লিমিট চুজ করুন:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("own_step3_devs_"):
        parts = data.split("_")
        days, links = int(parts[3]), int(parts[4])
        token = f"nirobxuptime_{secrets.token_hex(4).upper()}"
        db["redeem_codes"][token] = {"days": days, "link_limit": links, "max_devices": 3, "used": False}
        await sync_db()
        
        duration_text = "LIFETIME REIGN" if days == 0 else f"{days} Days"
        await query.edit_message_text(f"🎫 *VIP QUANTUM TICKET GENERATED* 🎫\n\n`{token}`\n\n🔹 Duration: {duration_text}\n🔹 Monitor Capacity: {links} Tracks", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back Main Dashboard", callback_data="own_main_panel")]]))
        return

    if data == "own_users_list":
        if not db["users"]:
            await query.edit_message_text("⚠️ ডাটাবেসে কোনো একটিভ প্রোফাইল রেকর্ড মেলেনি।", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="own_main_panel")]]))
            return
        keyboard = []
        for uid_key, ucon in db["users"].items():
            ban_status_label = "🚫 BANNED" if ucon.get("banned") else "🟢 ACTIVE"
            keyboard.append([InlineKeyboardButton(f"ID: {uid_key} [{ban_status_label}]", callback_data=f"own_manageuser_{uid_key}")])
        keyboard.append([InlineKeyboardButton("⬅️ Back Dashboard Menu", callback_data="own_main_panel")])
        await query.edit_message_text("👥 *MASTER SYSTEM MANAGEMENT PROFILES LEDGER*:\nযেকোনো ইউজারের উপর অ্যাকশন নিতে সিলেক্ট করুন:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("own_manageuser_"):
        t_uid = data.split("_")[2]
        ucon = db["users"].get(t_uid, {})
        my_links = [m for m in db["monitors"] if m["user_id"] == int(t_uid)]
        msg = (
            f"👤 *PROFILE MAINTENANCE INTERFACE* 👤\n\n"
            f"🔹 User Core ID: `{t_uid}`\n"
            f"🔹 Status: `{'🚫 BANNED' if ucon.get('banned') else '🟢 ACTIVE'}`\n"
            f"🔹 Config Limit Trace Ceiling: `{ucon.get('link_limit')}` Links\n"
            f"🔹 Total Channels Mapped: `{len(my_links)}` Objects"
        )
        keyboard = [
            [InlineKeyboardButton("🚫 INSTANT BAN", callback_data=f"own_execban_{t_uid}"), InlineKeyboardButton("🔓 REMOVE BAN", callback_data=f"own_execunban_{t_uid}")],
            [InlineKeyboardButton("⚙️ ADJUST MAX LINK CAPACITY", callback_data=f"own_execlimit_{t_uid}")],
            [InlineKeyboardButton("⬅️ Back List Ledger", callback_data="own_users_list")]
        ]
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("own_execban_") or data.startswith("own_execunban_"):
        t_uid = data.split("_")[2]
        db["users"][t_uid]["banned"] = True if "execban" in data else False
        await sync_db()
        query.data = f"own_manageuser_{t_uid}"
        await interface_buttons_dispatcher(update, context)
        return

    if data.startswith("own_execlimit_"):
        t_uid = data.split("_")[2]
        context.user_data["state"] = "WAITING_CUSTOM_LIMIT"
        context.user_data["target_user"] = t_uid
        await query.edit_message_text(f"🔢 User ID `{t_uid}` এর জন্য নতুন কাস্টম লিংক লিমিট সংখ্যাটি টাইপ করে চ্যাটে পাঠান:", parse_mode="Markdown")
        return

# --- FASTAPI WEB BACKEND RUNNERS ---
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

@app.post("/api/auth/verify")
async def verify_web_key(payload: dict):
    key = payload.get("key")
    if not key: raise HTTPException(status_code=400, detail="Missing Security Key Token")
    if key in db["web_keys"]: return {"status": "authorized", "role": "owner", "token": key, "user_id": OWNER_ID}
    raise HTTPException(status_code=401, detail="Security Firewall Refusal: Invalid Key.")

@app.get("/api/monitors")
async def fetch_api_monitors(user_id: int, role: str):
    if role == "owner": return db["monitors"]
    return [m for m in db["monitors"] if m["user_id"] == user_id]

@app.post("/api/monitors")
async def create_api_monitor(payload: dict):
    new_node = {
        "id": secrets.token_hex(4), "user_id": int(payload["user_id"]), "name": payload["name"], "url": payload["url"],
        "interval": int(payload["interval"]), "status": "PENDING", "response_time": 0, "status_code": "N/A", "uptime": 100.0, "success_checks": 0, "total_checks": 0, "is_active": True, "_last_run_timestamp": 0
    }
    db["monitors"].append(new_node)
    await sync_db()
    return new_node

@app.post("/api/monitors/{mid}/toggle")
async def toggle_api_monitor(mid: str):
    for m in db["monitors"]:
        if m["id"] == mid:
            m["is_active"] = not m["is_active"]
            m["status"] = "PENDING" if m["is_active"] else "STOPPED"
            await sync_db()
            return m
    raise HTTPException(status_code=404, detail="Node missing")

@app.delete("/api/monitors/{mid}")
async def delete_api_monitor(mid: str):
    global db
    db["monitors"] = [m for m in db["monitors"] if m["id"] != mid]
    await sync_db()
    return {"success": True}

# --- EXTENDED DESIGN NEXT-GEN PREMIUM WEB INTERFACE ---
@app.get("/", response_class=HTMLResponse)
async def deliver_nextgen_ui():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>SPEED_X VIP • MAINFRAME ENGINE SECURITY TERMINAL</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
        <!-- Google Fonts Orbitron & Space Mono -->
        <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
        
        <style>
            body {
                background-color: #030307;
                color: #e2e8f0;
                font-family: 'Space Mono', monospace;
                overflow-x: hidden;
            }
            .font-vip-hacker { font-family: 'Orbitron', sans-serif; }
            #particles-js {
                position: fixed; width: 100%; height: 100%; top: 0; left: 0; z-index: 1; pointer-events: none;
            }
            .vip-glass-card {
                background: rgba(10, 10, 22, 0.75);
                backdrop-filter: blur(12px);
                border: 1px solid rgba(168, 85, 247, 0.2);
                box-shadow: 0 0 35px rgba(0, 0, 0, 0.7), inset 0 0 15px rgba(168, 85, 247, 0.05);
            }
            .neon-glow-text {
                text-shadow: 0 0 10px rgba(168, 85, 247, 0.6), 0 0 20px rgba(168, 85, 247, 0.3);
            }
            .neon-glow-green {
                text-shadow: 0 0 10px rgba(16, 185, 129, 0.6);
            }
            .hacker-input {
                background: rgba(0, 0, 0, 0.6) !important;
                border: 1px solid rgba(168, 85, 247, 0.3);
                transition: all 0.3s ease;
            }
            .hacker-input:focus {
                border-color: #a855f7;
                box-shadow: 0 0 15px rgba(168, 85, 247, 0.5);
                outline: none;
            }
            ::-webkit-scrollbar { width: 6px; }
            ::-webkit-scrollbar-track { background: #030307; }
            ::-webkit-scrollbar-thumb { background: #a855f7; border-radius: 10px; }
        </style>
    </head>
    <body class="min-h-screen p-4 flex flex-col items-center justify-center relative">
        
        <!-- Live Particles Canvas Background Overlay -->
        <div id="particles-js"></div>

        <!-- AUTH OVERLAY GATEWAY SCREEN -->
        <div id="security-gateway-auth-box" class="w-full max-w-md vip-glass-card p-8 rounded-2xl border-t-4 border-purple-500 z-10 text-center relative">
            <div class="mb-4">
                <i class="fa-solid fa-terminal text-4xl text-purple-500 animate-pulse mb-2"></i>
                <h1 class="text-2xl font-black font-vip-hacker tracking-widest text-white neon-glow-text">SPEED_X MAINFRAME</h1>
                <p class="text-[10px] text-purple-400 uppercase tracking-widest mt-1">Authorized Protocol Intercept Verification Required</p>
            </div>
            <div class="space-y-4 pt-4">
                <input type="password" id="auth-passkey" class="w-full hacker-input rounded-xl px-4 py-3 text-xs tracking-widest text-center text-white font-mono" placeholder="ENTER MAINFRAME KEY">
                <button onclick="runSystemVerificationGate()" class="w-full bg-purple-600 hover:bg-purple-500 text-black font-black font-vip-hacker py-3 rounded-xl tracking-widest uppercase text-xs transition-all duration-300 transform hover:scale-[1.02]">BYPASS GATEWAY</button>
            </div>
        </div>

        <!-- PRINCIPAL APPLICATION ENGINE CONTROL MAIN AREA PANEL -->
        <div id="mainframe-workspace-app" class="w-full max-w-6xl mx-auto space-y-6 hidden z-10 my-6">
            <header class="vip-glass-card p-6 rounded-2xl flex flex-col md:flex-row justify-between items-center gap-4 border-l-4 border-purple-500 shadow-2xl">
                <div>
                    <h1 class="text-3xl font-black font-vip-hacker text-white tracking-widest neon-glow-text">SPEED_X VIP SERVER CENTRAL MATRIX</h1>
                    <p class="text-xs text-purple-400 tracking-widest uppercase mt-0.5">Automated Realtime Signal Trackers Network Grid Layer</p>
                </div>
                <div class="flex items-center gap-4">
                    <span id="role-badge" class="px-4 py-2 bg-purple-950/40 border border-purple-500/40 text-purple-300 font-bold text-xs uppercase tracking-widest rounded-xl">SUBADMIN VERIFIED</span>
                    <button onclick="window.location.reload()" class="px-4 py-2 bg-red-950/30 border border-red-900/60 hover:border-red-500 text-red-400 font-bold text-xs rounded-xl transition-all duration-300">DISCONNECT</button>
                </div>
            </header>

            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <!-- INJECTION CONTROLS ENGINE FORM PANEL -->
                <div class="vip-glass-card p-6 rounded-2xl space-y-4 h-fit">
                    <h2 class="text-sm font-bold text-white font-vip-hacker uppercase tracking-widest flex items-center gap-2 text-vip-neon"><i class="fa-solid fa-circle-nodes text-purple-500 animate-spin"></i> Inject Monitor Target</h2>
                    <hr class="border-purple-950">
                    <div class="space-y-4 text-xs">
                        <div>
                            <label class="block text-purple-400 mb-1.5 font-bold uppercase tracking-wider">Alias Tag / Name</label>
                            <input type="text" id="node-name" class="w-full hacker-input rounded-xl p-3 text-white" placeholder="Production Core Server">
                        </div>
                        <div>
                            <label class="block text-purple-400 mb-1.5 font-bold uppercase tracking-wider">Target Domain Routing Destination</label>
                            <input type="url" id="node-url" class="w-full hacker-input rounded-xl p-3 text-white" placeholder="https://my-app.render.com">
                        </div>
                        <div>
                            <label class="block text-purple-400 mb-1.5 font-bold uppercase tracking-wider">Pulse Internal Interval Cycle</label>
                            <select id="node-interval" class="w-full hacker-input rounded-xl p-3 text-white cursor-pointer">
                                <option value="1">1 Minute Hyper Polling Frequency</option>
                                <option value="5" selected>5 Minutes Standard Routine Engine</option>
                                <option value="15">15 Minutes Long Term Stable Routine</option>
                            </select>
                        </div>
                        <button onclick="executeTargetPipelineInjection()" class="w-full py-3.5 bg-purple-600 hover:bg-purple-500 text-black font-black uppercase tracking-widest rounded-xl font-vip-hacker transition-all duration-300 shadow-lg shadow-purple-950/40">INITIALIZE TRACK CHANNEL</button>
                    </div>
                </div>

                <!-- REALTIME TARGET PIPELINE DISPLAY GRID SYSTEM LAYOUTS -->
                <div class="lg:col-span-2 vip-glass-card p-6 rounded-2xl space-y-4">
                    <div class="flex justify-between items-center">
                        <h2 class="text-sm font-bold text-white font-vip-hacker uppercase tracking-widest flex items-center gap-2 text-vip-neon"><i class="fa-solid fa-network-wired text-purple-500"></i> Active Tracks Operational Grid Matrix</h2>
                        <span id="total-nodes-counter" class="text-xs bg-purple-950 border border-purple-500/30 text-purple-400 px-2.5 py-1 rounded-md font-mono">TRACKS: 0</span>
                    </div>
                    <hr class="border-purple-950">
                    <div id="channels-grid-container" class="grid grid-cols-1 md:grid-cols-2 gap-4 max-h-[550px] overflow-y-auto pr-2"></div>
                </div>
            </div>
        </div>

        <!-- Injecting Client-Side Particles.js Production Dependency Library -->
        <script src="https://cdn.jsdelivr.net/npm/particles.js@2.0.0/particles.min.js"></script>
        <script>
            // Initialize Core VIP Hacker Cyber Background Aesthetics
            particlesJS("particles-js", {
                "particles": {
                    "number": { "value": 45, "density": { "enable": true, "value_area": 800 } },
                    "color": { "value": "#a855f7" },
                    "shape": { "type": "circle" },
                    "opacity": { "value": 0.25, "random": true },
                    "size": { "value": 2, "random": true },
                    "line_linked": { "enable": true, "distance": 150, "color": "#a855f7", "opacity": 0.15, "width": 1 },
                    "move": { "enable": true, "speed": 1.5, "direction": "none", "random": true, "straight": false, "out_mode": "out" }
                },
                "interactivity": { "detect_on": "canvas", "events": { "onhover": { "enable": true, "mode": "grab" } } },
                "retina_detect": true
            });

            let activeSession = { token: "", role: "", user_id: null };

            async function runSystemVerificationGate() {
                const passkey = document.getElementById("auth-passkey").value.trim();
                if(!passkey) return alert("Security access passphrase mandatory.");
                try {
                    const res = await fetch("/api/auth/verify", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ key: passkey })
                    });
                    if(!res.ok) { alert("Access Denied: Firewall Key Signature Corrupted."); return; }
                    const data = await res.json();
                    activeSession.token = data.token;
                    activeSession.role = data.role;
                    activeSession.user_id = data.user_id;

                    document.getElementById("security-gateway-auth-box").classList.add("hidden");
                    document.getElementById("mainframe-workspace-app").classList.remove("hidden");
                    document.getElementById("role-badge").innerText = `${data.role.toUpperCase()} ENGINE LEVEL`;

                    syncRealtimeGridData();
                    setInterval(syncRealtimeGridData, 5000); // Super fast 5s automatic update pulse
                } catch(e) { alert("Network interface failure."); }
            }

            async function syncRealtimeGridData() {
                try {
                    const res = await fetch(`/api/monitors?user_id=${activeSession.user_id}&role=${activeSession.role}`);
                    const data = await res.json();
                    document.getElementById("total-nodes-counter").innerText = `TRACKS: ${data.length}`;
                    const container = document.getElementById("channels-grid-container");
                    container.innerHTML = data.length === 0 ? '<div class="text-xs text-gray-600 col-span-2 text-center p-16 tracking-widest uppercase">No stream packets routing to terminal grids.</div>' : '';

                    data.forEach(m => {
                        const div = document.createElement("div");
                        const isUp = m.status === "UP";
                        div.className = `vip-glass-card p-5 rounded-xl border-l-4 ${isUp ? 'border-l-emerald-500 shadow-emerald-950/20' : m.status === 'STOPPED' ? 'border-l-yellow-600':'border-l-rose-600 shadow-rose-950/20'} flex flex-col justify-between space-y-3 transition-all duration-300 hover:translate-y-[-2px]`;
                        div.innerHTML = `
                            <div>
                                <div class="flex justify-between items-start gap-2">
                                    <h4 class="font-bold text-white tracking-wide uppercase font-vip-hacker truncate">${m.name}</h4>
                                    <span class="px-2.5 py-0.5 text-[9px] font-black tracking-widest rounded border ${isUp ? 'bg-emerald-950/50 text-emerald-400 border-emerald-500/20 neon-glow-green' : 'bg-rose-950/50 text-rose-400 border-rose-500/20'}">${m.status}</span>
                                    <span class="text-[10px] text-purple-400 bg-black/50 px-1.5 py-0.5 rounded font-mono">[${m.status_code}]</span>
                                </div>
                                <p class="text-[10px] text-gray-500 break-all mt-1 font-mono select-text">${m.url}</p>
                            </div>
                            <div class="grid grid-cols-2 gap-2 bg-black/50 border border-purple-950/60 p-2.5 rounded-lg text-[10px] text-gray-400 font-mono">
                                <div>LATENCY: <span class="text-purple-400 font-bold">${m.response_time}ms</span></div>
                                <div>UPTIME: <span class="text-white font-bold">${m.uptime}%</span></div>
                            </div>
                            <div class="flex gap-2 pt-1 border-t border-purple-950/30">
                                <button onclick="triggerNodeToggle('${m.id}')" class="px-3 py-1.5 bg-purple-950/50 border border-purple-900/60 text-purple-300 rounded-lg text-[11px] hover:border-purple-500 transition-all duration-200">${m.is_active ? 'SUSPEND' : 'ACTIVATE'}</button>
                                <button onclick="triggerNodeIsolation('${m.id}')" class="px-3 py-1.5 text-rose-400 border border-transparent hover:border-rose-900/40 rounded-lg text-[11px] font-bold ml-auto transition-all duration-200">TERMINATE</button>
                            </div>
                        `;
                        container.appendChild(div);
                    });
                } catch(e){}
            }

            async function executeTargetPipelineInjection() {
                const name = document.getElementById("node-name").value.trim();
                const url = document.getElementById("node-url").value.trim();
                const interval = document.getElementById("node-interval").value;
                if(!name || !url) return alert("All fields required.");

                const res = await fetch("/api/monitors", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ user_id: activeSession.user_id, role: activeSession.role, name, url, interval })
                });
                if(res.ok) {
                    document.getElementById("node-name").value = "";
                    document.getElementById("node-url").value = "";
                    syncRealtimeGridData();
                } else { alert("Injection Denied by System Core Firewall Node Restrictions."); }
            }

            async function triggerNodeToggle(mid) {
                await fetch(`/api/monitors/${mid}/toggle`, { method: "POST" });
                syncRealtimeGridData();
            }

            async function triggerNodeIsolation(mid) {
                if(confirm("Are you sure you want to isolate/terminate this active signal node tracking vector?")) {
                    await fetch(`/api/monitors/${mid}`, { method: "DELETE" });
                    syncRealtimeGridData();
                }
            }
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
