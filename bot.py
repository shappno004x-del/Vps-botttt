# ==================== bot.py (পুরো ফাইল) ====================
import os
import logging
import sqlite3
import json
import hashlib
import secrets
import string
import random
import asyncio
import time
import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
import html

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.client.default import DefaultBotProperties

# ==================== CONFIG ====================
BOT_TOKEN = os.environ.get("8503489370:AAHOdNZKBvpuJHq1FDWgCtReh7GOG5Foh6U")
if not BOT_TOKEN:
    BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

OWNER_ID = int(os.environ.get("OWNER_ID", 7875541866))

BASE_DIR = Path(__file__).parent.absolute()
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / 'vps_bot.db'
WEBSITES_DIR = BASE_DIR / 'websites'
WEBSITES_DIR.mkdir(exist_ok=True)
BACKUP_DIR = BASE_DIR / 'backups'
BACKUP_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())

# ==================== STORAGE PLANS ====================
DEFAULT_PLANS = {
    '64': {'storage': 64, 'ram': 2, 'price': 30, 'days': 7},
    '128': {'storage': 128, 'ram': 4, 'price': 50, 'days': 10},
    '256': {'storage': 256, 'ram': 8, 'price': 60, 'days': 10},
    '512': {'storage': 512, 'ram': 16, 'price': 80, 'days': 15},
    '1024': {'storage': 1024, 'ram': 32, 'price': 110, 'days': 15},
    '2048': {'storage': 2048, 'ram': 64, 'price': 250, 'days': 30}
}

# ==================== DATABASE ====================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        referrals INTEGER DEFAULT 0,
        tokens INTEGER DEFAULT 10,
        join_date TEXT,
        referred_by INTEGER DEFAULT 0,
        banned BOOLEAN DEFAULT 0
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS vps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT,
        password TEXT,
        image_url TEXT,
        storage_gb INTEGER,
        ram_gb INTEGER,
        token_cost INTEGER,
        days INTEGER,
        created_at TEXT,
        expires_at TEXT,
        status TEXT DEFAULT 'active',
        website_url TEXT UNIQUE,
        website_path TEXT,
        used_storage INTEGER DEFAULT 0,
        auto_restart BOOLEAN DEFAULT 0,
        restart_count INTEGER DEFAULT 0
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER,
        referred_id INTEGER,
        tokens_earned INTEGER,
        created_at TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        added_by INTEGER,
        added_at TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS coupons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        tokens INTEGER,
        created_by INTEGER,
        created_at TEXT,
        expires_at TEXT,
        used_by INTEGER DEFAULT 0,
        used BOOLEAN DEFAULT 0
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS backup_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT,
        size INTEGER,
        created_at TEXT
    )''')
    
    for key, plan in DEFAULT_PLANS.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", 
                  (f'plan_{key}', json.dumps(plan)))
    
    c.execute("INSERT OR IGNORE INTO admins (user_id, added_by, added_at) VALUES (?, ?, ?)",
              (OWNER_ID, OWNER_ID, datetime.now().isoformat()))
    
    conn.commit()
    conn.close()

init_db()

# ==================== BACKUP FUNCTIONS ====================
def create_backup():
    """Create a full backup of the bot data"""
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"backup_{timestamp}.zip"
        backup_path = BACKUP_DIR / backup_filename
        
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Backup database
            if DB_PATH.exists():
                zipf.write(DB_PATH, 'data/vps_bot.db')
            
            # Backup websites
            if WEBSITES_DIR.exists():
                for item in WEBSITES_DIR.rglob('*'):
                    if item.is_file():
                        zipf.write(item, f"websites/{item.relative_to(WEBSITES_DIR)}")
            
            # Backup config
            config_file = BASE_DIR / 'config.json'
            if config_file.exists():
                zipf.write(config_file, 'config.json')
            
            # Backup servers_db
            servers_db = BASE_DIR / 'servers_db.json'
            if servers_db.exists():
                zipf.write(servers_db, 'servers_db.json')
        
        # Log backup
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO backup_log (filename, size, created_at) VALUES (?, ?, ?)",
                  (backup_filename, backup_path.stat().st_size, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        # Keep only last 10 backups
        cleanup_old_backups()
        
        return backup_path, backup_filename
    except Exception as e:
        logger.error(f"Backup creation failed: {e}")
        return None, None

def cleanup_old_backups():
    """Keep only last 10 backups"""
    try:
        backups = sorted(BACKUP_DIR.glob('backup_*.zip'), key=lambda x: x.stat().st_mtime, reverse=True)
        for backup in backups[10:]:
            backup.unlink()
            logger.info(f"Deleted old backup: {backup.name}")
    except Exception as e:
        logger.error(f"Cleanup old backups failed: {e}")

def restore_backup(zip_file_path):
    """Restore from a backup zip file"""
    try:
        with zipfile.ZipFile(zip_file_path, 'r') as zipf:
            zipf.extractall(BASE_DIR)
        return True, "Restore successful!"
    except Exception as e:
        return False, f"Restore failed: {str(e)}"

async def auto_backup_worker():
    """Auto backup every 4 hours"""
    while True:
        try:
            await asyncio.sleep(14400)  # 4 hours = 14400 seconds
            
            backup_path, filename = create_backup()
            if backup_path and backup_path.exists():
                # Send to owner
                await bot.send_document(
                    chat_id=OWNER_ID,
                    document=FSInputFile(str(backup_path)),
                    caption=f"📦 <b>ᴀᴜᴛᴏ ʙᴀᴄᴋᴜᴘ</b>\n\n"
                            f"📁 {filename}\n"
                            f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"⚡ {backup_path.stat().st_size // 1024} KB\n\n"
                            f"<i>Automated 4-hour backup</i>"
                )
                backup_path.unlink()
                logger.info(f"Auto backup sent: {filename}")
            else:
                logger.error("Auto backup failed")
        except Exception as e:
            logger.error(f"Auto backup worker error: {e}")

# ==================== DATABASE FUNCTIONS ====================
def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def get_user_by_username(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    conn.close()
    return user

def create_user(user_id, username, referred_by=0):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, join_date, referred_by) VALUES (?, ?, ?, ?)",
              (user_id, username, datetime.now().isoformat(), referred_by))
    conn.commit()
    conn.close()

def update_user(user_id, tokens=None, referrals=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if tokens is not None:
        c.execute("UPDATE users SET tokens = tokens + ? WHERE user_id = ?", (tokens, user_id))
    if referrals is not None:
        c.execute("UPDATE users SET referrals = referrals + ? WHERE user_id = ?", (referrals, user_id))
    conn.commit()
    conn.close()

def get_plan(plan_key):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (f'plan_{plan_key}',))
    result = c.fetchone()
    conn.close()
    if result:
        return json.loads(result[0])
    return None

def get_all_plans():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT key, value FROM settings WHERE key LIKE 'plan_%'")
    results = c.fetchall()
    conn.close()
    plans = {}
    for key, value in results:
        plan_key = key.replace('plan_', '')
        plans[plan_key] = json.loads(value)
    return plans

def update_plan(plan_key, storage, ram, price, days):
    plan = {'storage': storage, 'ram': ram, 'price': price, 'days': days}
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", 
              (f'plan_{plan_key}', json.dumps(plan)))
    conn.commit()
    conn.close()

def create_vps(user_id, name, password, image_url, plan_key):
    plan = get_plan(plan_key)
    if not plan:
        return None, "Invalid plan"
    
    user = get_user(user_id)
    if user[3] < plan['price']:
        return None, f"Not enough tokens! Need {plan['price']} tokens"
    
    update_user(user_id, tokens=-plan['price'])
    
    website_name = f"vps_{user_id}_{int(time.time())}"
    website_path = WEBSITES_DIR / website_name
    website_path.mkdir(parents=True, exist_ok=True)
    
    index_html = f'''<!DOCTYPE html>
