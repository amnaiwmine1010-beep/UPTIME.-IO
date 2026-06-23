import os
import time
import json
import asyncio
import httpx
from typing import List, Dict
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager

# --- TELEGRAM BOT INTEGRATION CORE ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

BOT_TOKEN = "7938490659:AAEdla7crncXJY0XDVWwUA8P8umOOdqHLC0"
OWNER_ID = 7224513731  # TODO: Replace with your actual Telegram User ID

# --- DB MANAGEMENT SYSTEM ---
DB_FILE = "monitors_db.json"
GLOBAL_SETTINGS_FILE = "global_settings.json"
ADMIN_FILE = "admins.json"

def load_json_file(filename, default_factory):
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except Exception:
            return default_factory()
    return default_factory()

def save_json_file(filename, data):
    try:
        with open(filename, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[!] Database Save Error ({filename}): {e}")

# Global In-Memory Sync
monitors: List[Dict] = load_json_file(DB_FILE, list)
global_config = load_json_file(GLOBAL_SETTINGS_FILE, lambda: {"global_timeout": 12, "auto_refresh": True})
admins: List[int] = load_json_file(ADMIN_FILE, list)
total_global_checks = sum(m.get('total_checks', 0) for m in monitors)

db_lock = asyncio.Lock()

async def async_save_db():
    async with db_lock:
        save_json_file(DB_FILE, monitors)

class MonitorRequest(BaseModel):
    name: str
    url: str
    interval: int = 5

class SettingsRequest(BaseModel):
    global_timeout: int
    auto_refresh: bool

# Shared HTTPX Client to prevent socket exhaustion
async_client_pool: httpx.AsyncClient = None

async def check_api_status(monitor: Dict):
    global total_global_checks
    start_time = time.time()
    
    url = monitor['url']
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    timeout_val = float(global_config.get("global_timeout", 12))

    try:
        response = await async_client_pool.get(url, timeout=timeout_val, follow_redirects=True)
        response_time = int((time.time() - start_time) * 1000)
        
        if 200 <= response.status_code < 400:
            monitor['status'] = 'UP'
            monitor['success_checks'] += 1
        else:
            monitor['status'] = 'DOWN'
        
        monitor['response_time'] = response_time
        monitor['status_code'] = response.status_code

    except Exception:
        monitor['status'] = 'DOWN'
        monitor['response_time'] = 0
        monitor['status_code'] = "ERR"
        
    finally:
        monitor['total_checks'] += 1
        total_global_checks += 1
        monitor['last_check'] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        if monitor['total_checks'] > 0:
            monitor['uptime'] = round((monitor['success_checks'] / monitor['total_checks']) * 100, 2)
        await async_save_db()

# Keep-Alive Engine to prevent sleeping
async def keep_alive_pulse():
    await asyncio.sleep(30)
    app_url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("KOYEB_APP_URL") or "http://localhost:8080"
    while True:
        try:
            await async_client_pool.get(app_url, timeout=10.0)
        except Exception:
            pass
        await asyncio.sleep(300)

# Background Monitoring Network Loop
async def monitor_loop():
    while True:
        tasks = []
        current_time = time.time()
        
        for monitor in monitors:
            if monitor.get('is_active', True):
                last_run = monitor.get('_last_run_timestamp', 0)
                interval_seconds = monitor.get('interval', 5) * 60
                
                if current_time - last_run >= interval_seconds:
                    monitor['_last_run_timestamp'] = current_time
                    tasks.append(check_api_status(monitor))
                    
        if tasks:
            await asyncio.gather(*tasks)
            await async_save_db()
            
        await asyncio.sleep(5)

# --- TELEGRAM BOT HANDLERS ---
def is_authorized(user_id: int) -> bool:
    return user_id == OWNER_ID or user_id in admins

async def bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("❌ Access Denied. You are not authorized.")
        return
    
    welcome_text = (
        f"⚡ *WELCOME TO MATRIX UPTIME COMMAND CENTER* ⚡\n\n"
        f"Greetings, {'Owner' if user.id == OWNER_ID else 'Admin'}! Use the panel below to pilot the grid."
    )
    keyboard = [
        [InlineKeyboardButton("📊 Core Live Stats", callback_data="bot_stats")],
        [InlineKeyboardButton("🖥️ Active Node Lists", callback_data="bot_list")]
    ]
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def bot_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_authorized(query.from_user.id):
        return

    total = len(monitors)
    up = len([m for m in monitors if m['is_active'] and m['status'] == 'UP'])
    down = len([m for m in monitors if m['is_active'] and m['status'] == 'DOWN'])
    
    stats_msg = (
        f"📊 *MATRIX FRAMEWORK LOGS*\n\n"
        f"🔹 Total Allocations: {total}\n"
        f"🟢 Operational (UP): {up}\n"
        f"🔴 Disconnected (DOWN): {down}\n"
        f"⚡ Total Pulses: {total_global_checks}"
    )
    keyboard = [[InlineKeyboardButton("⬅️ Back to Deck", callback_data="bot_main")]]
    await query.edit_message_text(stats_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def bot_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_authorized(query.from_user.id):
        return

    if not monitors:
        msg = "No target operational sequences inside matrix core."
    else:
        msg = "🖥️ *CURRENT ACTIVE TARGETS*:\n\n"
        for m in monitors[:10]: # limit to 10 for view optimization
            status_icon = "🟢" if m['status'] == 'UP' else "🔴" if m['status'] == 'DOWN' else "⚪"
            msg += f"{status_icon} *{m['name']}* - {m['uptime']}% Uptime\n`{m['url']}`\n\n"
            
    keyboard = [[InlineKeyboardButton("⬅️ Back to Deck", callback_data="bot_main")]]
    await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def bot_main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("📊 Core Live Stats", callback_data="bot_stats")],
        [InlineKeyboardButton("🖥️ Active Node Lists", callback_data="bot_list")]
    ]
    await query.edit_message_text("⚡ *MATRIX UPTIME COMMAND CENTER*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Critical Security: Only the Mainframe Owner can add Admins.")
        return
    try:
        new_admin_id = int(context.args[0])
        if new_admin_id not in admins:
            admins.append(new_admin_id)
            save_json_file(ADMIN_FILE, admins)
            await update.message.reply_text(f"🧬 Node Authorized: User ID {new_admin_id} is now an Admin.")
        else:
            await update.message.reply_text("User is already authorized within the framework.")
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Syntax: `/addadmin <USER_ID>`")

