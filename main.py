# ==============================================================================
# [1] UPDATED REQUIREMENTS.TXT CONFIGURATION (Optimized for Render Python 3.14+)
# ==============================================================================
# fastapi>=0.115.11
# uvicorn==0.34.0
# httpx==0.28.1
# python-telegram-bot==21.10
# pydantic>=2.10.0

import os
import time
import json
import asyncio
import httpx
from typing import List, Dict
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager

# --- TELEGRAM BOT INTEGRATION CORE ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

BOT_TOKEN = "7938490659:AAEdla7crncXJY0XDVWwUA8P8umOOdqHLC0"
OWNER_ID = 7224513731  # Replace with your actual Telegram User ID

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

async def keep_alive_pulse():
    await asyncio.sleep(30)
    app_url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("KOYEB_APP_URL") or "http://localhost:8080"
    while True:
        try:
            await async_client_pool.get(app_url, timeout=10.0)
        except Exception:
            pass
        await asyncio.sleep(300)

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
        await update.message.reply_text("❌ Access Denied. Mainframe security lockdown active.")
        return
    
    welcome_text = (
        f"⚡ *VIP UPTIME MATRIX v6.0* ⚡\n\n"
        f"🛡️ *Role:* {'Mainframe Owner' if user.id == OWNER_ID else 'Authorized Admin'}\n"
        f"🤖 Welcome to the Control Node. Select an option below to manage operations."
    )
    keyboard = [
        [InlineKeyboardButton("📊 Core Live Stats", callback_data="bot_stats")],
        [InlineKeyboardButton("🖥️ Active Targets Grid", callback_data="bot_list")]
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
        f"📊 *SYSTEM CONTROL LOGS*\n\n"
        f"🔹 Total Sequences: {total}\n"
        f"🟢 Active Online (UP): {up}\n"
        f"🔴 Offline/Error (DOWN): {down}\n"
        f"⚡ Cumulative Pulses: {total_global_checks}"
    )
    keyboard = [[InlineKeyboardButton("⬅️ Back to Mainframe", callback_data="bot_main")]]
    await query.edit_message_text(stats_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def bot_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_authorized(query.from_user.id):
        return

    if not monitors:
        msg = "⚠️ No target operational paths inside the database core."
    else:
        msg = "🖥️ *CURRENT TARGET MATRICES*:\n\n"
        for m in monitors[:10]:
            status_icon = "🟢" if m['status'] == 'UP' else "🔴" if m['status'] == 'DOWN' else "⚪"
            msg += f"{status_icon} *{m['name']}* — {m['uptime']}% Health\n`{m['url']}`\n\n"
            
    keyboard = [[InlineKeyboardButton("⬅️ Back to Mainframe", callback_data="bot_main")]]
    await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def bot_main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("📊 Core Live Stats", callback_data="bot_stats")],
        [InlineKeyboardButton("🖥️ Active Targets Grid", callback_data="bot_list")]
    ]
    await query.edit_message_text("⚡ *VIP UPTIME MATRIX v6.0*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Security Override: Only the Owner can authorize new nodes.")
        return
    try:
        new_admin_id = int(context.args[0])
        if new_admin_id not in admins:
            admins.append(new_admin_id)
            save_json_file(ADMIN_FILE, admins)
            await update.message.reply_text(f"🧬 Access Granted: User ID {new_admin_id} is registered as Admin.")
        else:
            await update.message.reply_text("User is already authorized.")
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Syntax: `/addadmin <USER_ID>`")

async def del_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Security Override: Only the Owner can strip admin credentials.")
        return
    try:
        admin_id = int(context.args[0])
        if admin_id in admins:
            admins.remove(admin_id)
            save_json_file(ADMIN_FILE, admins)
            await update.message.reply_text(f"⚔️ Access Revoked: User ID {admin_id} wiped from registry.")
        else:
            await update.message.reply_text("User ID not found in Admin database.")
    except (IndexError, ValueError):
        await update.message.reply_text("⚠️ Syntax: `/deladmin <USER_ID>`")