<html>
<head>
<title>{name}'s VPS</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Courier New',monospace; background:#000; color:#00ff00; min-height:100vh; display:flex; justify-content:center; align-items:center; }}
.container {{ background:#0a0a0a; border:2px solid #00ff00; border-radius:10px; padding:40px; max-width:500px; width:90%; box-shadow:0 0 40px rgba(0,255,0,0.2); }}
.header {{ text-align:center; margin-bottom:30px; }}
.header img {{ max-width:150px; border-radius:50%; border:3px solid #00ff00; margin-bottom:15px; }}
.header h1 {{ color:#00ff00; font-size:24px; }}
.login-form {{ display:flex; flex-direction:column; gap:15px; }}
.login-form input {{ background:#000; border:1px solid #00ff00; color:#00ff00; padding:12px; border-radius:5px; font-family:'Courier New',monospace; }}
.login-form button {{ background:transparent; border:2px solid #00ff00; color:#00ff00; padding:12px; border-radius:5px; cursor:pointer; font-weight:bold; }}
.login-form button:hover {{ background:#00ff00; color:#000; }}
.file-manager {{ display:none; margin-top:20px; }}
.file-manager.active {{ display:block; }}
.file-item {{ display:flex; justify-content:space-between; padding:8px 10px; border-bottom:1px solid rgba(0,255,0,0.1); font-size:13px; }}
.upload-form {{ margin-top:15px; display:flex; gap:10px; }}
.status {{ text-align:center; padding:10px; margin-top:15px; border:1px solid #00ff00; border-radius:5px; font-size:12px; }}
.error {{ color:#ff0000; text-align:center; padding:10px; border:1px solid #ff0000; border-radius:5px; display:none; }}
</style>
</head>
<body>
<div class="container">
<div class="header">
<img src="{image_url}" alt="{name}">
<h1>🚀 {name}'s VPS</h1>
</div>
<div id="errorMsg" class="error"></div>
<form id="loginForm" class="login-form" onsubmit="login(event)">
<input type="password" id="password" placeholder="Enter Password..." required>
<button type="submit">🔓 AUTHENTICATE</button>
</form>
<div id="fileManager" class="file-manager">
<div style="display:flex; justify-content:space-between; margin-bottom:15px;">
<span>📁 FILES</span>
<button onclick="logout()" style="background:transparent; border:1px solid #ff0000; color:#ff0000; padding:5px 15px; border-radius:5px; cursor:pointer;">LOGOUT</button>
</div>
<div id="fileList"></div>
<form class="upload-form" onsubmit="uploadFile(event)">
<input type="file" id="uploadInput" style="flex:1; background:#000; border:1px solid #00ff00; color:#00ff00; padding:8px; border-radius:5px;">
<button type="submit" style="background:transparent; border:1px solid #00ff00; color:#00ff00; padding:8px 15px; border-radius:5px; cursor:pointer;">📤 UPLOAD</button>
</form>
<div class="status" id="status">✅ Running | Storage: 0/{plan['storage']}GB</div>
</div>
</div>
<script>
const VPS_ID = "{vps_id}";
async function login(event) {{
event.preventDefault();
const password = document.getElementById('password').value;
const response = await fetch(`/vps_login/${{VPS_ID}}`, {{
method: 'POST',
headers: {{ 'Content-Type': 'application/json' }},
body: JSON.stringify({{ password: password }})
}});
const data = await response.json();
if (data.status === 'ok') {{
document.getElementById('loginForm').style.display = 'none';
document.getElementById('fileManager').classList.add('active');
document.getElementById('errorMsg').style.display = 'none';
loadFiles();
loadStatus();
}} else {{
document.getElementById('errorMsg').textContent = '❌ ' + data.message;
document.getElementById('errorMsg').style.display = 'block';
}}
}}
function logout() {{
document.getElementById('loginForm').style.display = 'flex';
document.getElementById('fileManager').classList.remove('active');
document.getElementById('password').value = '';
}}
async function loadFiles() {{
const response = await fetch(`/vps_files/${{VPS_ID}}`);
const data = await response.json();
const list = document.getElementById('fileList');
list.innerHTML = '';
if (data.files && data.files.length > 0) {{
data.files.forEach(f => {{
const div = document.createElement('div');
div.className = 'file-item';
div.innerHTML = `<span>📄 ${{f.name}}</span><span>${{(f.size/1024).toFixed(1)}} KB</span>`;
list.appendChild(div);
}});
}} else {{
list.innerHTML = '<div style="text-align:center; opacity:0.4; padding:20px;">No files uploaded</div>';
}}
}}
async function loadStatus() {{
const response = await fetch(`/vps_status/${{VPS_ID}}`);
const data = await response.json();
document.getElementById('status').textContent = `✅ ${{data.status}} | Storage: ${{data.used_storage}}GB/${{data.total_storage}}GB`;
}}
async function uploadFile(event) {{
event.preventDefault();
const file = document.getElementById('uploadInput').files[0];
if (!file) return;
const formData = new FormData();
formData.append('file', file);
const response = await fetch(`/vps_upload/${{VPS_ID}}`, {{ method: 'POST', body: formData }});
const data = await response.json();
if (data.status === 'ok') {{
document.getElementById('uploadInput').value = '';
loadFiles();
loadStatus();
}} else {{
alert('Upload failed: ' + data.message);
}}
}}
</script>
</body>
</html>'''
    
    with open(website_path / 'index.html', 'w', encoding='utf-8') as f:
        f.write(index_html)
    
    website_url = f"/vps/{website_name}"
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO vps (user_id, name, password, image_url, storage_gb, ram_gb, token_cost, days, created_at, expires_at, website_url, website_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, name, password, image_url, plan['storage'], plan['ram'], 
          plan['price'], plan['days'], datetime.now().isoformat(),
          (datetime.now() + timedelta(days=plan['days'])).isoformat(),
          website_url, str(website_path)))
    
    vps_id = c.lastrowid
    conn.commit()
    conn.close()
    
    return vps_id, website_url

def get_user_vps(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, password, image_url, storage_gb, ram_gb, created_at, expires_at, status, website_url, used_storage FROM vps WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    vps_list = c.fetchall()
    conn.close()
    return vps_list

def get_all_vps():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT v.id, v.user_id, u.username, v.name, v.password, v.image_url, v.storage_gb, v.ram_gb, 
               v.created_at, v.expires_at, v.status, v.website_url, v.used_storage
        FROM vps v
        JOIN users u ON v.user_id = u.user_id
        ORDER BY v.created_at DESC
    """)
    vps_list = c.fetchall()
    conn.close()
    return vps_list

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, tokens, referrals, banned FROM users ORDER BY user_id DESC")
    users = c.fetchall()
    conn.close()
    return users

def is_admin(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def ban_user(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET banned = 1 WHERE username = ?", (username,))
    conn.commit()
    conn.close()

def unban_user(username):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET banned = 0 WHERE username = ?", (username,))
    conn.commit()
    conn.close()

def delete_vps(vps_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT website_path FROM vps WHERE id = ?", (vps_id,))
    result = c.fetchone()
    if result and result[0]:
        path = Path(result[0])
        if path.exists():
            shutil.rmtree(path)
    c.execute("DELETE FROM vps WHERE id = ?", (vps_id,))
    conn.commit()
    conn.close()

def toggle_vps_status(vps_id, status):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE vps SET status = ? WHERE id = ?", (status, vps_id))
    conn.commit()
    conn.close()

def create_coupon(tokens, created_by, days=30):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO coupons (code, tokens, created_by, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?)
    """, (code, tokens, created_by, datetime.now().isoformat(),
          (datetime.now() + timedelta(days=days)).isoformat()))
    conn.commit()
    conn.close()
    return code

def use_coupon(code, user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, tokens, used, expires_at FROM coupons WHERE code = ?", (code,))
    coupon = c.fetchone()
    if not coupon:
        conn.close()
        return False, "Invalid coupon code"
    if coupon[2] == 1:
        conn.close()
        return False, "Coupon already used"
    if datetime.now().isoformat() > coupon[3]:
        conn.close()
        return False, "Coupon expired"
    c.execute("UPDATE coupons SET used = 1, used_by = ? WHERE id = ?", (user_id, coupon[0]))
    c.execute("UPDATE users SET tokens = tokens + ? WHERE user_id = ?", (coupon[1], user_id))
    conn.commit()
    conn.close()
    return True, coupon[1]

def get_all_coupons():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT code, tokens, created_at, expires_at, used, used_by FROM coupons ORDER BY created_at DESC")
    coupons = c.fetchall()
    conn.close()
    return coupons

def get_user_referrals(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT referred_id, tokens_earned, created_at FROM referrals WHERE referrer_id = ? ORDER BY created_at DESC", (user_id,))
    referrals = c.fetchall()
    conn.close()
    return referrals

def get_backup_log():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT filename, size, created_at FROM backup_log ORDER BY created_at DESC LIMIT 10")
    logs = c.fetchall()
    conn.close()
    return logs

# ==================== KEYBOARDS ====================
def get_main_keyboard():
    keyboard = [
        [KeyboardButton(text="🔴 CREATE VPS")],
        [KeyboardButton(text="📊 REFER & EARN"), KeyboardButton(text="🏆 LEADERBOARD")],
        [KeyboardButton(text="🛒 STORE"), KeyboardButton(text="🔄 TRANSFER")],
        [KeyboardButton(text="📁 MY VPS"), KeyboardButton(text="👤 MY PROFILE")],
        [KeyboardButton(text="🆘 SUPPORT"), KeyboardButton(text="⚙️ SYSTEM")],
        [KeyboardButton(text="🌐 LANGUAGE")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_admin_keyboard():
    keyboard = [
        [KeyboardButton(text="🛡️ ADMIN PANEL")],
        [KeyboardButton(text="🔴 CREATE VPS")],
        [KeyboardButton(text="📊 REFER & EARN"), KeyboardButton(text="🏆 LEADERBOARD")],
        [KeyboardButton(text="📁 MY VPS"), KeyboardButton(text="👤 MY PROFILE")],
        [KeyboardButton(text="🆘 SUPPORT"), KeyboardButton(text="⚙️ SYSTEM")],
        [KeyboardButton(text="🌐 LANGUAGE")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# ==================== STATES ====================
class VPSState(StatesGroup):
    waiting_name = State()
    waiting_password = State()
    waiting_image = State()
    waiting_plan = State()

class AdminState(StatesGroup):
    waiting_coupon_tokens = State()
    waiting_coupon_days = State()
    waiting_ban_user = State()
    waiting_unban_user = State()
    waiting_plan_key = State()
    waiting_plan_storage = State()
    waiting_plan_ram = State()
    waiting_plan_price = State()
    waiting_plan_days = State()
    waiting_restore_file = State()

class TransferState(StatesGroup):
    waiting_target = State()
    waiting_amount = State()

class CouponState(StatesGroup):
    waiting_code = State()

# ==================== COMMANDS ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    
    args = message.text.split()
    referred_by = 0
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referred_by = int(args[1].split("_")[1])
            if referred_by != user_id:
                referrer = get_user(referred_by)
                if referrer:
                    update_user(referred_by, referrals=1, tokens=5)
                    await bot.send_message(
                        referred_by,
                        f"🎉 <b>ɴᴇᴡ ʀᴇғᴇʀʀᴀʟ!</b>\n\n"
                        f"👤 @{username or 'Unknown'} ᴊᴏɪɴᴇᴅ ᴜsɪɴɢ ʏᴏᴜʀ ʟɪɴᴋ\n"
                        f"💰 +5 ᴛᴏᴋᴇɴs\n"
                        f"📊 ᴛᴏᴛᴀʟ: {referrer[2] + 1} ʀᴇғᴇʀʀᴀʟs"
                    )
        except:
            pass
    
    create_user(user_id, username, referred_by)
    user = get_user(user_id)
    
    if user[6] == 1:
        await message.answer("🚫 <b>ʏᴏᴜ ʜᴀᴠᴇ ʙᴇᴇɴ ʙᴀɴɴᴇᴅ!</b>")
        return
    
    tokens = user[3] if user else 0
    referrals = user[2] if user else 0
    is_admin_user = is_admin(user_id)
    
    keyboard = get_admin_keyboard() if is_admin_user else get_main_keyboard()
    
    await message.answer("✅ <b>ʀᴇsᴛᴏʀᴇsᴛᴏғᴀɪʀᴇsᴛᴏʀᴇ ғᴀɪʟᴇsᴛᴏɪʟᴇᴅʀᴇsᴛᴏʀᴇᴀɪᴀɪʟᴇᴅ</b> 🎉")
    await asyncio.sleep(0.5)
    
    text = f"""
👋 <b>ʜᴇʟʟᴏ, {html.escape(message.from_user.full_name)}</b> 👋

━━━━━━━━━━━━━━━━━━━━━━
📂 <b>ᴜsᴇʀ ᴅᴀsʜʙᴏᴀʀᴅ</b>
━━━━━━━━━━━━━━━━━━━━━━

🔒 <b>ɴᴀᴍᴇ:</b> {html.escape(message.from_user.full_name)}
🔒 <b>ᴜsᴇʀ ɪᴅ:</b> <code>{user_id}</code>
🔒 <b>ʀᴇғᴇʀʀᴀʟs:</b> {referrals}
🔒 <b>ᴠᴘs ᴄʀᴇᴀᴛᴇᴅ:</b> {len(get_user_vps(user_id))}
🔒 <b>ᴀᴠᴀɪʟᴀʙʟᴇ ᴠᴘs:</b> {len(get_user_vps(user_id))}

━━━━━━━━━━━━━━━━━━━━━━

⚠️ <b>ʏᴏᴜ ɴᴇᴇᴅ {max(0, 5 - referrals)} ᴍᴏʀᴇ ʀᴇғᴇʀʀᴀʟs ғᴏʀ ᴛʜᴇ ɴᴇxᴛ ᴠᴘs.</b>

ᴘᴏᴡᴇʀᴇᴅ ʙʏ <b>𝐒ʜᴀᴘᴘɴᴏ</b> 🪄
"""
    await message.answer(text, reply_markup=keyboard)

# ==================== CREATE VPS ====================
@dp.message(F.text == "🔴 CREATE VPS")
async def cmd_create_vps(message: types.Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("❌ ᴘʟᴇᴀsᴇ ᴜsᴇ /start ғɪʀsᴛ.")
        return
    
    if user[6] == 1:
        await message.answer("🚫 <b>ʏᴏᴜ ʜᴀᴠᴇ ʙᴇᴇɴ ʙᴀɴɴᴇᴅ!</b>")
        return
    
    await state.set_state(VPSState.waiting_name)
    await message.answer(
        "🔴 <b>ᴄʀᴇᴀᴛᴇ ɴᴇᴡ ᴠᴘs</b>\n\n"
        "ᴘʟᴇᴀsᴇ ᴇɴᴛᴇʀ ᴀ ɴᴀᴍᴇ ғᴏʀ ʏᴏᴜʀ ᴠᴘs ᴡᴇʙsɪᴛᴇ:\n"
        "(ᴇxᴀᴍᴘʟᴇ: <code>ᴍʏ-sᴇʀᴠᴇʀ</code>)\n\n"
        "ᴛʏᴘᴇ <code>/ᴄᴀɴᴄᴇʟ</code> ᴛᴏ ᴄᴀɴᴄᴇʟ."
    )

@dp.message(VPSState.waiting_name)
async def process_vps_name(message: types.Message, state: FSMContext):
    if message.text == "/cancel" or message.text == "/ᴄᴀɴᴄᴇʟ":
        await state.clear()
        await message.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ.", reply_markup=get_main_keyboard())
        return
    
    name = message.text.strip()
    await state.update_data(name=name)
    await state.set_state(VPSState.waiting_image)
    
    await message.answer(
        "🖼️ <b>sᴇɴᴅ ᴀɴ ɪᴍᴀɢᴇ ғᴏʀ ʏᴏᴜʀ ᴠᴘs</b>\n\n"
        "sᴇɴᴅ ᴀ ᴘʜᴏᴛᴏ ᴏʀ ɪᴍᴀɢᴇ ᴜʀʟ.\n"
        "ᴛʏᴘᴇ <code>sᴋɪᴘ</code> ᴛᴏ ᴜsᴇ ᴅᴇғᴀᴜʟᴛ.\n\n"
        "ᴛʏᴘᴇ <code>/ᴄᴀɴᴄᴇʟ</code> ᴛᴏ ᴄᴀɴᴄᴇʟ."
    )

@dp.message(VPSState.waiting_image)
async def process_vps_image(message: types.Message, state: FSMContext):
    if message.text == "/cancel" or message.text == "/ᴄᴀɴᴄᴇʟ":
        await state.clear()
        await message.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ.", reply_markup=get_main_keyboard())
        return
    
    image_url = "https://files.catbox.moe/1o431f.jpg"
    
    if message.text and message.text.lower() == "skip":
        pass
    elif message.photo:
        file = await bot.get_file(message.photo[-1].file_id)
        image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
    elif message.text and message.text.startswith("http"):
        image_url = message.text.strip()
    
    await state.update_data(image_url=image_url)
    await state.set_state(VPSState.waiting_password)
    
    await message.answer(
        "🔑 <b>sᴇᴛ ᴘᴀssᴡᴏʀᴅ ғᴏʀ ʏᴏᴜʀ ᴠᴘs</b>\n\n"
        "ᴇɴᴛᴇʀ ᴀ ᴘᴀssᴡᴏʀᴅ (ᴍɪɴ 4 ᴄʜᴀʀᴀᴄᴛᴇʀs):\n\n"
        "ᴛʏᴘᴇ <code>/ᴄᴀɴᴄᴇʟ</code> ᴛᴏ ᴄᴀɴᴄᴇʟ."
    )

@dp.message(VPSState.waiting_password)
async def process_vps_password(message: types.Message, state: FSMContext):
    if message.text == "/cancel" or message.text == "/ᴄᴀɴᴄᴇʟ":
        await state.clear()
        await message.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ.", reply_markup=get_main_keyboard())
        return
    
    password = message.text.strip()
    if len(password) < 4:
        await message.answer("❌ ᴘᴀssᴡᴏʀᴅ ᴍᴜsᴛ ʙᴇ ᴀᴛ ʟᴇᴀsᴛ 4 ᴄʜᴀʀᴀᴄᴛᴇʀs!")
        return
    
    await state.update_data(password=password)
    await state.set_state(VPSState.waiting_plan)
    
    plans = get_all_plans()
    text = "🟣 <b>sᴇʟᴇᴄᴛ ʏᴏᴜʀ ᴠᴘs ᴘʟᴀɴ</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    keyboard = []
    for key, plan in plans.items():
        text += f"📦 <b>{plan['storage']}GB</b> | 🧠 {plan['ram']}GB RAM\n"
        text += f"   💰 {plan['price']} ᴛᴏᴋᴇɴs | 📅 {plan['days']} ᴅᴀʏs\n\n"
        keyboard.append([InlineKeyboardButton(
            text=f"🔴 {plan['storage']}GB - {plan['price']} ᴛᴏᴋᴇɴs",
            callback_data=f"vps_plan|{key}"
        )])
    
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@dp.callback_query(F.data.startswith("vps_plan|"))
async def process_vps_plan(call: types.CallbackQuery, state: FSMContext):
    plan_key = call.data.split('|')[1]
    user_id = call.from_user.id
    
    data = await state.get_data()
    name = data.get('name')
    password = data.get('password')
    image_url = data.get('image_url')
    
    if not name:
        await call.answer("❌ sᴇssɪᴏɴ ᴇxᴘɪʀᴇᴅ!", show_alert=True)
        return
    
    plan = get_plan(plan_key)
    if not plan:
        await call.answer("❌ ɪɴᴠᴀʟɪᴅ ᴘʟᴀɴ!", show_alert=True)
        return
    
    user = get_user(user_id)
    if user[3] < plan['price']:
        await call.answer(f"❌ ɴᴇᴇᴅ {plan['price'] - user[3]} ᴍᴏʀᴇ ᴛᴏᴋᴇɴs!", show_alert=True)
        return
    
    vps_id, website_url = create_vps(user_id, name, password, image_url, plan_key)
    
    await state.clear()
    
    await call.message.edit_text(
        f"✅ <b>ᴠᴘs ᴄʀᴇᴀᴛᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
        f"🔴 <b>ɴᴀᴍᴇ:</b> <code>{name}</code>\n"
        f"🔑 <b>ᴘᴀssᴡᴏʀᴅ:</b> <code>{password}</code>\n"
        f"📦 <b>ᴘʟᴀɴ:</b> {plan['storage']}GB | {plan['ram']}GB RAM\n"
        f"💰 <b>ᴄᴏsᴛ:</b> {plan['price']} ᴛᴏᴋᴇɴs\n"
        f"📅 <b>ᴇxᴘɪʀᴇs:</b> {plan['days']} ᴅᴀʏs\n"
        f"🌐 <b>ᴡᴇʙsɪᴛᴇ:</b> <a href='{website_url}'>{website_url}</a>\n\n"
        f"<b>⚠️ sᴀᴠᴇ ʏᴏᴜʀ ᴘᴀssᴡᴏʀᴅ!</b>\n"
        f"ᴜsᴇ <b>📁 ᴍʏ ᴠᴘs</b> ᴛᴏ ᴠɪᴇᴡ ᴀʟʟ."
    )
    await call.answer("✅ ᴠᴘs ᴄʀᴇᴀᴛᴇᴅ!")

# ==================== MY VPS ====================
@dp.message(F.text == "📁 MY VPS")
async def cmd_my_vps(message: types.Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("❌ ᴘʟᴇᴀsᴇ ᴜsᴇ /start ғɪʀsᴛ.")
        return
    
    vps_list = get_user_vps(message.from_user.id)
    
    if not vps_list:
        await message.answer(
            "📁 <b>ɴᴏ ᴠᴘs ғᴏᴜɴᴅ</b>\n\n"
            "ᴜsᴇ <b>🔴 ᴄʀᴇᴀᴛᴇ ᴠᴘs</b> ᴛᴏ ᴄʀᴇᴀᴛᴇ ʏᴏᴜʀ ғɪʀsᴛ ᴠᴘs.",
            reply_markup=get_main_keyboard()
        )
        return
    
    text = "📁 <b>ʏᴏᴜʀ ᴠᴘs ʟɪsᴛ</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for vps in vps_list:
        status_icon = "🟢" if vps[8] == "active" else "🔴"
        used_storage = vps[10] // 1073741824 if vps[10] else 0
        text += f"{status_icon} <b>{vps[1]}</b>\n"
        text += f"   💾 {used_storage}/{vps[4]}GB | 🧠 {vps[5]}GB RAM\n"
        text += f"   📅 {vps[6][:16]}\n"
        text += f"   🌐 <a href='{vps[9]}'>{vps[9][:30]}...</a>\n"
        text += f"   🔑 <code>{vps[2]}</code>\n\n"
    
    text += "━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"ᴛᴏᴛᴀʟ: {len(vps_list)} ᴠᴘs"
    
    await message.answer(text, parse_mode="HTML")

# ==================== REFER & EARN ====================
@dp.message(F.text == "📊 REFER & EARN")
async def cmd_refer(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or str(user_id)
    
    ref_link = f"https://t.me/{bot.username}?start=ref_{user_id}"
    user = get_user(user_id)
    referrals = user[2] if user else 0
    
    text = f"""
📊 <b>ʀᴇғᴇʀ & ᴇᴀʀɴ</b>
━━━━━━━━━━━━━━━━━━━━━━

👤 <b>ʏᴏᴜʀ ʀᴇғᴇʀʀᴀʟ ʟɪɴᴋ:</b>
<code>{ref_link}</code>

📊 <b>ᴛᴏᴛᴀʟ ʀᴇғᴇʀʀᴀʟs:</b> {referrals}
💰 <b>ᴛᴏᴋᴇɴs ᴇᴀʀɴᴇᴅ:</b> {referrals * 5}

━━━━━━━━━━━━━━━━━━━━━━
🎁 <b>ʀᴇғᴇʀʀᴀʟ ʀᴇᴡᴀʀᴅs:</b>
• 5 ʀᴇғᴇʀʀᴀʟs = 1 ғʀᴇᴇ ᴠᴘs
• 10 ʀᴇғᴇʀʀᴀʟs = ᴘʀᴇᴍɪᴜᴍ ᴠᴘs
• 25 ʀᴇғᴇʀʀᴀʟs = ᴠɪᴘ ᴠᴘs

━━━━━━━━━━━━━━━━━━━━━━
💡 sʜᴀʀᴇ ᴛʜɪs ʟɪɴᴋ ᴛᴏ ʏᴏᴜʀ ғʀɪᴇɴᴅs!
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 sʜᴀʀᴇ ʟɪɴᴋ", url=f"https://t.me/share/url?url={ref_link}")],
        [InlineKeyboardButton(text="🔙 ʙᴀᴄᴋ", callback_data="back_main")]
    ])
    
    await message.answer(text, reply_markup=keyboard)

# ==================== LEADERBOARD ====================
@dp.message(F.text == "🏆 LEADERBOARD")
async def cmd_leaderboard(message: types.Message):
    users = get_all_users()
    
    if not users:
        await message.answer("🏆 <b>ɴᴏ ᴜsᴇʀs ғᴏᴜɴᴅ ʏᴇᴛ!</b>", reply_markup=get_main_keyboard())
        return
    
    text = "🏆 <b>ʟᴇᴀᴅᴇʀʙᴏᴀʀᴅ</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for i, (user_id, username, tokens, referrals, banned) in enumerate(users[:10], 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} <b>{html.escape(username or f'user_{user_id}')}</b>\n"
        text += f"   💰 {tokens} ᴛᴏᴋᴇɴs | 📊 {referrals} ʀᴇғᴇʀʀᴀʟs\n\n"
    
    text += "━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"ᴛᴏᴛᴀʟ ᴜsᴇʀs: {len(users)}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 ʙᴀᴄᴋ", callback_data="back_main")]
    ])
    
    await message.answer(text, reply_markup=keyboard)

# ==================== MY PROFILE ====================
@dp.message(F.text == "👤 MY PROFILE")
async def cmd_profile(message: types.Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("❌ ᴘʟᴇᴀsᴇ ᴜsᴇ /start ғɪʀsᴛ.")
        return
    
    user_id, username, referrals, tokens, join_date, referred_by, banned = user
    vps_list = get_user_vps(user_id)
    
    text = f"""
👤 <b>ᴍʏ ᴘʀᴏғɪʟᴇ</b>
━━━━━━━━━━━━━━━━━━━━━━

🔒 <b>ᴜsᴇʀ ɪᴅ:</b> <code>{user_id}</code>
👤 <b>ᴜsᴇʀɴᴀᴍᴇ:</b> @{username if username else 'ɴᴏɴᴇ'}
📅 <b>ᴊᴏɪɴᴇᴅ:</b> {join_date[:16] if join_date else 'ɴ/ᴀ'}

━━━━━━━━━━━━━━━━━━━━━━
📊 <b>sᴛᴀᴛɪsᴛɪᴄs</b>
━━━━━━━━━━━━━━━━━━━━━━

🔄 <b>ʀᴇғᴇʀʀᴀʟs:</b> {referrals}
💰 <b>ᴛᴏᴋᴇɴs:</b> {tokens}
🔴 <b>ᴠᴘs ᴄʀᴇᴀᴛᴇᴅ:</b> {len(vps_list)}

━━━━━━━━━━━━━━━━━━━━━━
"""
    
    await message.answer(text, reply_markup=get_main_keyboard())

# ==================== STORE ====================
@dp.message(F.text == "🛒 STORE")
async def cmd_store(message: types.Message):
    plans = get_all_plans()
    
    text = """
🛒 <b>sᴛᴏʀᴇ</b>
━━━━━━━━━━━━━━━━━━━━━━

🔴 <b>ᴘʀᴇᴍɪᴜᴍ ᴠᴘs ᴘʟᴀɴs</b>

━━━━━━━━━━━━━━━━━━━━━━
"""
    
    for key, plan in plans.items():
        text += f"<b>📦 {plan['storage']}GB</b> | 🧠 {plan['ram']}GB RAM\n"
        text += f"💰 {plan['price']} ᴛᴏᴋᴇɴs | 📅 {plan['days']} ᴅᴀʏs\n"
        text += "━━━━━━━━━━━━━━━━━━━━━━\n"
    
    text += "\n💡 ᴜsᴇ <b>🔴 ᴄʀᴇᴀᴛᴇ ᴠᴘs</b> ᴛᴏ ʙᴜʏ"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 ᴄʀᴇᴀᴛᴇ ᴠᴘs", callback_data="go_create")],
        [InlineKeyboardButton(text="🔙 ʙᴀᴄᴋ", callback_data="back_main")]
    ])
    
    await message.answer(text, reply_markup=keyboard)

@dp.callback_query(F.data == "go_create")
async def go_create(call: types.CallbackQuery, state: FSMContext):
    await call.message.delete()
    await cmd_create_vps(call.message, state)
    await call.answer()

# ==================== SUPPORT ====================
@dp.message(F.text == "🆘 SUPPORT")
async def cmd_support(message: types.Message):
    text = """
🆘 <b>sᴜᴘᴘᴏʀᴛ</b>
━━━━━━━━━━━━━━━━━━━━━━

📞 <b>ᴄᴏɴᴛᴀᴄᴛ sᴜᴘᴘᴏʀᴛ</b>

🐦 <b>ᴛᴇʟᴇɢʀᴀᴍ:</b> <a href="https://t.me/shappno">@shappno</a>

━━━━━━━━━━━━━━━━━━━━━━
📚 <b>ғᴀǫ</b>
━━━━━━━━━━━━━━━━━━━━━━

<b>ǫ:</b> ʜᴏᴡ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴠᴘs?
<b>ᴀ:</b> ᴜsᴇ <b>🔴 ᴄʀᴇᴀᴛᴇ ᴠᴘs</b> ʙᴜᴛᴛᴏɴ

<b>ǫ:</b> ʜᴏᴡ ᴛᴏ ɢᴇᴛ ᴛᴏᴋᴇɴs?
<b>ᴀ:</b> ʀᴇғᴇʀ ғʀɪᴇɴᴅs ᴏʀ ᴜsᴇ ᴄᴏᴜᴘᴏɴs

<b>ǫ:</b> ᴡʜᴀᴛ ɪs ᴍᴀx ᴠᴘs?
<b>ᴀ:</b> ᴅᴇᴘᴇɴᴅs ᴏɴ ʏᴏᴜʀ ᴘʟᴀɴ

━━━━━━━━━━━━━━━━━━━━━━
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐦 ᴄᴏɴᴛᴀᴄᴛ ᴏᴡɴᴇʀ", url="https://t.me/shappno")],
        [InlineKeyboardButton(text="🔙 ʙᴀᴄᴋ", callback_data="back_main")]
    ])
    
    await message.answer(text, reply_markup=keyboard)

# ==================== SYSTEM ====================
@dp.message(F.text == "⚙️ SYSTEM")
async def cmd_system(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ ᴏɴʟʏ ᴀᴅᴍɪɴs ᴄᴀɴ ᴀᴄᴄᴇss!", reply_markup=get_main_keyboard())
        return
    
    users = get_all_users()
    vps_list = get_all_vps()
    plans = get_all_plans()
    backups = get_backup_log()
    
    text = f"""
⚙️ <b>sʏsᴛᴇᴍ</b>
━━━━━━━━━━━━━━━━━━━━━━

👥 <b>ᴛᴏᴛᴀʟ ᴜsᴇʀs:</b> {len(users)}
🔴 <b>ᴛᴏᴛᴀʟ ᴠᴘs:</b> {len(vps_list)}
📦 <b>ᴘʟᴀɴs:</b> {len(plans)}
💾 <b>ʙᴀᴄᴋᴜᴘs:</b> {len(backups)}

━━━━━━━━━━━━━━━━━━━━━━
⚡ <b>ᴠᴇʀsɪᴏɴ:</b> 3.0.0
🤖 <b>ᴘᴏᴡᴇʀᴇᴅ ʙʏ:</b> 𝐒ʜᴀᴘᴘɴᴏ

━━━━━━━━━━━━━━━━━━━━━━
"""
    
    await message.answer(text, reply_markup=get_main_keyboard())

# ==================== LANGUAGE ====================
@dp.message(F.text == "🌐 LANGUAGE")
async def cmd_language(message: types.Message):
    text = """
🌐 <b>ʟᴀɴɢᴜᴀɢᴇ</b>
━━━━━━━━━━━━━━━━━━━━━━

sᴇʟᴇᴄᴛ ʏᴏᴜʀ ᴘʀᴇғᴇʀʀᴇᴅ ʟᴀɴɢᴜᴀɢᴇ:

🇬🇧 <b>ᴇɴɢʟɪsʜ</b> (ᴅᴇғᴀᴜʟᴛ)
🇧🇩 <b>ʙᴀɴɢʟᴀ</b> (ᴄᴏᴍɪɴɢ sᴏᴏɴ)

━━━━━━━━━━━━━━━━━━━━━━
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇬🇧 ᴇɴɢʟɪsʜ", callback_data="lang_en")],
        [InlineKeyboardButton(text="🇧🇩 ʙᴀɴɢʟᴀ", callback_data="lang_bn")],
        [InlineKeyboardButton(text="🔙 ʙᴀᴄᴋ", callback_data="back_main")]
    ])
    
    await message.answer(text, reply_markup=keyboard)

# ==================== ADMIN PANEL ====================
@dp.message(F.text == "🛡️ ADMIN PANEL")
async def cmd_admin_panel(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ ᴏɴʟʏ ᴀᴅᴍɪɴs ᴄᴀɴ ᴀᴄᴄᴇss!", reply_markup=get_main_keyboard())
        return
    
    text = """
🛡️ <b>ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ</b>
━━━━━━━━━━━━━━━━━━━━━━

👑 <b>ᴏᴡɴᴇʀ:</b> <code>OWNER</code>

━━━━━━━━━━━━━━━━━━━━━━
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 ᴍᴀɴᴀɢᴇ ᴘʟᴀɴs", callback_data="admin_plans")],
        [InlineKeyboardButton(text="🎫 ᴄʀᴇᴀᴛᴇ ᴄᴏᴜᴘᴏɴ", callback_data="admin_coupon")],
        [InlineKeyboardButton(text="👥 ʙᴀɴ/ᴜɴʙᴀɴ ᴜsᴇʀ", callback_data="admin_ban")],
        [InlineKeyboardButton(text="🔴 ᴠᴘs ᴍᴀɴᴀɢᴇ", callback_data="admin_vps")],
        [InlineKeyboardButton(text="📊 ᴠɪᴇᴡ ᴀʟʟ ᴜsᴇʀs", callback_data="admin_users")],
        [InlineKeyboardButton(text="📦 ʙᴀᴄᴋᴜᴘ", callback_data="admin_backup"),
         InlineKeyboardButton(text="🔄 ʀᴇsᴛᴏʀᴇ", callback_data="admin_restore")],
        [InlineKeyboardButton(text="📋 ʙᴀᴄᴋᴜᴘ ʟᴏɢ", callback_data="admin_backup_log")],
        [InlineKeyboardButton(text="🔙 ʙᴀᴄᴋ", callback_data="back_main")]
    ])
    
    await message.answer(text, reply_markup=keyboard)

# ==================== ADMIN - BACKUP ====================
@dp.callback_query(F.data == "admin_backup")
async def admin_backup(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ ᴅᴇɴɪᴇᴅ!", show_alert=True)
        return
    
    await call.message.answer("⏳ <b>ᴄʀᴇᴀᴛɪɴɢ ʙᴀᴄᴋᴜᴘ...</b>")
    
    backup_path, filename = create_backup()
    
    if backup_path and backup_path.exists():
        await bot.send_document(
            chat_id=call.from_user.id,
            document=FSInputFile(str(backup_path)),
            caption=f"📦 <b>ʙᴀᴄᴋᴜᴘ ᴄʀᴇᴀᴛᴇᴅ!</b>\n\n"
                    f"📁 <b>ғɪʟᴇ:</b> {filename}\n"
                    f"📅 <b>ᴅᴀᴛᴇ:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"⚡ <b>sɪᴢᴇ:</b> {backup_path.stat().st_size // 1024} KB\n\n"
                    f"<i>KEEP THIS BACKUP SAFE!</i>"
        )
        backup_path.unlink()
        await call.message.answer("✅ <b>ʙᴀᴄᴋᴜᴘ sᴇɴᴛ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>")
    else:
        await call.message.answer("❌ <b>ʙᴀᴄᴋᴜᴘ ғᴀɪʟᴇᴅ!</b>")
    
    await call.answer()

# ==================== ADMIN - RESTORE ====================
@dp.callback_query(F.data == "admin_restore")
async def admin_restore(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌ ᴅᴇɴɪᴇᴅ!", show_alert=True)
        return
    
    await state.set_state(AdminState.waiting_restore_file)
    await call.message.answer(
        "🔄 <b>ʀᴇsᴛᴏʀᴇ sʏsᴛᴇᴍ</b>\n\n"
        "ᴘʟᴇᴀsᴇ sᴇɴᴅ ᴛʜᴇ ʙᴀᴄᴋᴜᴘ `.ᴢɪᴘ` ғɪʟᴇ.\n\n"
        "⚠️ <b>ᴡᴀʀɴɪɴɢ:</b> ᴛʜɪs ᴡɪʟʟ ᴏᴠᴇʀᴡʀɪᴛᴇ ᴀʟʟ ᴄᴜʀʀᴇɴᴛ ᴅᴀᴛᴀ!\n"
        "ᴛʏᴘᴇ <code>/ᴄᴀɴᴄᴇʟ</code> ᴛᴏ ᴄᴀɴᴄᴇʟ."
    )
    await call.answer()

@dp.message(AdminState.waiting_restore_file)
async def process_restore_file(message: types.Message, state: FSMContext):
    if message.text and (message.text == "/cancel" or message.text == "/ᴄᴀɴᴄᴇʟ"):
        await state.clear()
        await message.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ.", reply_markup=get_main_keyboard())
        return
    
    if not message.document:
        await message.answer("❌ ᴘʟᴇᴀsᴇ sᴇɴᴅ ᴀ `.ᴢɪᴘ` ғɪʟᴇ!")
        return
    
    doc = message.document
    if not doc.file_name.endswith('.zip'):
        await message.answer("❌ ᴘʟᴇᴀsᴇ sᴇɴᴅ ᴀ `.ᴢɪᴘ` ғɪʟᴇ!")
        return
    
    status_msg = await message.answer("⏳ <b>ʀᴇsᴛᴏʀɪɴɢ ʙᴀᴄᴋᴜᴘ...</b>")
    
    temp_path = BASE_DIR / f"temp_restore_{int(time.time())}.zip"
    await bot.download(doc, destination=temp_path)
    
    try:
        success, result = restore_backup(temp_path)
        
        if success:
            await status_msg.edit_text(
                f"✅ <b>ʀᴇsᴛᴏʀᴇ ᴄᴏᴍᴘʟᴇᴛᴇ!</b>\n\n"
                f"📦 <b>ғɪʟᴇ:</b> {doc.file_name}\n"
                f"🔄 <b>sʏsᴛᴇᴍ ʀᴇsᴛᴏʀᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ</b>\n\n"
                f"<i>Please restart the bot for changes to take effect.</i>"
            )
        else:
            await status_msg.edit_text(f"❌ <b>ʀᴇsᴛᴏʀᴇ ғᴀɪʟᴇᴅ!</b>\n\n{result}")
    
    except Exception as e:
        await status_msg.edit_text(f"❌ <b>ᴇʀʀᴏʀ:</b> {str(e)}")
    
    finally:
        if temp_path.exists():
            temp_path.unlink()
        await state.clear()

## ==================== ADMIN - BACKUP LOG ====================
@dp.callback_query(F.data == "admin_backup_log")
async def admin_backup_log(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ ᴅᴇɴɪᴇᴅ!", show_alert=True)
        return
    
    logs = get_backup_log()
    
    if not logs:
        await call.message.answer("📋 <b>ɴᴏ ʙᴀᴄᴋᴜᴘ ʟᴏɢ ғᴏᴜɴᴅ.</b>")
        return
    
    text = "📋 <b>ʙᴀᴄᴋᴜᴘ ʟᴏɢ</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for log in logs:
        filename, size, created_at = log
        size_kb = size // 1024
        text += f"📁 <b>{filename}</b>\n"
        text += f"   ⚡ {size_kb} KB\n"
        text += f"   📅 {created_at[:16]}\n\n"
    
    await call.message.edit_text(text)
    await call.answer()

# ==================== ADMIN - PLANS ====================
@dp.callback_query(F.data == "admin_plans")
async def admin_plans(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ ᴅᴇɴɪᴇᴅ!", show_alert=True)
        return
    
    plans = get_all_plans()
    text = "📦 <b>ᴍᴀɴᴀɢᴇ ᴘʟᴀɴs</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    keyboard = []
    for key, plan in plans.items():
        text += f"<b>{key}:</b> {plan['storage']}GB | {plan['ram']}GB RAM | {plan['price']} ᴛᴏᴋᴇɴs | {plan['days']} ᴅᴀʏs\n"
        keyboard.append([InlineKeyboardButton(
            text=f"🔴 {key} - {plan['storage']}GB",
            callback_data=f"admin_edit_plan|{key}"
        )])
    
    keyboard.append([InlineKeyboardButton(text="🔙 ʙᴀᴄᴋ", callback_data="back_admin")])
    
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await call.answer()

@dp.callback_query(F.data.startswith("admin_edit_plan|"))
async def admin_edit_plan(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌ ᴅᴇɴɪᴇᴅ!", show_alert=True)
        return
    
    plan_key = call.data.split('|')[1]
    await state.update_data(plan_key=plan_key)
    await state.set_state(AdminState.waiting_plan_storage)
    
    plan = get_plan(plan_key)
    await call.message.answer(
        f"📦 <b>ᴇᴅɪᴛ ᴘʟᴀɴ: {plan_key}</b>\n\n"
        f"ᴄᴜʀʀᴇɴᴛ: {plan['storage']}GB\n"
        "ᴇɴᴛᴇʀ ɴᴇᴡ sᴛᴏʀᴀɢᴇ (GB):\n"
        "ᴛʏᴘᴇ <code>/ᴄᴀɴᴄᴇʟ</code> ᴛᴏ ᴄᴀɴᴄᴇʟ"
    )
    await call.answer()

@dp.message(AdminState.waiting_plan_storage)
async def process_plan_storage(message: types.Message, state: FSMContext):
    if message.text == "/cancel" or message.text == "/ᴄᴀɴᴄᴇʟ":
        await state.clear()
        await message.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ.", reply_markup=get_main_keyboard())
        return
    
    try:
        storage = int(message.text.strip())
        await state.update_data(storage=storage)
        await state.set_state(AdminState.waiting_plan_ram)
        await message.answer("ᴇɴᴛᴇʀ ɴᴇᴡ RAM (GB):")
    except ValueError:
        await message.answer("❌ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ!")

@dp.message(AdminState.waiting_plan_ram)
async def process_plan_ram(message: types.Message, state: FSMContext):
    try:
        ram = int(message.text.strip())
        await state.update_data(ram=ram)
        await state.set_state(AdminState.waiting_plan_price)
        await message.answer("ᴇɴᴛᴇʀ ɴᴇᴡ ᴘʀɪᴄᴇ (ᴛᴏᴋᴇɴs):")
    except ValueError:
        await message.answer("❌ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ!")

@dp.message(AdminState.waiting_plan_price)
async def process_plan_price(message: types.Message, state: FSMContext):
    try:
        price = int(message.text.strip())
        await state.update_data(price=price)
        await state.set_state(AdminState.waiting_plan_days)
        await message.answer("ᴇɴᴛᴇʀ ɴᴇᴡ ᴅᴀʏs:")
    except ValueError:
        await message.answer("❌ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ!")

@dp.message(AdminState.waiting_plan_days)
async def process_plan_days(message: types.Message, state: FSMContext):
    try:
        days = int(message.text.strip())
        data = await state.get_data()
        plan_key = data.get('plan_key')
        storage = data.get('storage')
        ram = data.get('ram')
        price = data.get('price')
        
        update_plan(plan_key, storage, ram, price, days)
        await state.clear()
        
        await message.answer(
            f"✅ <b>ᴘʟᴀɴ ᴜᴘᴅᴀᴛᴇᴅ!</b>\n\n"
            f"📦 {plan_key}: {storage}GB | {ram}GB RAM | {price} ᴛᴏᴋᴇɴs | {days} ᴅᴀʏs",
            reply_markup=get_main_keyboard()
        )
    except ValueError:
        await message.answer("❌ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ!")

# ==================== ADMIN - COUPON ====================
@dp.callback_query(F.data == "admin_coupon")
async def admin_coupon(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌ ᴅᴇɴɪᴇᴅ!", show_alert=True)
        return
    
    await state.set_state(AdminState.waiting_coupon_tokens)
    await call.message.answer(
        "🎫 <b>ᴄʀᴇᴀᴛᴇ ᴄᴏᴜᴘᴏɴ</b>\n\n"
        "ᴇɴᴛᴇʀ ᴛʜᴇ ɴᴜᴍʙᴇʀ ᴏғ ᴛᴏᴋᴇɴs:\n"
        "ᴛʏᴘᴇ <code>/ᴄᴀɴᴄᴇʟ</code> ᴛᴏ ᴄᴀɴᴄᴇʟ"
    )
    await call.answer()

@dp.message(AdminState.waiting_coupon_tokens)
async def process_coupon_tokens(message: types.Message, state: FSMContext):
    if message.text == "/cancel" or message.text == "/ᴄᴀɴᴄᴇʟ":
        await state.clear()
        await message.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ.", reply_markup=get_main_keyboard())
        return
    
    try:
        tokens = int(message.text.strip())
        if tokens <= 0:
            await message.answer("❌ ᴇɴᴛᴇʀ ᴀ ᴘᴏsɪᴛɪᴠᴇ ɴᴜᴍʙᴇʀ!")
            return
        
        await state.update_data(tokens=tokens)
        await state.set_state(AdminState.waiting_coupon_days)
        await message.answer(
            f"✅ ᴛᴏᴋᴇɴs: {tokens}\n\n"
            "ᴇɴᴛᴇʀ ᴇxᴘɪʀʏ ᴅᴀʏs (ᴅᴇғᴀᴜʟᴛ 30):\n"
            "ᴛʏᴘᴇ <code>/sᴋɪᴘ</code> ғᴏʀ ᴅᴇғᴀᴜʟᴛ"
        )
    except ValueError:
        await message.answer("❌ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ!")

@dp.message(AdminState.waiting_coupon_days)
async def process_coupon_days(message: types.Message, state: FSMContext):
    data = await state.get_data()
    tokens = data.get('tokens')
    
    if message.text.lower() == '/skip':
        days = 30
    else:
        try:
            days = int(message.text.strip())
            if days <= 0:
                await message.answer("❌ ᴇɴᴛᴇʀ ᴀ ᴘᴏsɪᴛɪᴠᴇ ɴᴜᴍʙᴇʀ!")
                return
        except ValueError:
            await message.answer("❌ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ!")
            return
    
    code = create_coupon(tokens, message.from_user.id, days)
    await state.clear()
    
    await message.answer(
        f"🎫 <b>ᴄᴏᴜᴘᴏɴ ᴄʀᴇᴀᴛᴇᴅ!</b>\n\n"
        f"📝 <b>ᴄᴏᴅᴇ:</b> <code>{code}</code>\n"
        f"💰 <b>ᴛᴏᴋᴇɴs:</b> {tokens}\n"
        f"📅 <b>ᴇxᴘɪʀᴇs:</b> {days} ᴅᴀʏs\n\n"
        f"<b>⚠️ sᴀᴠᴇ ᴛʜɪs ᴄᴏᴅᴇ!</b>",
        reply_markup=get_main_keyboard()
    )

# ==================== ADMIN - BAN/UNBAN ====================
@dp.callback_query(F.data == "admin_ban")
async def admin_ban(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("❌ ᴅᴇɴɪᴇᴅ!", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 ʙᴀɴ ᴜsᴇʀ", callback_data="admin_ban_user")],
        [InlineKeyboardButton(text="🟢 ᴜɴʙᴀɴ ᴜsᴇʀ", callback_data="admin_unban_user")],
        [InlineKeyboardButton(text="🔙 ʙᴀᴄᴋ", callback_data="back_admin")]
    ])
    
    await call.message.edit_text("👥 <b>ʙᴀɴ/ᴜɴʙᴀɴ ᴜsᴇʀ</b>", reply_markup=keyboard)
    await call.answer()

@dp.callback_query(F.data == "admin_ban_user")
async def admin_ban_user(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminState.waiting_ban_user)
    await call.message.answer(
        "🔴 <b>ʙᴀɴ ᴜsᴇʀ</b>\n\n"
        "sᴇɴᴅ ᴛʜᴇ ᴜsᴇʀɴᴀᴍᴇ ᴛᴏ ʙᴀɴ:\n"
        "ᴛʏᴘᴇ <code>/ᴄᴀɴᴄᴇʟ</code> ᴛᴏ ᴄᴀɴᴄᴇʟ"
    )
    await call.answer()

@dp.message(AdminState.waiting_ban_user)
async def process_ban_user(message: types.Message, state: FSMContext):
    if message.text == "/cancel" or message.text == "/ᴄᴀɴᴄᴇʟ":
        await state.clear()
        await message.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ.", reply_markup=get_main_keyboard())
        return
    
    username = message.text.strip()
    user = get_user_by_username(username)
    if not user:
        await message.answer(f"❌ ᴜsᴇʀ '{username}' ɴᴏᴛ ғᴏᴜɴᴅ!")
        return
    
    ban_user(username)
    await state.clear()
    await message.answer(f"✅ <b>{username}</b> ʜᴀs ʙᴇᴇɴ ʙᴀɴɴᴇᴅ!", reply_markup=get_main_keyboard())

@dp.callback_query(F.data == "admin_unban_user")
async def admin_unban_user(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminState.waiting_unban_user)
    await call.message.answer(
        "🟢 <b>ᴜɴʙᴀɴ ᴜsᴇʀ</b>\n\n"
        "sᴇɴᴅ ᴛʜᴇ ᴜsᴇʀɴᴀᴍᴇ ᴛᴏ ᴜɴʙᴀɴ:\n"
        "ᴛʏᴘᴇ <code>/ᴄᴀɴᴄᴇʟ</code> ᴛᴏ ᴄᴀɴᴄᴇʟ"
    )
    await call.answer()

@dp.message(AdminState.waiting_unban_user)
async def process_unban_user(message: types.Message, state: FSMContext):
    if message.text == "/cancel" or message.text == "/ᴄᴀɴᴄᴇʟ":
        await state.clear()
        await message.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ.", reply_markup=get_main_keyboard())
        return
    
    username = message.text.strip()
    user = get_user_by_username(username)
    if not user:
        await message.answer(f"❌ ᴜsᴇʀ '{username}' ɴᴏᴛ ғᴏᴜɴᴅ!")
        return
    
    unban_user(username)
    await state.clear()
    await message.answer(f"✅ <b>{username}</b> ʜᴀs ʙᴇᴇɴ ᴜɴʙᴀɴɴᴇᴅ!", reply_markup=get_main_keyboard())

# ==================== ADMIN - VPS MANAGE ====================
@dp.callback_query(F.data == "admin_vps")
async def admin_vps(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ ᴅᴇɴɪᴇᴅ!", show_alert=True)
        return
    
    vps_list = get_all_vps()
    if not vps_list:
        await call.message.edit_text("📁 ɴᴏ ᴠᴘs ғᴏᴜɴᴅ.")
        return
    
    text = "🔴 <b>ᴀʟʟ ᴠᴘs</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    keyboard = []
    
    for vps in vps_list:
        vps_id, user_id, username, name, password, image_url, storage, ram, created, expires, status, url, used = vps
        status_icon = "🟢" if status == "active" else "🔴"
        text += f"{status_icon} <b>{name}</b> (@{username or user_id})\n"
        text += f"   💾 {storage}GB | 🧠 {ram}GB\n"
        text += f"   🔑 <code>{password}</code>\n"
        text += f"   🌐 <a href='{url}'>{url[:30]}...</a>\n\n"
        keyboard.append([InlineKeyboardButton(
            text=f"{'🟢' if status == 'active' else '🔴'} {name}",
            callback_data=f"admin_vps_action|{vps_id}"
        )])
    
    keyboard.append([InlineKeyboardButton(text="🔙 ʙᴀᴄᴋ", callback_data="back_admin")])
    
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("admin_vps_action|"))
async def admin_vps_action(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ ᴅᴇɴɪᴇᴅ!", show_alert=True)
        return
    
    vps_id = int(call.data.split('|')[1])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 ᴀᴄᴛɪᴠᴀᴛᴇ", callback_data=f"admin_vps_on|{vps_id}"),
         InlineKeyboardButton(text="🔴 ᴅᴇᴀᴄᴛɪᴠᴀᴛᴇ", callback_data=f"admin_vps_off|{vps_id}")],
        [InlineKeyboardButton(text="🗑️ ᴅᴇʟᴇᴛᴇ", callback_data=f"admin_vps_delete|{vps_id}")],
        [InlineKeyboardButton(text="🔙 ʙᴀᴄᴋ", callback_data="admin_vps")]
    ])
    
    await call.message.edit_text(f"🔴 <b>ᴠᴘs #{vps_id}</b>\nsᴇʟᴇᴄᴛ ᴀᴄᴛɪᴏɴ:", reply_markup=keyboard)
    await call.answer()

@dp.callback_query(F.data.startswith("admin_vps_on|"))
async def admin_vps_on(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ ᴅᴇɴɪᴇᴅ!", show_alert=True)
        return
    
    vps_id = int(call.data.split('|')[1])
    toggle_vps_status(vps_id, "active")
    await call.answer("✅ ᴠᴘs ᴀᴄᴛɪᴠᴀᴛᴇᴅ!", show_alert=True)
    await admin_vps(call)

@dp.callback_query(F.data.startswith("admin_vps_off|"))
async def admin_vps_off(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ ᴅᴇɴɪᴇᴅ!", show_alert=True)
        return
    
    vps_id = int(call.data.split('|')[1])
    toggle_vps_status(vps_id, "inactive")
    await call.answer("🔴 ᴠᴘs ᴅᴇᴀᴄᴛɪᴠᴀᴛᴇᴅ!", show_alert=True)
    await admin_vps(call)

@dp.callback_query(F.data.startswith("admin_vps_delete|"))
async def admin_vps_delete(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ ᴅᴇɴɪᴇᴅ!", show_alert=True)
        return
    
    vps_id = int(call.data.split('|')[1])
    delete_vps(vps_id)
    await call.answer("🗑️ ᴠᴘs ᴅᴇʟᴇᴛᴇᴅ!", show_alert=True)
    await admin_vps(call)

# ==================== ADMIN - VIEW ALL USERS ====================
@dp.callback_query(F.data == "admin_users")
async def admin_users(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("❌ ᴅᴇɴɪᴇᴅ!", show_alert=True)
        return
    
    users = get_all_users()
    if not users:
        await call.message.edit_text("📊 ɴᴏ ᴜsᴇʀs ғᴏᴜɴᴅ.")
        return
    
    text = "📊 <b>ᴀʟʟ ᴜsᴇʀs</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for user in users:
        user_id, username, tokens, referrals, banned = user
        status = "🚫" if banned else "✅"
        text += f"{status} <code>{user_id}</code>"
        if username:
            text += f" (@{username})"
        text += f"\n   💰 {tokens} ᴛᴏᴋᴇɴs | 📊 {referrals} ʀᴇғᴇʀʀᴀʟs\n\n"
    
    text += "━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"ᴛᴏᴛᴀʟ: {len(users)} ᴜsᴇʀs"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 ʙᴀᴄᴋ", callback_data="back_admin")]
    ])
    
    await call.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await call.answer()

# ==================== BACK CALLBACKS ====================
@dp.callback_query(F.data == "back_main")
async def back_main(call: types.CallbackQuery):
    await call.message.delete()
    user = get_user(call.from_user.id)
    if user and user[6] == 1:
        await call.answer("🚫 ʏᴏᴜ ᴀʀᴇ ʙᴀɴɴᴇᴅ!", show_alert=True)
        return
    await cmd_start(call.message)
    await call.answer()

@dp.callback_query(F.data == "back_admin")
async def back_admin(call: types.CallbackQuery):
    await cmd_admin_panel(call.message)
    await call.answer()

@dp.callback_query(F.data == "lang_en")
async def lang_en(call: types.CallbackQuery):
    await call.answer("✅ ᴇɴɢʟɪsʜ sᴇʟᴇᴄᴛᴇᴅ!", show_alert=True)
    await back_main(call)

@dp.callback_query(F.data == "lang_bn")
async def lang_bn(call: types.CallbackQuery):
    await call.answer("✅ ʙᴀɴɢʟᴀ sᴇʟᴇᴄᴛᴇᴅ!", show_alert=True)
    await back_main(call)

# ==================== COUPON REDEEM ====================
@dp.message(F.text == "🎫 COUPON")
async def cmd_coupon(message: types.Message, state: FSMContext):
    await state.set_state(CouponState.waiting_code)
    await message.answer(
        "🎫 <b>ʀᴇᴅᴇᴇᴍ ᴄᴏᴜᴘᴏɴ</b>\n\n"
        "ᴇɴᴛᴇʀ ʏᴏᴜʀ ᴄᴏᴜᴘᴏɴ ᴄᴏᴅᴇ:\n"
        "ᴛʏᴘᴇ <code>/ᴄᴀɴᴄᴇʟ</code> ᴛᴏ ᴄᴀɴᴄᴇʟ"
    )

@dp.message(CouponState.waiting_code)
async def process_coupon(message: types.Message, state: FSMContext):
    if message.text == "/cancel" or message.text == "/ᴄᴀɴᴄᴇʟ":
        await state.clear()
        await message.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ.", reply_markup=get_main_keyboard())
        return
    
    code = message.text.strip().upper()
    success, result = use_coupon(code, message.from_user.id)
    
    if success:
        await message.answer(f"✅ <b>ᴄᴏᴜᴘᴏɴ ʀᴇᴅᴇᴇᴍᴇᴅ!</b>\n\n🎉 ʏᴏᴜ ɢᴏᴛ {result} ᴛᴏᴋᴇɴs!", reply_markup=get_main_keyboard())
    else:
        await message.answer(f"❌ {result}", reply_markup=get_main_keyboard())
    
    await state.clear()

# ==================== TRANSFER ====================
@dp.message(F.text == "🔄 TRANSFER")
async def cmd_transfer(message: types.Message, state: FSMContext):
    await state.set_state(TransferState.waiting_target)
    await message.answer(
        "🔄 <b>ᴛʀᴀɴsғᴇʀ ᴛᴏᴋᴇɴs</b>\n\n"
        "ᴇɴᴛᴇʀ ᴛʜᴇ ᴜsᴇʀɴᴀᴍᴇ ᴏғ ᴛʜᴇ ᴘᴇʀsᴏɴ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴛʀᴀɴsғᴇʀ ᴛᴏ:\n"
        "ᴛʏᴘᴇ <code>/ᴄᴀɴᴄᴇʟ</code> ᴛᴏ ᴄᴀɴᴄᴇʟ"
    )

@dp.message(TransferState.waiting_target)
async def process_transfer_target(message: types.Message, state: FSMContext):
    if message.text == "/cancel" or message.text == "/ᴄᴀɴᴄᴇʟ":
        await state.clear()
        await message.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ.", reply_markup=get_main_keyboard())
        return
    
    username = message.text.strip()
    target = get_user_by_username(username)
    if not target:
        await message.answer(f"❌ ᴜsᴇʀ '{username}' ɴᴏᴛ ғᴏᴜɴᴅ!")
        return
    
    await state.update_data(target_id=target[0])
    await state.set_state(TransferState.waiting_amount)
    await message.answer(
        f"👤 <b>ᴛᴀʀɢᴇᴛ:</b> @{username}\n\n"
        "ᴇɴᴛᴇʀ ᴛʜᴇ ᴀᴍᴏᴜɴᴛ ᴏғ ᴛᴏᴋᴇɴs ᴛᴏ ᴛʀᴀɴsғᴇʀ:"
    )

@dp.message(TransferState.waiting_amount)
async def process_transfer_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            await message.answer("❌ ᴀᴍᴏᴜɴᴛ ᴍᴜsᴛ ʙᴇ ᴘᴏsɪᴛɪᴠᴇ!")
            return
        
        user = get_user(message.from_user.id)
        if user[3] < amount:
            await message.answer(f"❌ ʏᴏᴜ ᴏɴʟʏ ʜᴀᴠᴇ {user[3]} ᴛᴏᴋᴇɴs!")
            return
        
        data = await state.get_data()
        target_id = data.get('target_id')
        
        update_user(message.from_user.id, tokens=-amount)
        update_user(target_id, tokens=amount)
        
        await state.clear()
        await message.answer(
            f"✅ <b>ᴛʀᴀɴsғᴇʀ sᴜᴄᴄᴇssғᴜʟ!</b>\n\n"
            f"💰 {amount} ᴛᴏᴋᴇɴs sᴇɴᴛ!",
            reply_markup=get_main_keyboard()
        )
        
        await bot.send_message(
            target_id,
            f"📥 <b>ʏᴏᴜ ʀᴇᴄᴇɪᴠᴇᴅ ᴛᴏᴋᴇɴs!</b>\n\n"
            f"💰 +{amount} ᴛᴏᴋᴇɴs ғʀᴏᴍ @{message.from_user.username or 'Unknown'}"
        )
    except ValueError:
        await message.answer("❌ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ!")

# ==================== MAIN ====================
async def main():
    logger.info("SHAPPNO VPS BOT STARTED!")
    
    # Start auto backup worker
    asyncio.create_task(auto_backup_worker())
    logger.info("Auto backup worker started (every 4 hours)")
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())