async def del_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Critical Security: Only the Mainframe Owner can remove Admins.")
        return
    try:
        admin_id = int(context.args[0])
        if admin_id in admins:
            admins.remove(admin_id)
            save_json_file(ADMIN_FILE, admins)
            await update.message.reply_text(f"⚔️ Access Revoked: User ID {admin_id} removed from registry.")
        else:
            await update.message.reply_text("User ID not found in Admin registry.")
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Syntax: `/deladmin <USER_ID>`")

# --- LIFESPAN AND API CONFIGURATION ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global async_client_pool
    async_client_pool = httpx.AsyncClient(limits=httpx.Limits(max_connections=100, max_keepalive_connections=20))
    
    # Initialize Bot Application safely in async environment
    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", bot_start))
    bot_app.add_handler(CommandHandler("addadmin", add_admin))
    bot_app.add_handler(CommandHandler("deladmin", del_admin))
    bot_app.add_handler(CallbackQueryHandler(bot_stats_callback, pattern="bot_stats"))
    bot_app.add_handler(CallbackQueryHandler(bot_list_callback, pattern="bot_list"))
    bot_app.add_handler(CallbackQueryHandler(bot_main_callback, pattern="bot_main"))
    
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()
    
    asyncio.create_task(monitor_loop())
    asyncio.create_task(keep_alive_pulse())
    
    yield
    # Clean shutdown execution
    await bot_app.updater.stop()
    await bot_app.stop()
    await bot_app.shutdown()
    await async_client_pool.aclose()

app = FastAPI(title="VIP Uptime Monitor By SPEED_X", lifespan=lifespan)

# --- API ENDPOINTS ---

@app.get("/api/stats")
async def get_stats():
    total = len(monitors)
    active = len([m for m in monitors if m['is_active']])
    up = len([m for m in monitors if m['is_active'] and m['status'] == 'UP'])
    down = len([m for m in monitors if m['is_active'] and m['status'] == 'DOWN'])
    return {
        "total": total,
        "active": active,
        "up": up,
        "down": down,
        "total_checks": total_global_checks,
        "settings": global_config
    }

@app.get("/api/monitors")
async def get_monitors():
    cleaned_monitors = []
    for m in monitors:
        copy_m = m.copy()
        copy_m.pop('_last_run_timestamp', None)
        cleaned_monitors.append(copy_m)
    return cleaned_monitors

@app.post("/api/settings")
async def update_settings(req: SettingsRequest):
    global global_config
    global_config["global_timeout"] = req.global_timeout
    global_config["auto_refresh"] = req.auto_refresh
    save_json_file(GLOBAL_SETTINGS_FILE, global_config)
    return {"success": True, "settings": global_config}