async def direct_stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    total = len(monitors)
    up = len([m for m in monitors if m['is_active'] and m['status'] == 'UP'])
    await update.message.reply_text(f"⚡ Grid Status: {up}/{total} Nodes Operational.")

# --- LIFESPAN AND API CONFIGURATION ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global async_client_pool
    async_client_pool = httpx.AsyncClient(limits=httpx.Limits(max_connections=100, max_keepalive_connections=20))
    
    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", bot_start))
    bot_app.add_handler(CommandHandler("addadmin", add_admin))
    bot_app.add_handler(CommandHandler("deladmin", del_admin))
    bot_app.add_handler(CommandHandler("stats", direct_stats_cmd))
    bot_app.add_handler(CallbackQueryHandler(bot_stats_callback, pattern="bot_stats"))
    bot_app.add_handler(CallbackQueryHandler(bot_list_callback, pattern="bot_list"))
    bot_app.add_handler(CallbackQueryHandler(bot_main_callback, pattern="bot_main"))
    
    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling()
    
    asyncio.create_task(monitor_loop())
    asyncio.create_task(keep_alive_pulse())
    
    yield
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


# --- NEW INSANELY PREMIUM CYBERPUNK VIP WEB INTERFACE (v6.0) ---

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>SPEED_X • VIP MATRIX INTERFACE</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdn.jsdelivr.net/npm/particles.js@2.0.0/particles.min.js"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Share+Tech+Mono&display=swap');
            
            body { 
                background-color: #030307; 
                color: #e2e8f0; 
                font-family: 'Share Tech Mono', monospace; 
                overflow-x: hidden; 
                user-select: none;
            }
            .font-orbitron { font-family: 'Orbitron', sans-serif; }
            
            /* High-End Cyberpunk Neon Shadows & Text Glows */
            .cyber-glow-cyan { box-shadow: 0 0 30px rgba(6, 182, 212, 0.2); border: 1px solid rgba(6, 182, 212, 0.4) !important; }
            .cyber-glow-purple { box-shadow: 0 0 30px rgba(168, 85, 247, 0.2); border: 1px solid rgba(168, 85, 247, 0.4) !important; }
            
            .text-neon-cyan { text-shadow: 0 0 10px rgba(6, 182, 212, 0.7), 0 0 20px rgba(6, 182, 212, 0.3); }
            .text-neon-purple { text-shadow: 0 0 10px rgba(168, 85, 247, 0.7), 0 0 20px rgba(168, 85, 247, 0.3); }
            .text-neon-emerald { text-shadow: 0 0 8px rgba(16, 185, 129, 0.6); }
            
            /* Premium Futuristic Cards */
            .matrix-panel {
                background: linear-gradient(145deg, rgba(10, 10, 22, 0.85) 0%, rgba(5, 5, 12, 0.95) 100%);
                border: 1px solid rgba(6, 182, 212, 0.1);
                backdrop-filter: blur(20px);
                position: relative;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            }
            .matrix-panel:hover {
                border-color: rgba(168, 85, 247, 0.4);
                box-shadow: 0 0 30px rgba(168, 85, 247, 0.15);
                transform: translateY(-2px);
            }
            
            /* Background Grid Overlay */
            .bg-matrix-grid {
                position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                background-image: linear-gradient(rgba(6, 182, 212, 0.02) 1px, transparent 1px),
                                  linear-gradient(90deg, rgba(6, 182, 212, 0.02) 1px, transparent 1px);
                background-size: 30px 30px; z-index: -1; pointer-events: none;
            }
            
            #particles-js { position: fixed; width: 100%; height: 100%; z-index: -2; top: 0; left: 0; }
            
            /* Custom Cyber Scanner Animation */
            .scanner-line {
                height: 1px; background: linear-gradient(90deg, transparent, #a855f7, transparent);
                width: 100%; position: absolute; left: 0; animation: scanning 6s linear infinite; pointer-events: none;
            }
            @keyframes scanning { 0% { top: 0%; opacity: 0; } 10% { opacity: 1; } 90% { opacity: 1; } 100% { top: 100%; opacity: 0; } }
            
            #toast-container { position: fixed; bottom: 25px; right: 25px; z-index: 100; display: flex; flex-direction: column; gap: 12px; }
            
            /* Interactive Buttons Styling */
            .cyber-btn {
                position: relative; overflow: hidden; transition: all 0.2s ease;
                border: 1px solid rgba(6, 182, 212, 0.3); background: rgba(6, 182, 212, 0.05);
            }
            .cyber-btn:hover {
                background: rgba(6, 182, 212, 0.2); border-color: #06b6d4;
                color: #fff; box-shadow: 0 0 15px rgba(6, 182, 212, 0.4);
            }
            .cyber-btn-purple {
                border: 1px solid rgba(168, 85, 247, 0.3); background: rgba(168, 85, 247, 0.05);
            }
            .cyber-btn-purple:hover {
                background: rgba(168, 85, 247, 0.2); border-color: #a855f7;
                box-shadow: 0 0 15px rgba(168, 85, 247, 0.4);
            }
            
            .terminal-view {
                background: rgba(2, 2, 6, 0.9); border: 1px solid rgba(168, 85, 247, 0.15);
                box-shadow: inset 0 0 20px rgba(0,0,0,0.9); height: 150px; overflow-y: auto;
            }
        </style>
        
        <!-- HIGH-SECURE ENCRYPTED ANTI-EXPLOIT SYSTEM LAYER -->
        <script>
            document.addEventListener('contextmenu', e => e.preventDefault());
            document.onkeydown = function(e) {
                if (e.keyCode == 123) return false;
                if (e.ctrlKey && e.shiftKey && e.keyCode == 'I'.charCodeAt(0)) return false;
                if (e.ctrlKey && e.shiftKey && e.keyCode == 'C'.charCodeAt(0)) return false;
                if (e.ctrlKey && e.shiftKey && e.keyCode == 'J'.charCodeAt(0)) return false;
                if (e.ctrlKey && e.keyCode == 'U'.charCodeAt(0)) return false;
            };
            setInterval(function() {
                const start = +new Date(); debugger;
                if ((+new Date() - start) > 100) {
                    document.body.innerHTML = "<div class='flex justify-center items-center h-screen bg-black text-purple-500 font-mono text-xl tracking-widest'>[DEFENSE LAYER INTERCEPTED: EXPLOIT BLOCKED]</div>";
                }
            }, 50);
        </script>
    </head>
    <body class="relative min-h-screen">
        <div id="particles-js"></div>
        <div class="bg-matrix-grid"></div>
        <div id="toast-container"></div>

        <div class="max-w-6xl mx-auto px-4 py-6 relative z-10">
            <!-- Global Utility Command Bar -->
            <div class="flex flex-wrap justify-between items-center gap-4 mb-8 bg-black/60 border border-purple-950/40 px-5 py-3 rounded-xl backdrop-blur-md">
                <div class="flex items-center gap-3">
                    <button onclick="toggleAudio()" id="audio-btn" class="px-4 py-1.5 cyber-btn text-cyan-400 text-xs font-bold rounded-lg flex items-center gap-2">
                        <i class="fa-solid fa-volume-high" id="audio-icon"></i> SFX: ACTIVE
                    </button>
                    <span id="auto-refresh-badge" class="px-3 py-1.5 bg-purple-950/30 border border-purple-900/40 text-purple-400 font-bold text-xs rounded-lg">SYNC RUNTIME: ON</span>
                </div>
                <div class="flex flex-wrap gap-2">
                    <button onclick="globalAction('resume')" class="px-3 py-1.5 bg-emerald-950/30 border border-emerald-900/40 hover:border-emerald-500 text-emerald-400 font-bold text-xs rounded-lg transition-all"><i class="fa-solid fa-play mr-1"></i> RESUME MATRIX</button>
                    <button onclick="globalAction('suspend')" class="px-3 py-1.5 bg-amber-950/30 border border-amber-900/40 hover:border-amber-500 text-amber-400 font-bold text-xs rounded-lg transition-all"><i class="fa-solid fa-pause mr-1"></i> PAUSE ALL</button>
                    <button onclick="globalPurge()" class="px-3 py-1.5 bg-rose-950/30 border border-rose-900/40 hover:border-rose-500 text-rose-400 font-bold text-xs rounded-lg transition-all"><i class="fa-solid fa-radiation mr-1"></i> PURGE CORE</button>
                </div>
            </div>

            <!-- Header Branding Vector Layout -->
            <header class="text-center mb-10 relative">
                <div class="inline-block px-4 py-1.5 bg-gradient-to-r from-purple-950/50 to-cyan-950/50 border border-purple-500/30 text-purple-400 text-xs tracking-widest uppercase rounded-lg mb-3">
                    <i class="fa-solid fa-shield-halved animate-pulse mr-2 text-cyan-400"></i> SECURITY LOGISTICS SYSTEM ACTIVE
                </div>
                <h1 class="text-4xl md:text-6xl font-black tracking-widest text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 via-purple-400 to-indigo-500 font-orbitron text-neon-cyan">VIP UPTIME MATRIX</h1>
                <p class="text-xs text-gray-500 tracking-widest mt-2 uppercase font-mono">POWERED BY <span class="text-purple-400 font-bold text-neon-purple">SPEED_X</span> • SECURED ENGINE v6.0</p>
            </header>

            <!-- Metrics Core Status Dashboard -->
            <div class="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8">
                <div class="matrix-panel p-5 rounded-xl text-center border-b-2 border-cyan-500 overflow-hidden">
                    <div class="scanner-line opacity-20"></div>
                    <h3 class="text-xs text-cyan-400/70 uppercase tracking-wider mb-1 font-bold">Total Signals</h3>
                    <p id="stat-total" class="text-4xl font-black text-cyan-400 tracking-tighter">0</p>
                </div>
                <div class="matrix-panel p-5 rounded-xl text-center border-b-2 border-purple-500">
                    <h3 class="text-xs text-purple-400/70 uppercase tracking-wider mb-1 font-bold">Active Tracks</h3>
                    <p id="stat-active" class="text-4xl font-black text-purple-400 tracking-tighter">0</p>
                </div>
                <div class="matrix-panel p-5 rounded-xl text-center border-b-2 border-emerald-500">
                    <h3 class="text-xs text-emerald-400/70 uppercase tracking-wider mb-1 font-bold">Grid Secure (UP)</h3>
                    <p id="stat-up" class="text-4xl font-black text-emerald-400 tracking-tighter text-neon-emerald">0</p>
                </div>
                <div class="matrix-panel p-5 rounded-xl text-center border-b-2 border-rose-500">
                    <h3 class="text-xs text-rose-400/70 uppercase tracking-wider mb-1 font-bold">Breached (DOWN)</h3>
                    <p id="stat-down" class="text-4xl font-black text-rose-400 tracking-tighter text-shadow">0</p>
                </div>
                <div class="matrix-panel p-5 rounded-xl text-center border-b-2 border-amber-500 col-span-2 md:col-span-1">
                    <h3 class="text-xs text-amber-400/70 uppercase tracking-wider mb-1 font-bold">Total Pings</h3>
                    <p id="stat-checks" class="text-4xl font-black text-amber-400 tracking-tighter">0</p>
                </div>
            </div>

            <!-- Double Workspace Columns -->
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
                <!-- Endpoint Insertion Control Box -->
                <div class="matrix-panel p-6 rounded-2xl lg:col-span-2 border border-purple-500/10 shadow-2xl">
                    <h2 class="text-sm font-bold text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-purple-400 mb-6 flex items-center gap-2 uppercase tracking-widest font-orbitron">
                        <i class="fa-solid fa-bolt text-cyan-400"></i> INJECT MONITOR NETWORK TARGET
                    </h2>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-5 mb-5">
                        <div>
                            <label class="block text-xs font-bold text-cyan-400/80 mb-1.5 uppercase tracking-wide">Target Descriptor / Alias</label>
                            <div class="relative">
                                <i class="fa-solid fa-signature absolute left-3.5 top-3.5 text-purple-500/40 text-xs"></i>
                                <input type="text" id="mon-name" placeholder="e.g. VIP API Mainframe" class="w-full bg-black/60 border border-purple-950 rounded-lg pl-10 pr-4 py-2.5 text-white placeholder-gray-700 focus:outline-none focus:border-cyan-500 text-xs">
                            </div>
                        </div>
                        <div>
                            <label class="block text-xs font-bold text-cyan-400/80 mb-1.5 uppercase tracking-wide">Routing Endpoint URL</label>
                            <div class="relative">
                                <i class="fa-solid fa-link absolute left-3.5 top-3.5 text-purple-500/40 text-xs"></i>
                                <input type="url" id="mon-url" placeholder="https://endpoint.com/health" class="w-full bg-black/60 border border-purple-950 rounded-lg pl-10 pr-4 py-2.5 text-white placeholder-gray-700 focus:outline-none focus:border-cyan-500 text-xs">
                            </div>
                        </div>
                    </div>
                    <div class="mb-6">
                        <label class="block text-xs font-bold text-cyan-400/80 mb-1.5 uppercase tracking-wide">Transmission Duty Cycle</label>
                        <select id="mon-interval" class="w-full bg-black/60 border border-purple-950 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-cyan-500 text-xs cursor-pointer">
                            <option value="1">Hyper-Pulse Engine Mode (1 Minute)</option>
                            <option value="5" selected>Standard Premium Verification (5 Minutes)</option>
                            <option value="15">Balanced Matrix Grid Logic (15 Minutes)</option>
                            <option value="30">Deep Sequence Resource Safe (30 Minutes)</option>
                        </select>
                    </div>
                    <button onclick="deployMonitor()" class="w-full bg-gradient-to-r from-cyan-500 via-purple-600 to-indigo-600 hover:from-cyan-400 hover:to-indigo-500 text-black font-black py-3 rounded-xl tracking-widest uppercase text-xs font-orbitron shadow-lg transition-all">
                        <i class="fa-solid fa-satellite-dish mr-1.5 text-sm"></i> DEPLOY TARGET SEQUENCE
                    </button>
                </div>

                <!-- Global Logic Configuration Dashboard -->
                <div class="matrix-panel p-6 rounded-2xl border border-purple-500/10 flex flex-col justify-between shadow-2xl">
                    <div>
                        <h2 class="text-sm font-bold text-purple-400 mb-6 flex items-center gap-2 uppercase tracking-widest font-orbitron"><i class="fa-solid fa-gears text-purple-400"></i> KERNEL CONFIG</h2>
                        <div class="mb-4">
                            <label class="block text-xs font-bold text-purple-400/80 mb-2 uppercase tracking-wide">Connection Deadline (Sec)</label>
                            <input type="number" id="settings-timeout" min="2" max="60" class="w-full bg-black/60 border border-purple-950 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-purple-500 text-xs">
                        </div>
                        <div class="mb-4 flex items-center justify-between bg-black/50 border border-purple-950/50 p-3 rounded-lg">
                            <span class="text-xs font-bold text-purple-400/80 uppercase tracking-wide">Live Stream Synchronizer</span>
                            <input type="checkbox" id="settings-refresh" class="w-4 h-4 accent-purple-500 cursor-pointer">
                        </div>
                    </div>
                    <button onclick="saveGlobalConfig()" class="w-full px-4 py-2.5 text-center rounded-xl font-bold text-xs tracking-widest uppercase text-purple-400 cyber-btn cyber-btn-purple transition-all">SAVE KERNEL SETTINGS</button>
                </div>
            </div>

            <!-- Live Stream Filter/Searching Control Board -->
            <div class="bg-black/60 border border-purple-950/40 p-4 rounded-xl mb-6 flex flex-col md:flex-row gap-4 items-center justify-between backdrop-blur-md">
                <div class="flex flex-wrap items-center gap-3 w-full md:w-auto">
                    <div class="relative w-full sm:w-64">
                        <i class="fa-solid fa-search absolute left-3 top-3 text-purple-500/60 text-xs"></i>
                        <input type="text" id="search-bar" oninput="applyFiltersAndSorting()" placeholder="Search designated channel traces..." class="w-full bg-black/80 border border-purple-950 rounded-lg pl-9 pr-4 py-2 text-xs focus:outline-none focus:border-cyan-500 text-gray-300">
                    </div>
                    <div class="flex bg-black/80 border border-purple-950 p-1 rounded-lg text-xs font-bold">
                        <button onclick="setStatusFilter('ALL')" id="tab-ALL" class="px-3 py-1.5 rounded bg-purple-950 text-purple-400">ALL TARGETS</button>
                        <button onclick="setStatusFilter('UP')" id="tab-UP" class="px-3 py-1.5 rounded text-gray-500 hover:text-cyan-400">SECURE (UP)</button>
                        <button onclick="setStatusFilter('DOWN')" id="tab-DOWN" class="px-3 py-1.5 rounded text-gray-500 hover:text-rose-400">CRITICAL (DOWN)</button>
                        <button onclick="setStatusFilter('STOPPED')" id="tab-STOPPED" class="px-3 py-1.5 rounded text-gray-500 hover:text-purple-400">SUSPENDED</button>
                    </div>
                </div>
                <div class="flex items-center gap-3 w-full md:w-auto justify-end">
                    <span class="text-xs text-gray-500 uppercase tracking-widest"><i class="fa-solid fa-sort mr-1"></i> Sequence Order:</span>
                    <select id="sort-engine" onchange="applyFiltersAndSorting()" class="bg-black border border-purple-950 rounded-lg px-3 py-2 text-xs text-gray-300 focus:outline-none focus:border-purple-500 cursor-pointer">
                        <option value="name">Identifier Tag</option>
                        <option value="uptime">Health Percentage</option>
                        <option value="response_time">Response Latency</option>
                    </select>
                    <button onclick="downloadBackup()" class="px-3 py-2 text-xs font-bold rounded-lg text-cyan-400 cyber-btn transition-all uppercase tracking-widest">DUMP BACKUP</button>
                </div>
            </div>

            <!-- Dedicated Channel Transmission Targets Grid -->
            <div id="monitors-grid" class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8"></div>

            <!-- Realtime Terminal Log Operations Panel -->
            <div class="mb-6">
                <div id="terminal-log" class="terminal-view p-4 text-xs text-cyan-400 space-y-1 rounded-xl">
                    <div>[SYSTEM GATEWAY KERNEL LEVEL INITIALIZING] Main cryptographic verification routines loaded...</div>
                </div>
            </div>

            <footer class="text-center text-xs text-gray-700 border-t border-purple-950/20 pt-6">
                <p>&copy; 2026 <span class="text-purple-500/40 font-bold">SPEED_X</span> • AUTHORIZED SYSTEM INFRASTRUCTURE FRAMEWORK LABS.</p>
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
                    gain.gain.setValueAtTime(0.04, audioCtx.currentTime);
                    osc.start(); osc.stop(audioCtx.currentTime + 0.1);
                } else if (type === 'alert') {
                    osc.type = 'sawtooth'; osc.frequency.setValueAtTime(180, audioCtx.currentTime);
                    gain.gain.setValueAtTime(0.08, audioCtx.currentTime);
                    osc.start(); osc.stop(audioCtx.currentTime + 0.2);
                } else if (type === 'click') {
                    osc.type = 'square'; osc.frequency.setValueAtTime(600, audioCtx.currentTime);
                    gain.gain.setValueAtTime(0.02, audioCtx.currentTime);
                    osc.start(); osc.stop(audioCtx.currentTime + 0.03);
                }
            }

            function printTerminalLog(msg, isErr=false) {
                const term = document.getElementById('terminal-log');
                const timestamp = new Date().toISOString().slice(11, 19);
                const logNode = document.createElement('div');
                let theme = isErr ? 'text-rose-500' : 'text-cyan-400';
                logNode.innerHTML = `<span class="text-purple-600">[${timestamp}]</span> <span class="${theme}">${msg}</span>`;
                term.appendChild(logNode);
                term.scrollTop = term.scrollHeight;
            }

            function toggleAudio() {
                isAudioEnabled = !isAudioEnabled;
                const btn = document.getElementById('audio-btn');
                btn.innerHTML = isAudioEnabled ? `<i class="fa-solid fa-volume-high"></i> SFX: ACTIVE` : `<i class="fa-solid fa-volume-xmark"></i> SFX: MUTED`;
                playSoundFx('click');
            }

            function showToast(message, type = 'info') {
                const toast = document.createElement('div');
                let theme = type === 'success' ? 'border-emerald-500 text-emerald-400' : type === 'error' ? 'border-rose-500 text-rose-400' : 'border-cyan-500 text-cyan-400';
                toast.className = `matrix-panel px-4 py-3 rounded-xl border-l-4 ${theme} shadow-2xl text-xs flex items-center gap-2`;
                toast.innerHTML = `<span>${message}</span>`;
                document.getElementById('toast-container').appendChild(toast);
                setTimeout(() => toast.remove(), 3500);
            }

            particlesJS('particles-js', {
                "particles": {
                    "number": { "value": 50 }, "color": { "value": "#a855f7" },
                    "opacity": { "value": 0.2 }, "size": { "value": 2 },
                    "line_linked": { "enable": true, "distance": 130, "color": "#06b6d4", "opacity": 0.08 },
                    "move": { "enable": true, "speed": 1.0 }
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
                    if (!isSilent) printTerminalLog("Database synchronized with memory registries.");
                } catch (err) { 
                    printTerminalLog("CRITICAL MAIN INTERFACE SYNC ERROR.", true); 
                }
            }

            function setStatusFilter(status) {
                playSoundFx('click');
                activeStatusFilter = status;
                ['ALL', 'UP', 'DOWN', 'STOPPED'].forEach(st => {
                    document.getElementById(`tab-${st}`).className = st === status ? "px-3 py-1.5 rounded bg-purple-950 text-purple-400" : "px-3 py-1.5 rounded text-gray-500 hover:text-cyan-400";
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
                container.innerHTML = dataList.length === 0 ? `<div class="matrix-panel p-12 rounded-xl text-center text-xs col-span-2 text-gray-600 tracking-wider">NO MONITOR NODES MATRICES IN VIEW REGISTRY.</div>` : '';
                dataList.forEach(m => {
                    let borderTheme = m.status === 'UP' ? 'border-l-emerald-500 cyber-glow-cyan' : m.status === 'DOWN' ? 'border-l-rose-500 cyber-glow-purple' : 'border-l-gray-700';
                    let badge = m.status === 'UP' ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" : m.status === 'DOWN' ? "bg-rose-500/10 text-rose-400 border-rose-500/20" : "bg-gray-900 text-gray-500 border-gray-800";
                    const card = document.createElement('div');
                    card.className = `matrix-panel p-5 rounded-xl border-l-4 ${borderTheme}`;
                    card.innerHTML = `
                        <div class="flex justify-between items-start mb-3 gap-2">
                            <div>
                                <h3 class="text-sm font-bold text-gray-100 font-orbitron tracking-wide">${m.name} <span class="text-xs text-purple-400 font-mono">[${m.status_code}]</span></h3>
                                <p class="text-xs text-cyan-600/70 break-all select-all font-mono mt-0.5">${m.url}</p>
                            </div>
                            <span class="px-2 py-0.5 text-[10px] rounded border uppercase font-bold tracking-wider shrink-0 ${badge}">${m.status}</span>
                        </div>
                        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 bg-black/50 border border-purple-950/20 p-2.5 rounded-lg text-xs text-gray-400 mb-4">
                            <div>Latency: <span class="text-cyan-400 font-bold">${m.response_time}ms</span></div>
                            <div>Health: <span class="text-purple-400 font-bold">${m.uptime}%</span></div>
                            <div>Pings: <span class="text-amber-400 font-bold">${m.success_checks}/${m.total_checks}</span></div>
                            <div>Cycle: <span class="text-white font-bold">${m.interval}m</span></div>
                        </div>
                        <div class="flex gap-2">
                            <button onclick="toggleChannel('${m.id}')" class="px-3 py-1 bg-black/40 border border-purple-950 hover:border-purple-500 text-gray-300 rounded-lg text-xs transition-all">${m.is_active ? 'Suspend' : 'Activate'}</button>
                            <button onclick="forcePing('${m.id}')" class="px-3 py-1 bg-cyan-950/20 text-cyan-400 border border-cyan-900/40 hover:border-cyan-500 rounded-lg text-xs transition-all">Pulse Manual</button>
                            <button onclick="destroyChannel('${m.id}')" class="px-3 py-1 text-rose-400 border border-transparent hover:border-rose-900 rounded-lg text-xs font-bold ml-auto transition-all">Terminate</button>
                        </div>`;
                    container.appendChild(card);
                });
            }

            async function deployMonitor() {
                playSoundFx('click');
                const name = document.getElementById('mon-name').value.trim();
                const url = document.getElementById('mon-url').value.trim();
                const interval = document.getElementById('mon-interval').value;
                if(!name || !url) return showToast('Execution failed: Missing properties!', 'error');
                
                printTerminalLog(`Injecting path vector: ${name}...`);
                await fetch('/api/monitors', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, url, interval: parseInt(interval) })
                });
                document.getElementById('mon-name').value = '';
                document.getElementById('mon-url').value = '';
                showToast('Target signal accepted by matrix module.', 'success');
                playSoundFx('success');
                refreshDashboard(true);
            }

            async function saveGlobalConfig() {
                playSoundFx('click');
                const timeout = parseInt(document.getElementById('settings-timeout').value);
                const autoRefresh = document.getElementById('settings-refresh').checked;
                await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ global_timeout: timeout, auto_refresh: autoRefresh })
                });
                printTerminalLog("Kernel synchronization cycle committed.");
                showToast('Kernel modifications active.', 'success');
                refreshDashboard(true);
            }

            function initAutoRefreshLoop(status) {
                if(autoRefreshIntervalId) clearInterval(autoRefreshIntervalId);
                if(status) autoRefreshIntervalId = setInterval(() => refreshDashboard(true), 15000);
            }

            async function forcePing(id) {
                playSoundFx('click');
                printTerminalLog(`Forcing physical manual connection scan to channel ID: ${id}`);
                await fetch(`/api/monitors/${id}/ping`, { method: 'POST' });
                refreshDashboard(true);
            }

            async function toggleChannel(id) {
                playSoundFx('click');
                await fetch(`/api/monitors/${id}/toggle`, { method: 'POST' });
                refreshDashboard(true);
            }

            async function globalAction(action) {
                playSoundFx('click');
                printTerminalLog(`Broadcasting global operation execution: [${action.toUpperCase()}]`);
                await fetch(`/api/global/${action}`, { method: 'POST' });
                refreshDashboard(true);
            }

            async function globalPurge() {
                playSoundFx('alert');
                if(confirm('Wipe core tracking allocations database completely?')) {
                    await fetch('/api/global/purge', { method: 'POST' });
                    printTerminalLog("CRITICAL LOG: Global data purge commanded.", true);
                    refreshDashboard(true);
                }
            }

            async function destroyChannel(id) {
                playSoundFx('alert');
                if(confirm('Completely isolate and terminate channel node?')) {
                    await fetch(`/api/monitors/${id}`, { method: 'DELETE' });
                    printTerminalLog(`Channel ${id} terminated and wiped.`);
                    refreshDashboard(true);
                }
            }

            function downloadBackup() {
                playSoundFx('click');
                if(currentCachedMonitors.length === 0) return;
                const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(currentCachedMonitors, null, 2));
                const anchor = document.createElement('a');
                anchor.setAttribute("href", dataStr); anchor.setAttribute("download", "matrix_core_backup.json");
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