@app.post("/api/monitors")
async def add_monitor(req: MonitorRequest):
    new_monitor = {
        "id": str(int(time.time() * 1000)),
        "name": req.name,
        "url": req.url,
        "interval": req.interval,
        "status": "PENDING",
        "response_time": 0,
        "status_code": "N/A",
        "uptime": 100.0,
        "success_checks": 0,
        "total_checks": 0,
        "is_active": True,
        "last_check": "Never",
        "_last_run_timestamp": 0
    }
    monitors.append(new_monitor)
    await check_api_status(new_monitor) 
    await async_save_db()
    return new_monitor

@app.post("/api/monitors/{monitor_id}/ping")
async def force_ping_monitor(monitor_id: str):
    for m in monitors:
        if m['id'] == monitor_id:
            if not m['is_active']:
                raise HTTPException(status_code=400, detail="Cannot pulse suspended node")
            await check_api_status(m)
            await async_save_db()
            return m
    raise HTTPException(status_code=404, detail="Monitor not found")

@app.post("/api/monitors/{monitor_id}/toggle")
async def toggle_monitor(monitor_id: str):
    for m in monitors:
        if m['id'] == monitor_id:
            m['is_active'] = not m['is_active']
            m['status'] = 'PENDING' if m['is_active'] else 'STOPPED'
            if m['is_active']:
                m['_last_run_timestamp'] = 0
            await async_save_db()
            return m
    raise HTTPException(status_code=404, detail="Monitor not found")

@app.post("/api/global/suspend")
async def suspend_all_monitors():
    for m in monitors:
        m['is_active'] = False
        m['status'] = 'STOPPED'
    await async_save_db()
    return {"success": True}

@app.post("/api/global/resume")
async def resume_all_monitors():
    for m in monitors:
        m['is_active'] = True
        m['status'] = 'PENDING'
        m['_last_run_timestamp'] = 0
    await async_save_db()
    return {"success": True}

@app.post("/api/global/purge")
async def purge_all_monitors():
    global monitors
    monitors.clear()
    await async_save_db()
    return {"success": True}

@app.delete("/api/monitors/{monitor_id}")
async def delete_monitor(monitor_id: str):
    global monitors
    monitors = [m for m in monitors if m['id'] != monitor_id]
    await async_save_db()
    return {"success": True}


# --- FRONTEND UI WITH INTEGRATED ENCRYPTED GUARDRAILS ---

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>MATRIX UPTIME mainframe PRO • SPEED_X</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdn.jsdelivr.net/npm/particles.js@2.0.0/particles.min.js"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;600;900&family=Rajdhani:wght@500;700&display=swap');
            body { background-color: #020205; color: #f1f5f9; font-family: 'Rajdhani', sans-serif; overflow-x: hidden; user-select: none; }
            .font-orbitron { font-family: 'Orbitron', sans-serif; }
            .neon-shadow-cyan { box-shadow: 0 0 25px rgba(6, 182, 212, 0.25); }
            .neon-text-cyan { text-shadow: 0 0 15px rgba(6, 182, 212, 0.8), 0 0 30px rgba(6, 182, 212, 0.4); }
            .neon-text-green { text-shadow: 0 0 10px rgba(16, 185, 129, 0.6); }
            .neon-text-rose { text-shadow: 0 0 10px rgba(244, 63, 94, 0.6); }
            .vip-card { background: linear-gradient(135deg, rgba(8, 8, 20, 0.9) 0%, rgba(3, 3, 8, 0.98) 100%); border: 1px solid rgba(6, 182, 212, 0.12); backdrop-filter: blur(16px); }
            .vip-card:hover { border-color: rgba(6, 182, 212, 0.4); box-shadow: 0 0 25px rgba(6, 182, 212, 0.15); transform: translateY(-1px); }
            #particles-js { position: fixed; width: 100%; height: 100%; z-index: -1; top: 0; left: 0; }
            .cyber-scanner { height: 2px; background: linear-gradient(90deg, transparent, #06b6d4, transparent); width: 100%; position: absolute; animation: scan 4s linear infinite; }
            @keyframes scan { 0% { top: 0%; } 50% { top: 100%; } 100% { top: 0%; } }
            #toast-container { position: fixed; bottom: 20px; right: 20px; z-index: 50; display: flex; flex-direction: column; gap: 10px; }
            ::-webkit-scrollbar { width: 5px; height: 5px; }
            ::-webkit-scrollbar-track { background: #020205; }
            ::-webkit-scrollbar-thumb { background: linear-gradient(#06b6d4, #3b82f6); border-radius: 10px; }
            .terminal-box { background: rgba(2, 2, 5, 0.95); font-family: monospace; border: 1px solid rgba(6, 182, 212, 0.2); height: 160px; overflow-y: auto; box-shadow: inset 0 0 15px rgba(0,0,0,0.8); }
        </style>
        
        <script>
            document.addEventListener('contextmenu', event => event.preventDefault());
            document.onkeydown = function(e) {
                if (e.keyCode == 123) return false; // F12
                if (e.ctrlKey && e.shiftKey && e.keyCode == 'I'.charCodeAt(0)) return false; // Inspect Element
                if (e.ctrlKey && e.shiftKey && e.keyCode == 'C'.charCodeAt(0)) return false;
                if (e.ctrlKey && e.shiftKey && e.keyCode == 'J'.charCodeAt(0)) return false;
                if (e.ctrlKey && e.keyCode == 'U'.charCodeAt(0)) return false; // View Source
            };
            
            // Core Security Looping Interval (Anti-Debugging Rig)
            setInterval(function() {
                const startTime = +new Date();
                debugger;
                const endTime = +new Date();
                if (endTime - startTime > 100) {
                    document.body.innerHTML = "<h1 style='color:#06b6d4; text-align:center; margin-top:20%; font-family:monospace;'>[ACCESS DENIED: DEFENSE LAYER TRIGGERED]</h1>";
                }
            }, 50);
        </script>
    </head>
    <body class="relative min-h-screen antialiased">
        <div id="particles-js"></div>
        <div id="toast-container"></div>

        <div class="max-w-6xl mx-auto px-4 py-8 relative z-10">
            <div class="flex flex-wrap justify-between items-center gap-3 mb-6 bg-black/50 border border-cyan-950/30 px-4 py-3 rounded-xl">
                <div class="flex flex-wrap items-center gap-2">
                    <button onclick="toggleAudio()" id="audio-btn" class="px-3 py-1.5 bg-cyan-950/30 border border-cyan-800/40 hover:border-cyan-500/50 text-cyan-400 font-bold text-xs rounded-lg transition-all flex items-center gap-1.5 font-mono">
                        <i class="fa-solid fa-volume-high" id="audio-icon"></i> SFX: ENABLED
                    </button>
                    <div class="h-4 w-[1px] bg-cyan-950"></div>
                    <span id="auto-refresh-badge" class="px-3 py-1 bg-blue-950/30 border border-blue-900/40 text-blue-400 font-bold text-xs rounded-lg font-mono">AUTO REFRESH: ON</span>
                </div>
                <div class="flex flex-wrap gap-2">
                    <button onclick="globalAction('resume')" class="px-3 py-1.5 bg-emerald-950/40 border border-emerald-800/40 hover:border-emerald-500/50 text-emerald-400 font-bold text-xs rounded-lg transition-all font-mono"><i class="fa-solid fa-play"></i> RESUME ALL NODES</button>
                    <button onclick="globalAction('suspend')" class="px-3 py-1.5 bg-amber-950/40 border border-amber-800/40 hover:border-amber-500/50 text-amber-400 font-bold text-xs rounded-lg transition-all font-mono"><i class="fa-solid fa-pause"></i> SUSPEND ALL NODES</button>
                    <button onclick="globalPurge()" class="px-3 py-1.5 bg-rose-950/40 border border-rose-800/40 hover:border-rose-500/50 text-rose-400 font-bold text-xs rounded-lg transition-all font-mono"><i class="fa-solid fa-skull-crossbones"></i> PURGE ALL</button>
                </div>
            </div>

            <header class="text-center mb-10 border-b border-cyan-950/20 pb-8 relative">
                <div class="inline-block px-4 py-1.5 bg-gradient-to-r from-cyan-950/60 to-blue-950/60 border border-cyan-500/20 text-cyan-400 text-xs font-mono tracking-widest uppercase rounded-md mb-4">
                    <i class="fa-solid fa-microchip animate-pulse mr-1.5 text-cyan-400"></i> SYSTEM LAYER FRAMEWORK ACTIVE
                </div>
                <h1 class="text-5xl md:text-6xl font-black tracking-wider text-cyan-400 neon-text-cyan font-orbitron">VIP UPTIME MATRIX</h1>
                <p class="text-sm text-gray-500 uppercase tracking-widest mt-3 font-mono">ENGINEERED BY <span class="text-cyan-400 font-bold">SPEED_X</span> • SECURE ARCHITECTURE v5.0 ⚔️</p>
            </header>

            <div class="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8">
                <div class="vip-card p-4 rounded-xl text-center border-b-2 border-cyan-500 relative overflow-hidden">
                    <div class="cyber-scanner opacity-10"></div>
                    <h3 class="text-xs font-bold text-cyan-500/70 tracking-wider uppercase mb-1 font-mono">Total Targets</h3>
                    <p id="stat-total" class="text-4xl font-black text-cyan-400 font-mono tracking-tighter">0</p>
                </div>
                <div class="vip-card p-4 rounded-xl text-center border-b-2 border-blue-500">
                    <h3 class="text-xs font-bold text-blue-500/70 tracking-wider uppercase mb-1 font-mono">Active Rails</h3>
                    <p id="stat-active" class="text-4xl font-black text-blue-400 font-mono tracking-tighter">0</p>
                </div>
                <div class="vip-card p-4 rounded-xl text-center border-b-2 border-emerald-500">
                    <h3 class="text-xs font-bold text-emerald-500/70 tracking-wider uppercase mb-1 font-mono">Status UP</h3>
                    <p id="stat-up" class="text-4xl font-black text-emerald-400 font-mono tracking-tighter neon-text-green">0</p>
                </div>
                <div class="vip-card p-4 rounded-xl text-center border-b-2 border-rose-500">
                    <h3 class="text-xs font-bold text-rose-500/70 tracking-wider uppercase mb-1 font-mono">Status DOWN</h3>
                    <p id="stat-down" class="text-4xl font-black text-rose-400 font-mono tracking-tighter neon-text-rose">0</p>
                </div>
                <div class="vip-card p-4 rounded-xl text-center border-b-2 border-amber-500 col-span-2 md:col-span-1">
                    <h3 class="text-xs font-bold text-amber-500/70 tracking-wider uppercase mb-1 font-mono">Total Transmissions</h3>
                    <p id="stat-checks" class="text-4xl font-black text-amber-400 font-mono tracking-tighter">0</p>
                </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
                <div class="vip-card p-6 rounded-2xl border border-cyan-500/10 lg:col-span-2 shadow-xl">
                    <h2 class="text-md font-bold text-cyan-400 mb-5 flex items-center gap-2 font-mono uppercase tracking-widest font-orbitron">
                        <i class="fa-solid fa-plus-node text-cyan-400 animate-bounce"></i> INJECT TARGET MATRIX ENDPOINT
                    </h2>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                        <div>
                            <label class="block text-xs font-bold text-cyan-400/80 mb-1 font-mono uppercase tracking-wider">Node Alias Identifier</label>
                            <div class="relative">
                                <i class="fa-solid fa-tag absolute left-3.5 top-3.5 text-cyan-600/50 text-xs"></i>
                                <input type="text" id="mon-name" placeholder="e.g. Main Framework Bot" class="w-full bg-black/60 border border-cyan-950 rounded-lg pl-10 pr-4 py-2.5 text-white placeholder-gray-700 focus:outline-none focus:border-cyan-500 text-xs font-mono">
                            </div>
                        </div>
                        <div>
                            <label class="block text-xs font-bold text-cyan-400/80 mb-1 font-mono uppercase tracking-wider">Target Endpoint URL</label>
                            <div class="relative">
                                <i class="fa-solid fa-network-wired absolute left-3.5 top-3.5 text-cyan-600/50 text-xs"></i>
                                <input type="url" id="mon-url" placeholder="https://api.domain.com/pulse" class="w-full bg-black/60 border border-cyan-950 rounded-lg pl-10 pr-4 py-2.5 text-white placeholder-gray-700 focus:outline-none focus:border-cyan-500 text-xs font-mono">
                            </div>
                        </div>
                    </div>
                    <div class="mb-5">
                        <label class="block text-xs font-bold text-cyan-400/80 mb-1 font-mono uppercase tracking-wider">Interval Cycle Control Sequence</label>
                        <select id="mon-interval" class="w-full bg-black/60 border border-cyan-950 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-cyan-500 text-xs font-mono cursor-pointer">
                            <option value="1">Hyper Blast Mode (Every 1 Minute)</option>
                            <option value="5" selected>Standard VIP Framework Cycle (Every 5 Minutes)</option>
                            <option value="15">Optimized Operations Sequence (Every 15 Minutes)</option>
                            <option value="30">Deep Matrix System Save (Every 30 Minutes)</option>
                        </select>
                    </div>
                    <button onclick="deployMonitor()" class="w-full bg-gradient-to-r from-cyan-500 via-blue-600 to-indigo-600 hover:from-cyan-400 hover:to-indigo-500 text-black font-black py-3 rounded-xl tracking-widest uppercase text-xs font-orbitron transition-all">
                        <i class="fa-solid fa-circle-nodes mr-1 text-sm"></i> Deploy Main Target Node
                    </button>
                </div>

                <div class="vip-card p-6 rounded-2xl border border-cyan-500/10 flex flex-col justify-between">
                    <div>
                        <h2 class="text-md font-bold text-cyan-400 mb-5 flex items-center gap-2 font-mono uppercase tracking-widest font-orbitron"><i class="fa-solid fa-sliders text-cyan-400"></i> CONFIG RUNTIME</h2>
                        <div class="mb-4">
                            <label class="block text-xs font-bold text-cyan-400/80 mb-1.5 font-mono uppercase tracking-wider">Network Timeout (Seconds)</label>
                            <input type="number" id="settings-timeout" min="2" max="60" class="w-full bg-black/60 border border-cyan-950 rounded-lg px-4 py-2 text-white focus:outline-none focus:border-cyan-500 text-xs font-mono">
                        </div>
                        <div class="mb-4 flex items-center justify-between bg-black/40 border border-cyan-950/40 p-2.5 rounded-lg">
                            <span class="text-xs font-bold text-cyan-400/80 font-mono uppercase tracking-wider">UI Auto Synchronizer</span>
                            <input type="checkbox" id="settings-refresh" class="w-4 h-4 accent-cyan-500 cursor-pointer">
                        </div>
                    </div>
                    <button onclick="saveGlobalConfig()" class="w-full bg-cyan-950/50 border border-cyan-700/60 hover:bg-cyan-900/60 text-cyan-400 font-bold py-2 rounded-xl tracking-widest uppercase text-xs font-mono transition-all">Sync Config Core</button>
                </div>
            </div>

            <div class="bg-black/40 border border-cyan-950/40 p-4 rounded-xl mb-6 flex flex-col md:flex-row gap-4 items-center justify-between">
                <div class="flex flex-wrap items-center gap-3 w-full md:w-auto">
                    <div class="relative w-full sm:w-64">
                        <i class="fa-solid fa-magnifying-glass absolute left-3 top-3 text-cyan-600/70 text-xs"></i>
                        <input type="text" id="search-bar" oninput="applyFiltersAndSorting()" placeholder="Search active node matrices..." class="w-full bg-black border border-cyan-950 rounded-lg pl-9 pr-4 py-2 text-xs focus:outline-none focus:border-cyan-500 text-gray-300 font-mono">
                    </div>
                    <div class="flex bg-black border border-cyan-950 p-1 rounded-lg text-xs font-mono">
                        <button onclick="setStatusFilter('ALL')" id="tab-ALL" class="px-3 py-1 rounded bg-cyan-950 text-cyan-400 font-bold">ALL</button>
                        <button onclick="setStatusFilter('UP')" id="tab-UP" class="px-3 py-1 rounded text-gray-500 hover:text-cyan-400">UP</button>
                        <button onclick="setStatusFilter('DOWN')" id="tab-DOWN" class="px-3 py-1 rounded text-gray-500 hover:text-cyan-400">DOWN</button>
                        <button onclick="setStatusFilter('STOPPED')" id="tab-STOPPED" class="px-3 py-1 rounded text-gray-500 hover:text-cyan-400">SUSPENDED</button>
                    </div>
                </div>
                <div class="flex items-center gap-2 w-full md:w-auto justify-end">
                    <span class="text-xs text-gray-500 font-mono uppercase tracking-wider"><i class="fa-solid fa-arrow-down-sort-alphabet"></i> Sort:</span>
                    <select id="sort-engine" onchange="applyFiltersAndSorting()" class="bg-black border border-cyan-950 rounded-lg px-3 py-2 text-xs font-mono text-gray-300 focus:outline-none focus:border-cyan-500 cursor-pointer">
                        <option value="name">Identifier Name</option>
                        <option value="uptime">Health Rate</option>
                        <option value="response_time">Response Latency</option>
                    </select>
                    <button onclick="downloadBackup()" class="px-3 py-2 bg-cyan-950/20 border border-cyan-900/50 text-cyan-400 font-bold text-xs rounded-lg transition-all font-mono">BACKUP</button>
                </div>
            </div>

            <div id="monitors-grid" class="space-y-4 mb-8"></div>

            <div class="mb-4">
                <div id="terminal-log" class="terminal-box p-4 text-xs font-mono text-emerald-400 space-y-1">
                    <div>[SYSTEM INITIALIZING] Security protocols operational. Main secure tracking framework online...</div>
                </div>
            </div>

            <footer class="text-center text-xs font-mono text-gray-600 border-t border-cyan-950/20 pt-6">
                <p>&copy; 2026 <span class="text-cyan-500/50 font-bold">SPEED_X</span> • AUTHORIZED QUANTUM FRAMEWORK LABS.</p>
            </footer>
        </div>

        <script>
            let currentCachedMonitors = [];
            let activeStatusFilter = 'ALL';
            let isAudioEnabled = true;
            let autoRefreshIntervalId = null;
            const audioCtx = new (window.AudioContext || window.webkitAudioContext)();

            function playSoundFx(type) {
                if (!isAudioEnabled) return;
                const osc = audioCtx.createOscillator();
                const gain = audioCtx.createGain();
                osc.connect(gain); gain.connect(audioCtx.destination);
                if (type === 'success') {
                    osc.type = 'sine'; osc.frequency.setValueAtTime(880, audioCtx.currentTime);
                    gain.gain.setValueAtTime(0.06, audioCtx.currentTime);
                    osc.start(); osc.stop(audioCtx.currentTime + 0.12);
                } else if (type === 'alert') {
                    osc.type = 'sawtooth'; osc.frequency.setValueAtTime(160, audioCtx.currentTime);
                    gain.gain.setValueAtTime(0.1, audioCtx.currentTime);
                    osc.start(); osc.stop(audioCtx.currentTime + 0.25);
                } else if (type === 'click') {
                    osc.type = 'square'; osc.frequency.setValueAtTime(550, audioCtx.currentTime);
                    gain.gain.setValueAtTime(0.03, audioCtx.currentTime);
                    osc.start(); osc.stop(audioCtx.currentTime + 0.04);
                }
            }

            function printTerminalLog(msg) {
                const term = document.getElementById('terminal-log');
                const timestamp = new Date().toISOString().slice(11, 19);
                const logNode = document.createElement('div');
                logNode.innerHTML = `<span class="text-cyan-600">[${timestamp}]</span> ${msg}`;
                term.appendChild(logNode);
                term.scrollTop = term.scrollHeight;
            }

            function toggleAudio() {
                isAudioEnabled = !isAudioEnabled;
                const btn = document.getElementById('audio-btn');
                btn.innerHTML = isAudioEnabled ? `<i class="fa-solid fa-volume-high"></i> SFX: ENABLED` : `<i class="fa-solid fa-volume-xmark"></i> SFX: MUTED`;
            }

            function showToast(message, type = 'info') {
                const toast = document.createElement('div');
                let theme = type === 'success' ? 'border-emerald-500 text-emerald-400' : type === 'error' ? 'border-rose-500 text-rose-400' : 'border-cyan-500 text-cyan-400';
                toast.className = `vip-card px-4 py-2.5 rounded-lg border-l-4 ${theme} shadow-lg font-mono text-xs flex items-center gap-2`;
                toast.innerHTML = `<span>${message}</span>`;
                document.getElementById('toast-container').appendChild(toast);
                setTimeout(() => toast.remove(), 3500);
            }

            particlesJS('particles-js', {
                "particles": {
                    "number": { "value": 45 }, "color": { "value": "#06b6d4" },
                    "opacity": { "value": 0.15 }, "size": { "value": 2 },
                    "line_linked": { "enable": true, "distance": 120, "color": "#0891b2", "opacity": 0.06 },
                    "move": { "enable": true, "speed": 0.8 }
                }
            });

            async function refreshDashboard(isSilent = false) {
                try {
                    const statsRes = await fetch('/api/stats');
                    const stats = await statsRes.json();
                    document.getElementById('stat-total').innerText = stats.total;
                    document.getElementById('stat-active').innerText = stats.active;
                    document.getElementById('stat-up').innerText = stats.up;
                    document.getElementById('stat-down').innerText = stats.down;
                    document.getElementById('stat-checks').innerText = stats.total_checks;
                    document.getElementById('settings-timeout').value = stats.settings.global_timeout;
                    document.getElementById('settings-refresh').checked = stats.settings.auto_refresh;
                    
                    initAutoRefreshLoop(stats.settings.auto_refresh);
                    const listRes = await fetch('/api/monitors');
                    currentCachedMonitors = await listRes.json();
                    applyFiltersAndSorting();
                } catch (err) { printTerminalLog("CRITICAL ERROR: Connection failed."); }
            }

            function setStatusFilter(status) {
                activeStatusFilter = status;
                ['ALL', 'UP', 'DOWN', 'STOPPED'].forEach(st => {
                    document.getElementById(`tab-${st}`).className = st === status ? "px-3 py-1 rounded bg-cyan-950 text-cyan-400 font-bold" : "px-3 py-1 rounded text-gray-500 hover:text-cyan-400";
                });
                applyFiltersAndSorting();
            }

            function applyFiltersAndSorting() {
                const query = document.getElementById('search-bar').value.toLowerCase().trim();
                const sortBy = document.getElementById('sort-engine').value;
                let data = [...currentCachedMonitors];
                if(activeStatusFilter !== 'ALL') data = data.filter(m => m.status === activeStatusFilter);
                if(query) data = data.filter(m => m.name.toLowerCase().includes(query) || m.url.toLowerCase().includes(query));
                data.sort((a, b) => sortBy === 'name' ? a.name.localeCompare(b.name) : b[sortBy] - a[sortBy]);
                renderMatrixGrid(data);
            }

            function renderMatrixGrid(dataList) {
                const container = document.getElementById('monitors-grid');
                container.innerHTML = dataList.length === 0 ? `<div class="vip-card p-12 rounded-xl text-center text-xs font-mono text-gray-600">NO ACTIVE GRID MATRIX LOADED.</div>` : '';
                dataList.forEach(m => {
                    let badge = m.status === 'UP' ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" : m.status === 'DOWN' ? "bg-rose-500/10 text-rose-400 border-rose-500/20" : "bg-gray-900 text-gray-500";
                    const card = document.createElement('div');
                    card.className = `vip-card p-5 rounded-xl border-l-4 ${m.status === 'UP' ? 'border-l-emerald-500' : 'border-l-rose-500'}`;
                    card.innerHTML = `
                        <div class="flex justify-between items-center mb-3">
                            <div>
                                <h3 class="text-md font-black text-gray-100 font-mono">${m.name} [${m.status_code}]</h3>
                                <p class="text-xs font-mono text-cyan-600/70 break-all">${m.url}</p>
                            </div>
                            <span class="px-3 py-1 font-mono text-[10px] rounded border ${badge}">${m.status}</span>
                        </div>
                        <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 bg-black/40 p-3 rounded-lg text-[11px] font-mono text-gray-400 mb-4">
                            <div>Latency: <b class="text-white">${m.response_time}ms</b></div>
                            <div>Health: <b class="text-white">${m.uptime}%</b></div>
                            <div>Pulses: <b class="text-white">${m.success_checks}/${m.total_checks}</b></div>
                            <div>Routine: <b class="text-white">${m.interval}m</b></div>
                        </div>
                        <div class="flex gap-2">
                            <button onclick="toggleChannel('${m.id}')" class="px-3 py-1.5 bg-black/50 border text-gray-300 rounded-lg text-xs font-mono">${m.is_active ? 'Suspend' : 'Activate'}</button>
                            <button onclick="forcePing('${m.id}')" class="px-3 py-1.5 bg-cyan-950/30 text-cyan-400 rounded-lg text-xs font-mono">Manual Pulse</button>
                            <button onclick="destroyChannel('${m.id}')" class="px-3 py-1.5 text-rose-400 font-bold rounded-lg text-xs font-mono ml-auto">Terminate</button>
                        </div>`;
                    container.appendChild(card);
                });
            }

            async function deployMonitor() {
                const name = document.getElementById('mon-name').value.trim();
                const url = document.getElementById('mon-url').value.trim();
                const interval = document.getElementById('mon-interval').value;
                if(!name || !url) return showToast('Required payload parameters missing!', 'error');
                await fetch('/api/monitors', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, url, interval: parseInt(interval) })
                });
                document.getElementById('mon-name').value = '';
                document.getElementById('mon-url').value = '';
                refreshDashboard(true);
            }

            async function saveGlobalConfig() {
                const timeout = parseInt(document.getElementById('settings-timeout').value);
                const autoRefresh = document.getElementById('settings-refresh').checked;
                await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ global_timeout: timeout, auto_refresh: autoRefresh })
                });
                refreshDashboard(true);
            }

            function initAutoRefreshLoop(status) {
                if(autoRefreshIntervalId) clearInterval(autoRefreshIntervalId);
                if(status) autoRefreshIntervalId = setInterval(() => refreshDashboard(true), 10000);
            }

            async function forcePing(id) {
                await fetch(`/api/monitors/${id}/ping`, { method: 'POST' });
                refreshDashboard(true);
            }

            async function toggleChannel(id) {
                await fetch(`/api/monitors/${id}/toggle`, { method: 'POST' });
                refreshDashboard(true);
            }

            async function globalAction(action) {
                await fetch(`/api/global/${action}`, { method: 'POST' });
                refreshDashboard(true);
            }

            async function globalPurge() {
                if(confirm('Wipe ALL active data matrices inside core?')) {
                    await fetch('/api/global/purge', { method: 'POST' });
                    refreshDashboard(true);
                }
            }

            async function destroyChannel(id) {
                if(confirm('Terminate this channel node?')) {
                    await fetch(`/api/monitors/${id}`, { method: 'DELETE' });
                    refreshDashboard(true);
                }
            }

            function downloadBackup() {
                if(currentCachedMonitors.length === 0) return;
                const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(currentCachedMonitors, null, 2));
                const anchor = document.createElement('a');
                anchor.setAttribute("href", dataStr); anchor.setAttribute("download", "matrix_uptime_dump.json");
                anchor.click(); anchor.remove();
            }

            window.onload = () => refreshDashboard(false);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
