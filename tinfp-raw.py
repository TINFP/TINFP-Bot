#!/usr/bin/env python3
# main.py - TheIranianNetFreedomBot Source v15
#
# v15 CHANGES:
# - Remove session expiration (sessions persist until bot restart)
# - Add weekly subscription via Bale Wallet (WALLET-TEST-1111111111111111)
# - Sub benefits: videos >35min, TikTok link download, LibGen search+PDF, unlimited GitHub uploads
# - Price: 2500,000 IRR/week
# - Add donate button (1,000 - 1,000,000 Tomans)
# - Payment/donation logged to admin group
# - Connection error handling with auto-reconnect
# - /status command for admin (host info, folder sizes)
# - Admin has subscription by default
# - Admin can add/remove subscription from users via inline panel
# - GitHub upload rate limit: 2/day free, unlimited for subscribers
# - Free users blocked from videos > 35 minutes
# - TikTok download (link only, requires sub)
# - LibGen book search with PDF conversion (requires sub)

import os
import re
import asyncio
import json
import logging
import math
import shlex
import threading
import time
import random
import platform
import subprocess
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import quote

import aiohttp
import yt_dlp
from pyrobale.client import Client
from pyrobale.objects import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery,
)

BOT_TOKEN = "BOT_TOKEN"
BOT_USERNAME = "YOUR_BOT_USERNAME-WITHOUT_@"
ADMIN_ID = 1234567890
ADMIN_GROUP_ID = 1234567890
DOWNLOAD_DIR = "downloads"
CONTAINER_DIR = "/home/container/downloads"
MAX_FILE_SIZE_BYTES = int(19 * 1024 * 1024)
MAX_DISK_SIZE = 650 * 1024 * 1024
BALE_API_BASE = f"https://tapi.bale.ai/bot{BOT_TOKEN}"
DB_FILE = "bot_database.json"
MAX_CONCURRENT_DOWNLOADS = 1
SEARCH_PER_PAGE = 6
SEARCH_TOTAL = 30
CAPTION_MAX = 500
FILENAME_MAX = 500
CHANNEL_PATTERN = re.compile(
    r"(youtube\.com/(channel|c|user)/|youtube\.com/@)", re.IGNORECASE
)
TIKTOK_PATTERN = re.compile(r"(tiktok\.com|vm\.tiktok\.com)", re.IGNORECASE)
MAX_FREE_DURATION = 35 * 60  # 35 minutes in seconds
FREE_GH_DAILY_LIMIT = 2

# ============ Payment / Subscription ============
WALLET_TOKEN = "BALE_WALLET_TOKEN"
SUBSCRIPTION_PRICE_IRR = 250000  # 600,000 IRR = 60,000 Tomans
SUBSCRIPTION_DAYS = 7
DONATE_MIN_TOMANS = 1000
DONATE_MAX_TOMANS = 1000000

GITHUB_TOKEN = "GITHUB_TOKEN"
GITHUB_API = "https://api.github.com"
GITHUB_MAX_FILE_SIZE = 100 * 1024 * 1024
GITHUB_HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}
_github_owner: Optional[str] = None
_github_session: Optional[aiohttp.ClientSession] = None

# ============ NSFW / Pornographic URL blocking (keyword-based) ============
NSFW_URL_PATTERNS: List[re.Pattern] = [
    re.compile(
        r"(porn|sex|xxx|xvideos|xnxx|xhamster|youporn|redtube|"
        r"brazzers|onlyfans|hentai|rule34|nsfw|adult|camgirl|"
        r"cams|webcamsex|erotic|milf|blowjob|hardcore|lesbian|"
        r"anal|cumshot|deepthroat|fap|fetish|bdsm|incest|"
        r"jav|ecchi|doujin|pornhub|stripchat|livejasmin|"
        r"chaturbate|spankbang|tube8|beeg|tnaflix|nudity|"
        r"nude|escort|fuck|dick|pussy|boobs|tits|slut|whore|"
        r"xhaccess|xhamsterlive|camsoda|cam4|myfreecams|faphouse|"
        r"pornzog|porndoe|hellporno|eporner|txxx|watchmygf|"
        r"adulttime|realitykings|bangbros|naughtyamerica|"
        r"deviantclip|xtube|sexvid|sexlikereal)",
        re.IGNORECASE
    ),
]

# ============ Blocked Iranian political/news channels ============
BLOCKED_POLITICAL_CHANNELS = [
    "iraninternational", "iranintl", "bbcpersian", "bbc persian",
    "voapersian", "voa persian", "radiofarda", "radio farda",
    "manototv", "manoto", "iranwire", "mihantv", "mihan tv",
    "presstv", "press tv", "alalam", "al alam", "hispantv",
    "ifilm", "sahartv", "sahar tv", "irib", "tasnimnews", "tasnim",
    "isna", "mehrnews", "kayhan", "shargh", "etemad",
    "hamshahri", "jamaran", "entekhab", "khabaronline", "fararu",
    "asriran", "yjc", "tabnak", "alef", "khabar", "irna",
    "farsnews", "fars news", "pbc persian", "pbcpersian",
    "sedayeamerica", "seda ye america", "azadi tv", "azaditv",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(CONTAINER_DIR, exist_ok=True)

BOT_START_TIME = time.time()


def check_tool(cmd: str) -> bool:
    try:
        subprocess.run([cmd, "--version"], capture_output=True, check=False, timeout=5)
        return True
    except Exception:
        return False


FFMPEG_AVAILABLE = check_tool("ffmpeg")
EBOOK_CONVERT_AVAILABLE = check_tool("ebook-convert")
VIDEO_PRESETS = ["720p", "480p", "360p", "240p", "128p"]
AUDIO_PRESETS = ["mp3", "ogg"]


def is_political_channel(channel_name: str) -> bool:
    if not channel_name:
        return False
    name_lower = channel_name.lower().replace(" ", "").replace("_", "").replace("-", "")
    for blocked in BLOCKED_POLITICAL_CHANNELS:
        b = blocked.replace(" ", "").replace("_", "").replace("-", "").lower()
        if b and (b in name_lower or name_lower in b):
            return True
    return False


def is_nsfw_url(url: str) -> bool:
    if not NSFW_URL_PATTERNS:
        return False
    for pat in NSFW_URL_PATTERNS:
        if pat.search(url):
            return True
    return False


def is_tiktok_url(url: str) -> bool:
    return bool(TIKTOK_PATTERN.search(url))


# ========================= Shared aiohttp session =========================

async def _get_github_session() -> aiohttp.ClientSession:
    global _github_session
    if _github_session is None or _github_session.closed:
        _github_session = aiohttp.ClientSession(
            headers=GITHUB_HEADERS,
            timeout=aiohttp.ClientTimeout(total=120, connect=30, sock_read=120),
        )
    return _github_session


# ========================= Robust helpers =========================

def get_msg_id(msg) -> int:
    if msg is None:
        return 0
    if isinstance(msg, int):
        return msg
    if isinstance(msg, dict):
        return int(msg.get("message_id", msg.get("id", 0)))
    for attr in ("message_id", "id"):
        val = getattr(msg, attr, None)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
    return 0


def extract_user_info(message) -> Tuple[str, str]:
    username, first_name = "", ""
    sender = None
    for attr in ("from_user", "author", "from", "user", "sender"):
        sender = getattr(message, attr, None)
        if sender is not None:
            break
    if sender is not None:
        for uattr in ("username", "user_name", "userName", "screen_name"):
            val = getattr(sender, uattr, None)
            if val:
                username = str(val).lstrip("@")
                break
        if not username and hasattr(sender, "__dict__"):
            d = sender.__dict__
            if isinstance(d, dict):
                for key in ("username", "user_name", "userName", "screen_name"):
                    val = d.get(key)
                    if val:
                        username = str(val).lstrip("@")
                        break
        if not username and hasattr(sender, "to_dict"):
            try:
                d = sender.to_dict()
                if isinstance(d, dict):
                    for key in ("username", "user_name", "userName", "screen_name"):
                        val = d.get(key)
                        if val:
                            username = str(val).lstrip("@")
                            break
            except Exception:
                pass
        for fattr in ("first_name", "firstName", "name", "title"):
            val = getattr(sender, fattr, None)
            if val:
                first_name = str(val)
                break
        if not first_name and hasattr(sender, "__dict__"):
            d = sender.__dict__
            if isinstance(d, dict):
                for key in ("first_name", "firstName", "name"):
                    val = d.get(key)
                    if val:
                        first_name = str(val)
                        break
    chat = getattr(message, "chat", None)
    if chat is not None:
        if not first_name:
            for fattr in ("first_name", "firstName", "title", "name"):
                val = getattr(chat, fattr, None)
                if val:
                    first_name = str(val)
                    break
        if not username:
            for uattr in ("username", "user_name", "userName"):
                val = getattr(chat, uattr, None)
                if val:
                    username = str(val).lstrip("@")
                    break
    return username, first_name


# ========================= JSON Database =========================

class Database:
    def __init__(self, path: str):
        self.path = path
        self._lock = asyncio.Lock()
        self.data = self._load()

    def _load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {
                "users": {},
                "blocked_channels": [],
                "blocked_videos": [],
                "langs": {},
                "settings": {},
            }

    async def save(self):
        async with self._lock:
            try:
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error("DB save error: %s", e)

    def get_user(self, uid: int) -> Optional[dict]:
        return self.data["users"].get(str(uid))

    async def add_user(self, uid: int, username: str = "", first_name: str = "") -> bool:
        k = str(uid)
        if k not in self.data["users"]:
            self.data["users"][k] = {
                "username": username,
                "first_name": first_name,
                "joined_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "blocked": False,
                "subscription_expiry": 0,
                "gh_uploads_today": 0,
                "gh_upload_reset_date": "",
            }
            await self.save()
            return True
        else:
            changed = False
            u = self.data["users"][k]
            if username and u.get("username", "") != username:
                u["username"] = username
                changed = True
            if first_name and u.get("first_name", "") != first_name:
                u["first_name"] = first_name
                changed = True
            for field, default in [("subscription_expiry", 0), ("gh_uploads_today", 0), ("gh_upload_reset_date", "")]:
                if field not in u:
                    u[field] = default
                    changed = True
            if changed:
                await self.save()
        return False

    async def block_user(self, uid: int, username: str = "", first_name: str = ""):
        k = str(uid)
        if k not in self.data["users"]:
            self.data["users"][k] = {
                "username": username, "first_name": first_name,
                "joined_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "blocked": True, "subscription_expiry": 0,
                "gh_uploads_today": 0, "gh_upload_reset_date": "",
            }
        else:
            self.data["users"][k]["blocked"] = True
        await self.save()

    async def unblock_user(self, uid: int):
        k = str(uid)
        if k not in self.data["users"]:
            self.data["users"][k] = {
                "username": "", "first_name": "",
                "joined_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "blocked": False, "subscription_expiry": 0,
                "gh_uploads_today": 0, "gh_upload_reset_date": "",
            }
        else:
            self.data["users"][k]["blocked"] = False
        await self.save()

    def is_user_blocked(self, uid: int) -> bool:
        u = self.get_user(uid)
        return bool(u and u.get("blocked"))

    def is_user_allowed(self, uid: int) -> bool:
        if uid == ADMIN_ID:
            return True
        return not self.is_user_blocked(uid)

    def all_users(self) -> dict:
        return self.data.get("users", {})

    def blocked_users(self) -> dict:
        return {k: v for k, v in self.data.get("users", {}).items() if v.get("blocked")}

    async def block_channel(self, ch: str):
        if ch not in self.data["blocked_channels"]:
            self.data["blocked_channels"].append(ch)
            await self.save()

    async def unblock_channel(self, ch: str):
        if ch in self.data["blocked_channels"]:
            self.data["blocked_channels"].remove(ch)
            await self.save()

    def is_channel_blocked(self, ch: str) -> bool:
        return ch in self.data.get("blocked_channels", [])

    async def block_video(self, url: str):
        if url not in self.data["blocked_videos"]:
            self.data["blocked_videos"].append(url)
            await self.save()

    async def unblock_video(self, url: str):
        if url in self.data["blocked_videos"]:
            self.data["blocked_videos"].remove(url)
            await self.save()

    def is_video_blocked(self, url: str) -> bool:
        return url in self.data.get("blocked_videos", [])

    def get_lang(self, uid: int) -> str:
        return self.data.get("langs", {}).get(str(uid), "fa")

    async def set_lang(self, uid: int, lang: str):
        if "langs" not in self.data:
            self.data["langs"] = {}
        self.data["langs"][str(uid)] = lang
        await self.save()

    # ---- Subscription helpers ----
    def has_subscription(self, uid: int) -> bool:
        if uid == ADMIN_ID:
            return True
        u = self.get_user(uid)
        if not u:
            return False
        return u.get("subscription_expiry", 0) > time.time()

    async def set_subscription(self, uid: int, expiry_timestamp: float):
        u = self.get_user(uid)
        if u:
            u["subscription_expiry"] = expiry_timestamp
            await self.save()

    async def remove_subscription(self, uid: int):
        u = self.get_user(uid)
        if u:
            u["subscription_expiry"] = 0
            await self.save()

    def get_subscription_expiry(self, uid: int) -> float:
        u = self.get_user(uid)
        return u.get("subscription_expiry", 0) if u else 0

    # ---- GitHub upload rate limit ----
    def can_github_upload(self, uid: int) -> bool:
        if self.has_subscription(uid):
            return True
        u = self.get_user(uid)
        if not u:
            return True
        today = time.strftime("%Y-%m-%d")
        if u.get("gh_upload_reset_date", "") != today:
            return True
        return u.get("gh_uploads_today", 0) < FREE_GH_DAILY_LIMIT

    def get_github_uploads_today(self, uid: int) -> int:
        u = self.get_user(uid)
        if not u:
            return 0
        today = time.strftime("%Y-%m-%d")
        if u.get("gh_upload_reset_date", "") != today:
            return 0
        return u.get("gh_uploads_today", 0)

    async def increment_github_upload(self, uid: int):
        u = self.get_user(uid)
        if not u:
            return
        today = time.strftime("%Y-%m-%d")
        if u.get("gh_upload_reset_date", "") != today:
            u["gh_uploads_today"] = 1
            u["gh_upload_reset_date"] = today
        else:
            u["gh_uploads_today"] = u.get("gh_uploads_today", 0) + 1
        await self.save()

    def count_subscribers(self) -> int:
        count = 0
        now = time.time()
        for uid_str, u in self.data.get("users", {}).items():
            if u.get("subscription_expiry", 0) > now:
                count += 1
        return count


db = Database(DB_FILE)

_admin_blocks: Dict[str, dict] = {}
_admin_block_seq = 0


def _store_admin_block(url: str, channel: str, title: str) -> str:
    global _admin_block_seq
    _admin_block_seq += 1
    k = str(_admin_block_seq)
    _admin_blocks[k] = {"url": url, "channel": channel, "title": title}
    if len(_admin_blocks) > 500:
        oldest = list(_admin_blocks.keys())[:200]
        for ok in oldest:
            del _admin_blocks[ok]
    return k


# ========================= GitHub Helpers — Releases API =========================

def _fmt_len(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _read_file_sync(filepath: str) -> bytes:
    with open(filepath, "rb") as f:
        return f.read()


async def get_github_owner() -> Optional[str]:
    global _github_owner
    if _github_owner:
        return _github_owner
    logger.info("[GH-AUTH] Fetching GitHub owner...")
    try:
        session = await _get_github_session()
        async with session.get(f"{GITHUB_API}/user") as resp:
            if resp.status == 200:
                data = await resp.json()
                _github_owner = data.get("login", "")
                logger.info("[GH-AUTH] Owner: %s", _github_owner)
                return _github_owner
            else:
                data = await resp.json()
                logger.error("[GH-AUTH] Failed: HTTP %s - %s", resp.status, data.get("message", ""))
                return None
    except Exception as e:
        logger.error("[GH-AUTH] Error: %s", e)
        return None


async def github_ensure_repo(repo_name: str) -> bool:
    owner = await get_github_owner()
    if not owner:
        logger.error("[GH-REPO] No owner, cannot ensure repo")
        return False
    logger.info("[GH-REPO] Checking repo %s/%s ...", owner, repo_name)
    try:
        session = await _get_github_session()
        async with session.get(f"{GITHUB_API}/repos/{owner}/{repo_name}") as resp:
            if resp.status == 200:
                logger.info("[GH-REPO] Repo exists: %s/%s", owner, repo_name)
                return True
    except Exception as e:
        logger.warning("[GH-REPO] Check error: %s", e)
    logger.info("[GH-REPO] Creating repo %s/%s ...", owner, repo_name)
    try:
        session = await _get_github_session()
        async with session.post(
            f"{GITHUB_API}/user/repos",
            json={
                "name": repo_name,
                "public": True,
                "auto_init": True,
                "description": f"File uploads from {BOT_USERNAME}",
            },
        ) as resp:
            if resp.status == 201:
                logger.info("[GH-REPO] Created repo: %s/%s", owner, repo_name)
                await asyncio.sleep(3)
                return True
            elif resp.status == 422:
                logger.info("[GH-REPO] Repo already exists (422): %s/%s", owner, repo_name)
                await asyncio.sleep(1)
                return True
            else:
                data = await resp.json()
                logger.error("[GH-REPO] Create failed: HTTP %s - %s", resp.status, data.get("message", ""))
                return False
    except Exception as e:
        logger.error("[GH-REPO] Create error: %s", e)
        return False


async def github_create_release(owner: str, repo_name: str, tag: str, filename: str) -> Optional[dict]:
    url = f"{GITHUB_API}/repos/{owner}/{repo_name}/releases"
    payload = {
        "tag_name": tag,
        "name": filename[:80],
        "body": f"Uploaded by {BOT_USERNAME}",
        "draft": False,
        "prerelease": False,
    }
    logger.info("[GH-RELEASE] Creating release tag=%s for %s/%s", tag, owner, repo_name)
    try:
        session = await _get_github_session()
        async with session.post(url, json=payload) as resp:
            if resp.status == 201:
                data = await resp.json()
                logger.info("[GH-RELEASE] Created release id=%s", data.get("id"))
                return data
            else:
                text = await resp.text()
                logger.error("[GH-RELEASE] Create failed: HTTP %s - %s", resp.status, text[:300])
                return None
    except Exception as e:
        logger.error("[GH-RELEASE] Create error: %s", e)
        return None


async def github_upload_asset(upload_url: str, local_filepath: str, filename: str) -> Optional[str]:
    loop = asyncio.get_running_loop()
    file_size = os.path.getsize(local_filepath)
    logger.info("[GH-ASSET] START upload '%s' (%s) as raw binary", filename, _fmt_len(file_size))
    t0 = time.time()
    try:
        file_data = await loop.run_in_executor(None, _read_file_sync, local_filepath)
    except Exception as e:
        logger.error("[GH-ASSET] File read error: %s", e)
        return None
    logger.info("[GH-ASSET] File read: %s in %.2fs", _fmt_len(len(file_data)), time.time() - t0)
    headers = {"Content-Type": "application/octet-stream"}
    try:
        session = await _get_github_session()
        upload_timeout = aiohttp.ClientTimeout(total=600, connect=30, sock_read=300)
        t1 = time.time()
        async with session.post(upload_url, data=file_data, headers=headers, timeout=upload_timeout) as resp:
            elapsed = time.time() - t1
            logger.info("[GH-ASSET] Response status: %s after %.2fs", resp.status, elapsed)
            if resp.status == 201:
                data = await resp.json()
                dl_url = data.get("browser_download_url", "")
                logger.info("[GH-ASSET] SUCCESS in %.2fs: %s", elapsed, dl_url)
                return dl_url
            else:
                text = await resp.text()
                logger.error("[GH-ASSET] FAILED HTTP %s: %s", resp.status, text[:300])
                return None
    except asyncio.TimeoutError:
        logger.error("[GH-ASSET] TIMEOUT after %.2fs", time.time() - t1)
        return None
    except Exception as e:
        logger.error("[GH-ASSET] Error: %s", e)
        return None
    finally:
        del file_data


async def github_upload_file(repo_name: str, local_filepath: str, progress_callback=None) -> Optional[str]:
    owner = await get_github_owner()
    if not owner:
        logger.error("[GH-UPLOAD] No owner")
        return None
    file_size = os.path.getsize(local_filepath)
    filename = safe_filename(os.path.basename(local_filepath))
    logger.info("[GH-UPLOAD] START upload '%s' (%s) to %s/%s via Releases API",
                filename, _fmt_len(file_size), owner, repo_name)
    if progress_callback:
        await progress_callback("checking")
    repo_ok = await github_ensure_repo(repo_name)
    if not repo_ok:
        logger.error("[GH-UPLOAD] Repo ensure FAILED")
        return None
    if progress_callback:
        await progress_callback("encoding")
    tag = f"u{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
    release = await github_create_release(owner, repo_name, tag, filename)
    if not release:
        logger.error("[GH-UPLOAD] Release creation FAILED")
        return None
    upload_url_template = release.get("upload_url", "")
    if not upload_url_template:
        logger.error("[GH-UPLOAD] No upload_url in release response")
        return None
    upload_url = upload_url_template.replace("{?name,label}", f"?name={quote(filename)}")
    if progress_callback:
        await progress_callback("uploading")
    download_url = await github_upload_asset(upload_url, local_filepath, filename)
    if download_url:
        logger.info("[GH-UPLOAD] SUCCESS: %s", download_url)
    else:
        logger.error("[GH-UPLOAD] FAILED")
    return download_url


# ========================= GitHub progress updater =========================

async def _github_progress_updater(chat_id, msg_id, msg_type, stop_event, phase_info):
    start_time = time.time()
    while not stop_event.is_set():
        await asyncio.sleep(5)
        if stop_event.is_set():
            break
        elapsed = int(time.time() - start_time)
        phase = phase_info.get("phase", "uploading")
        logger.info("[GH-PROGRESS] chat_id=%s phase=%s elapsed=%ds", chat_id, phase, elapsed)
        if phase == "encoding":
            text = t(chat_id, "github_encoding", elapsed=elapsed)
        elif phase == "serializing":
            text = t(chat_id, "github_serializing", elapsed=elapsed)
        else:
            text = t(chat_id, "github_uploading_progress", elapsed=elapsed)
        await _edit_info_msg(chat_id, msg_id, msg_type, text)


# ========================= Language System =========================

MESSAGES: Dict[str, Dict[str, str]] = {
    "en": {
        "welcome": "👋 Welcome to {bot}!\n\n📥 Download videos/audio from YouTube, Instagram & more.\n🔍 Search YouTube by name.\n📺 Browse channel videos.\n📚 LibGen book search (⭐).\n\n🔧 Optimised for weak hosts & Iranian networks.",
        "help": "🔍 How to Use:\n1️⃣ Send a link or search YouTube\n2️⃣ Tap Download → choose quality\n3️⃣ Choose upload method (Bale or GitHub)\n4️⃣ Large files on Bale split automatically (<19MB/part).\n\n⭐ Free: Videos ≤35 min, 2 GitHub uploads/day\n⭐ Premium: Unlimited length, TikTok, LibGen, unlimited GitHub\n\n💵 /subscribe | 💰 /donate",
        "analyzing": "🔍 Analyzing…",
        "extract_failed": "❌ Could not extract info.",
        "no_links": "ℹ️ No downloadable links found.",
        "found_links": "🌐 Found {count} links:\n{links}",
        "choose_quality": "🎬 Choose quality:",
        "downloading": "⏳ Downloading…",
        "queue_wait": "⏳ Queue full — waiting…",
        "download_starting": "🔄 Starting download…",
        "download_failed": "❌ Download failed — file not found.",
        "file_too_large": "⏳ File too large — splitting into parts…",
        "split_failed": "❌ Splitting failed.",
        "sent_parts": "✅ Sent in {count} parts.",
        "file_not_found": "❌ File not found on disk.",
        "send_link": "🤖 Send me a link or video name!\n/help for guide.",
        "session_expired": "Please send the link again.",
        "session_expired_short": "Please start over.",
        "link_invalid": "Link invalid.",
        "cancelled": "Cancelled",
        "already_downloading": "⚠️ Already downloading…",
        "blocked": "🚫 You are blocked.",
        "video_blocked": "🚫 Video blocked.",
        "channel_blocked": "🚫 Channel blocked.",
        "political_channel_blocked": "🚫 This channel is blocked (political/news content).",
        "nsfw_blocked": "🚫 This content is blocked.",
        "sites": "🌍 YouTube, Instagram, Twitter/X, TikTok, SoundCloud & 1000+ more.",
        "lang_changed": "🌐 Language changed to English!",
        "searching": '🔍 Searching "{query}"…',
        "search_prompt_msg": "🔍 Please type your search query:",
        "search_results": '🔍 Results for "{query}":\n\nPage {page}',
        "no_results": '❌ No results for "{query}".',
        "btn_help": "ℹ️ Help", "btn_sites": "🌐 Sites", "btn_download": "📥 Download",
        "btn_search": "🔍 Search", "btn_channel": "📺 Channel", "btn_libgen": "📚 LibGen",
        "btn_subscribe": "⭐ Subscribe", "btn_subscribed": "✅ Subscribed", "btn_donate": "💰 Donate",
        "btn_lang_fa": "🇮🇷 فارسی", "btn_lang_en": "🇬🇧 English",
        "btn_retry": "🔄 Retry", "btn_cancel": "❌ Cancel", "btn_back": "🔙 Back",
        "btn_next": "➡️ Next", "btn_prev": "⬅️ Prev",
        "progress_downloading": "⏳ Downloading… {percent}%\n📦 {downloaded} / {total}\n⚡ {speed}/s\n⏱ {eta}",
        "progress_processing": "⏳ Processing…",
        "video_caption": "📹 {title}\n👤 {uploader} | ⏱ {duration}",
        "download_caption": "✅ {title}",
        "part_caption": "{caption} [{idx}/{total}]",
        "channel_browse": "📺 Channel: {name}\n{count} videos found.",
        "channel_prompt": "📺 Send YouTube channel URL or name!",
        "channel_not_found": "❌ Channel not found.",
        "admin_panel": "👑 Admin Panel\n👥 Users: {users}\n🚫 Blocked: {blocked}\n📺 Blocked ch: {bc}\n📹 Blocked vid: {bv}\n⭐ Subscribers: {subs}",
        "admin_new_user": "🆕 New user: {uid} (@{username})\n{first_name}",
        "choose_upload_method": "📤 Choose upload method:",
        "upload_bale": "📤 Bale (Split <19MB)",
        "upload_bale_desc": "⚠️ Large files split into parts",
        "upload_github": "📤 GitHub (No Split)",
        "upload_github_desc": "✅ Direct download link",
        "github_creating_repo": "⏳ Creating GitHub repository…",
        "uploading_github": "⏳ Uploading to GitHub…",
        "github_encoding": "⏳ Preparing file for GitHub…\n⏱ {elapsed}s elapsed",
        "github_serializing": "⏳ Preparing upload data…\n⏱ {elapsed}s elapsed",
        "github_uploading_progress": "⏳ Uploading to GitHub…\n📡 Please wait…\n⏱ {elapsed}s elapsed",
        "github_success": "✅ Uploaded to GitHub!\n📥 Direct link:\n{link}",
        "github_failed": "❌ GitHub upload failed.\n{error}",
        "github_too_large": "❌ File too large for GitHub (max 100MB).\nTry Bale upload with splitting.",
        "github_link_btn": "📥 Download from GitHub",
        "admin_blocked_list": "🚫 Blocked items:\n\n{items}",
        "admin_no_blocked": "✅ No blocked items.",
        "admin_unblocked": "✅ Unblocked: {item}",
        "admin_already_unblocked": "ℹ️ Already not blocked.",
        "admin_blocked_channels": "📺 Blocked Channels",
        "admin_blocked_videos": "📹 Blocked Videos",
        "admin_users_list": "👥 Users (Page {page}/{total}):\n\n{items}",
        "admin_blocked_users_list": "🚫 Blocked Users:\n\n{items}",
        "admin_user_blocked": "🚫 User {uid} blocked.",
        "admin_user_unblocked": "✅ User {uid} unblocked.",
        "admin_back": "🔙 Back to Panel",
        "announce_format": "📢 Announcement | اطلاعیه\n\n{message}",
        "broadcast_done": "📢 Broadcast: {sent} sent, {fail} failed.",
        "sub_required": "⭐ This feature requires a subscription!\n\nPremium features:\n• Videos longer than 35 minutes\n• TikTok downloads\n• (BETA) LibGen book search & download (PDF)\n• Unlimited GitHub uploads\n\n💵 Weekly: 25,000 Tomans 250,000 IRR)",
        "sub_required_duration": "⭐ This video is {dur} minutes long.\nFree users can download up to 35 minutes.\n\nSubscribe for unlimited length + more!",
        "sub_active": "✅ Your subscription is active until {date}!\n\nPremium features:\n• Videos of any length\n• TikTok downloads\n• LibGen book search\n• Unlimited GitHub uploads",
        "sub_no": "❌ You don't have an active subscription.\n\nPremium features:\n• Videos of any length\n• TikTok downloads\n• LibGen book search\n• Unlimited GitHub uploads\n\n💵 Weekly: 25,000 Tomans",
        "sub_activated": "✅ Subscription activated! Valid until {date}.\n\nPremium features unlocked:\n• Videos of any length\n• TikTok downloads\n• LibGen book search\n• Unlimited GitHub uploads",
        "sub_title": "⭐ Weekly Subscription",
        "sub_desc": "7-day premium access:\n• Unlimited video length\n• TikTok downloads\n• LibGen book search & PDF\n• Unlimited GitHub uploads\n\nPrice: 25,000 Tomans (250,000 IRR)",
        "tiktok_requires_sub": "⭐ TikTok downloads require a subscription!\n\nSubscribe to download TikTok videos + more premium features.",
        "github_upload_limit": "⭐ Free users: {limit} GitHub uploads/day.\nYou've used {count}/{limit} today.\n\nSubscribe for unlimited uploads!",
        "libgen_prompt": "📚 Enter book title or author to search on LibGen:",
        "libgen_searching": '📚 Searching LibGen for "{query}"…',
        "libgen_results": '📚 LibGen results for "{query}":\n\nPage {page}',
        "libgen_no_results": '📚 No books found for "{query}".',
        "libgen_downloading": "📚 Downloading book…",
        "libgen_converting": "📚 Converting to PDF…",
        "libgen_sent": "📚 Book sent!",
        "libgen_requires_sub": "⭐ LibGen search requires a subscription!\n\nSubscribe to search and download books + more premium features.",
        "libgen_download_failed": "❌ Failed to download book from LibGen.",
        "libgen_convert_failed": "⚠️ Could not convert to PDF. Sending original format.",
        "donate_prompt": "💰 Select donation amount (Tomans):",
        "donate_custom": "✏️ Custom Amount",
        "donate_custom_prompt": "💰 Enter amount in Tomans (1,000 - 1,000,000):",
        "donate_thanks": "🙏 Thank you for donating {amount} Tomans!",
        "donate_title": "💰 Donation",
        "donate_desc": "Support the bot",
        "donate_invalid": "❌ Invalid amount. Enter 1,000 - 1,000,000 Tomans.",
        "admin_sub_added": "✅ Subscription added for user {uid} until {date}.",
        "admin_sub_removed": "✅ Subscription removed for user {uid}.",
        "status_text": "📊 Bot Status\n⏱ Uptime: {uptime}\n🖥 Host: {host}\n📁 Downloads: {dl_size}\n📁 Container: {ct_size}\n👥 Users: {users}\n⭐ Subscribers: {subs}\n🔧 FFmpeg: {ffmpeg}\n📚 ebook-convert: {ebook}\n💾 Disk: {disk}",
    },
    "fa": {
        "welcome": "👋 به {bot} خوش آمدید!\n\n📥 دانلود از یوتیوب، اینستاگرام و بیشتر.\n🔍 جستجو با اسم.\n📺 مرور ویدیوهای کانال.\n📚 جستجوی کتاب در LibGen (⭐).\n\n🔧 بهینه‌شده برای ایران.",
        "help": "🔍 راهنما:\n1️⃣ لینک بفرستید یا سرچ کنید\n2️⃣ دانلود → کیفیت\n3️⃣ روش آپلود (بله یا گیت‌هاب)\n4️⃣ فایل‌های بزرگ خودکار تقسیم (<19MB)\n\n⭐ رایگان: ویدیو تا ۳۵ دقیقه، ۲ آپلود گیت‌هاب/روز\n⭐ اشتراک: طول نامحدود، تیک‌تاک، LibGen، آپلود نامحدود\n\n💵 /subscribe | 💰 /donate",
        "analyzing": "🔍 بررسی…",
        "extract_failed": "❌ خطای استخراج.",
        "no_links": "ℹ️ لینکی پیدا نشد.",
        "found_links": "🌐 {count} لینک:\n{links}",
        "choose_quality": "🎬 کیفیت:",
        "downloading": "⏳ دانلود…",
        "queue_wait": "⏳ صف شلوغه…",
        "download_starting": "🔄 شروع دانلود…",
        "download_failed": "❌ دانلود ناموفق.",
        "file_too_large": "⏳ فایل بزرگ — در حال تقسیم…",
        "split_failed": "❌ تقسیم ناموفق.",
        "sent_parts": "✅ در {count} قسمت ارسال شد.",
        "file_not_found": "❌ فایل پیدا نشد.",
        "send_link": "🤖 لینک یا اسم بفرست!",
        "session_expired": "لطفاً لینک را دوباره بفرستید.",
        "session_expired_short": "لطفاً از اول شروع کنید.",
        "link_invalid": "لینک نامعتبر.",
        "cancelled": "لغو شد",
        "already_downloading": "⚠️ در حال دانلود…",
        "blocked": "🚫 محدود شده‌اید.",
        "video_blocked": "🚫 ویدیو مسدود.",
        "channel_blocked": "🚫 کانال مسدود.",
        "political_channel_blocked": "🚫 این کانال مسدود است (محتوای سیاسی/خبری).",
        "nsfw_blocked": "🚫 این محتوا مسدود است.",
        "sites": "🌍 یوتیوب، اینستاگرام، توییتر، تیک‌تاک و ۱۰۰۰+ سایت.",
        "lang_changed": "🌐 زبان فارسی!",
        "searching": '🔍 جستجوی "{query}"…',
        "search_prompt_msg": "🔍 عبارت مورد نظر خود را تایپ کنید:",
        "search_results": '🔍 نتایج "{query}":\n\nصفحه {page}',
        "no_results": '❌ نتیجه‌ای برای "{query}" نیست.',
        "btn_help": "ℹ️ راهنما", "btn_sites": "🌐 سایت‌ها", "btn_download": "📥 دانلود",
        "btn_search": "🔍 جستجو", "btn_channel": "📺 کانال", "btn_libgen": "📚 لیب‌جن",
        "btn_subscribe": "⭐ اشتراک", "btn_subscribed": "✅ اشتراک فعال", "btn_donate": "💰 حمایت مالی",
        "btn_lang_fa": "🇮🇷 فارسی", "btn_lang_en": "🇬🇧 English",
        "btn_retry": "🔄 دوباره", "btn_cancel": "❌ لغو", "btn_back": "🔙 برگشت",
        "btn_next": "➡️ بعدی", "btn_prev": "⬅️ قبلی",
        "progress_downloading": "⏳ دانلود… {percent}%\n📦 {downloaded} / {total}\n⚡ {speed}/s\n⏱ {eta}",
        "progress_processing": "⏳ پردازش…",
        "video_caption": "📹 {title}\n👤 {uploader} | ⏱ {duration}",
        "download_caption": "✅ {title}",
        "part_caption": "{caption} [قسمت {idx}/{total}]",
        "channel_browse": "📺 کانال: {name}\n{count} ویدیو.",
        "channel_prompt": "📺 لینک یا اسم کانال بفرستید!",
        "channel_not_found": "❌ کانال پیدا نشد.",
        "admin_panel": "👑 پنل مدیریت\n👥 کاربران: {users}\n🚫 مسدودشده: {blocked}\n📺 کانال مسدود: {bc}\n📹 ویدیو مسدود: {bv}\n⭐ اشتراک‌داران: {subs}",
        "admin_new_user": "🆕 کاربر جدید: {uid} (@{username})\n{first_name}",
        "choose_upload_method": "📤 روش آپلود را انتخاب کنید:",
        "upload_bale": "📤 بله (تقسیم <19MB)",
        "upload_bale_desc": "⚠️ فایل‌های بزرگ تقسیم میشن",
        "upload_github": "📤 گیت‌هاب (بدون تقسیم)",
        "upload_github_desc": "✅ لینک مستقیم دانلود",
        "github_creating_repo": "⏳ ساخت مخزن گیت‌هاب…",
        "uploading_github": "⏳ آپلود در گیت‌هاب…",
        "github_encoding": "⏳ آماده‌سازی فایل برای گیت‌هاب…\n⏱ {elapsed} ثانیه گذشته",
        "github_serializing": "⏳ آماده‌سازی داده‌های آپلود…\n⏱ {elapsed} ثانیه گذشته",
        "github_uploading_progress": "⏳ آپلود در گیت‌هاب…\n📡 لطفاً صبر کنید…\n⏱ {elapsed} ثانیه گذشته",
        "github_success": "✅ در گیت‌هاب آپلود شد!\n📥 لینک مستقیم:\n{link}",
        "github_failed": "❌ آپلود گیت‌هاب ناموفق.\n{error}",
        "github_too_large": "❌ فایل برای گیت‌هاب خیلی بزرگه (حداکثر 100MB).\nاز بله با تقسیم استفاده کنید.",
        "github_link_btn": "📥 دانلود از گیت‌هاب",
        "admin_blocked_list": "🚫 آیتم‌های مسدود:\n\n{items}",
        "admin_no_blocked": "✅ آیتم مسدودی نیست.",
        "admin_unblocked": "✅ آزاد شد: {item}",
        "admin_already_unblocked": "ℹ️ قبلاً آزاد شده.",
        "admin_blocked_channels": "📺 کانال‌های مسدود",
        "admin_blocked_videos": "📹 ویدیوهای مسدود",
        "admin_users_list": "👥 کاربران (صفحه {page}/{total}):\n\n{items}",
        "admin_blocked_users_list": "🚫 کاربران مسدود:\n\n{items}",
        "admin_user_blocked": "🚫 کاربر {uid} مسدود شد.",
        "admin_user_unblocked": "✅ کاربر {uid} آزاد شد.",
        "admin_back": "🔙 برگشت به پنل",
        "announce_format": "📢 اطلاعیه | Announcement\n\n{message}",
        "broadcast_done": "📢 پیام همگانی: {sent} ارسال شد، {fail} ناموفق.",
        "sub_required": "⭐ این قابلیت نیاز به اشتراک دارد!\n\nمزایای اشتراک:\n• ویدیوهای بالای ۳۵ دقیقه\n• دانلود از تیک‌تاک\n• جستجوی کتاب در LibGen (PDF)\n• آپلود نامحدود گیت‌هاب\n\n💵 هفتگی: 25,000 تومان (250,000 ریال)",
        "sub_required_duration": "⭐ این ویدیو {dur} دقیقه است.\nکاربران رایگان تا ۳۵ دقیقه.\n\nبا اشتراک طول نامحدود + امکانات بیشتر!",
        "sub_active": "✅ اشتراک شما تا {date} فعال است!\n\nمزایای اشتراک:\n• ویدیو با هر طول\n• دانلود تیک‌تاک\n• جستجوی LibGen\n• آپلود نامحدود گیت‌هاب",
        "sub_no": "❌ اشتراک فعالی ندارید.\n\nمزایای اشتراک:\n• ویدیو با هر طول\n• دانلود تیک‌تاک\n• جستجوی LibGen\n• آپلود نامحدود گیت‌هاب\n\n💵 هفتگی: 25,000 تومان",
        "sub_activated": "✅ اشتراک فعال شد! تا {date} معتبر.\n\nمزایای اشتراک:\n• ویدیو با هر طول\n• دانلود تیک‌تاک\n• جستجوی LibGen\n• آپلود نامحدود گیت‌هاب",
        "sub_title": "⭐ اشتراک هفتگی",
        "sub_desc": "دسترسی ۷ روزه:\n• طول ویدیو نامحدود\n• دانلود تیک‌تاک\n• جستجوی LibGen (PDF)\n• آپلود نامحدود گیت‌هاب\n\nقیمت: 25,000 تومان (250,000 ریال)",
        "tiktok_requires_sub": "⭐ دانلود تیک‌تاک نیاز به اشتراک دارد!\n\nبا اشتراک ویدیو تیک‌تاک + امکانات بیشتر دانلود کنید.",
        "github_upload_limit": "⭐ کاربران رایگان: {limit} آپلود گیت‌هاب/روز.\nشما {count}/{limit} استفاده کرده‌اید.\n\nبا اشتراک آپلود نامحدود!",
        "libgen_prompt": "📚 عنوان یا نویسنده کتاب را وارد کنید:",
        "libgen_searching": '📚 جستجو در LibGen: "{query}"…',
        "libgen_results": '📚 نتایج LibGen برای "{query}":\n\nصفحه {page}',
        "libgen_no_results": '📚 کتابی برای "{query}" پیدا نشد.',
        "libgen_downloading": "📚 در حال دانلود کتاب…",
        "libgen_converting": "📚 تبدیل به PDF…",
        "libgen_sent": "📚 کتاب ارسال شد!",
        "libgen_requires_sub": "⭐ جستجوی LibGen نیاز به اشتراک دارد!\n\nبا اشتراک کتاب دانلود کنید + امکانات بیشتر.",
        "libgen_download_failed": "❌ دانلود کتاب از LibGen ناموفق.",
        "libgen_convert_failed": "⚠️ تبدیل به PDF ممکن نبود. فرمت اصلی ارسال می‌شود.",
        "donate_prompt": "💰 مبلغ حمایت (تومان) را انتخاب کنید:",
        "donate_custom": "✏️ مبلغ دلخواه",
        "donate_custom_prompt": "💰 مبلغ به تومان وارد کنید (۱,۰۰۰ - ۱,۰۰۰,۰۰۰):",
        "donate_thanks": "🙏 از حمایت {amount} تومانی شما ممنونیم!",
        "donate_title": "💰 حمایت مالی",
        "donate_desc": "حمایت از بات",
        "donate_invalid": "❌ مبلغ نامعتبر. ۱,۰۰۰ - ۱,۰۰۰,۰۰۰ تومان وارد کنید.",
        "admin_sub_added": "✅ اشتراک کاربر {uid} تا {date} فعال شد.",
        "admin_sub_removed": "✅ اشتراک کاربر {uid} حذف شد.",
        "status_text": "📊 وضعیت ربات\n⏱آپ‌تایم: {uptime}\n🖥 سرور: {host}\n📁 دانلودها: {dl_size}\n📁 کانتینر: {ct_size}\n👥 کاربران: {users}\n⭐ اشتراک‌داران: {subs}\n🔧 FFmpeg: {ffmpeg}\n📚 ebook-convert: {ebook}\n💾 دیسک: {disk}",
    },
}


def t(chat_id: int, key: str, **kwargs) -> str:
    lang = db.get_lang(chat_id)
    text = MESSAGES.get(lang, MESSAGES["fa"]).get(key, MESSAGES["en"].get(key, key))
    return text.format(**kwargs) if kwargs else text


# ========================= Utility Functions =========================

def safe_remove(filepath):
    try:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        logger.warning("safe_remove %s: %s", filepath, e)


def cleanup_dir(directory):
    try:
        if not os.path.isdir(directory):
            return
        for f in os.listdir(directory):
            fp = os.path.join(directory, f)
            if os.path.isfile(fp):
                safe_remove(fp)
    except Exception:
        pass


def format_size(n) -> str:
    if n is None:
        return "???"
    if n == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(n)
    for unit in units:
        if abs(size) < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def format_duration(seconds) -> str:
    if not seconds:
        return "??"
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def safe_caption(text: str, max_len: int = CAPTION_MAX) -> str:
    if not text:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_len:
        return text
    while len(encoded) > max_len - 3:
        text = text[:-1]
        encoded = text.encode("utf-8")
    return text + "…"


def safe_filename(name: str, max_len: int = FILENAME_MAX) -> str:
    base, ext = os.path.splitext(name)
    if len(base) <= max_len - len(ext):
        return name
    return base[: max_len - len(ext) - 3] + "..." + ext


def sanitize_error(err_text: str) -> str:
    text = str(err_text).replace(BOT_TOKEN, "[TOKEN]")
    text = text.replace(GITHUB_TOKEN, "[GH_TOKEN]")
    text = text.replace(WALLET_TOKEN, "[WALLET]")
    text = re.sub(r"https?://[^\s'\"]+", "[URL]", text)
    return text[:200]


def get_content_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    types = {
        ".mp4": "video/mp4", ".mkv": "video/x-matroska", ".webm": "video/webm",
        ".avi": "video/x-msvideo", ".mov": "video/quicktime", ".3gp": "video/3gpp",
        ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".ogg": "audio/ogg",
        ".wav": "audio/wav", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
        ".pdf": "application/pdf", ".epub": "application/epub+zip",
    }
    return types.get(ext, "application/octet-stream")


def reply_markup_to_dict(reply_markup) -> Optional[dict]:
    if reply_markup is None:
        return None
    if isinstance(reply_markup, dict):
        return reply_markup
    if hasattr(reply_markup, "to_dict"):
        return reply_markup.to_dict()
    if hasattr(reply_markup, "inline_keyboard"):
        keyboard = []
        for row in reply_markup.inline_keyboard:
            row_data = []
            for btn in row:
                btn_data = {"text": btn.text}
                if getattr(btn, "callback_data", None):
                    btn_data["callback_data"] = btn.callback_data
                if getattr(btn, "url", None):
                    btn_data["url"] = btn.url
                row_data.append(btn_data)
            keyboard.append(row_data)
        return {"inline_keyboard": keyboard}
    return {}


def _make_vertical(kbd):
    try:
        if hasattr(kbd, "inline_keyboard") and kbd.inline_keyboard:
            all_buttons = [btn for row in kbd.inline_keyboard for btn in row]
            kbd.inline_keyboard = [[btn] for btn in all_buttons]
    except Exception as e:
        logger.warning("_make_vertical failed: %s", e)


def build_vertical_keyboard(buttons_data: list) -> InlineKeyboardMarkup:
    kbd = InlineKeyboardMarkup()
    for item in buttons_data:
        if len(item) == 2:
            text, cb = item
            kbd.add_button(text, callback_data=cb)
        elif len(item) == 3 and item[2] == "url":
            text, url_val, _ = item
            kbd.add_button(text, url=url_val)
    _make_vertical(kbd)
    return kbd


def empty_inline_dict() -> dict:
    return {"inline_keyboard": []}


def disk_usage() -> int:
    total = 0
    try:
        for f in os.listdir(DOWNLOAD_DIR):
            fp = os.path.join(DOWNLOAD_DIR, f)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
    except Exception:
        pass
    return total


def get_folder_size(folder_path: str) -> int:
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(folder_path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.isfile(fp):
                    try:
                        total += os.path.getsize(fp)
                    except Exception:
                        pass
    except Exception:
        pass
    return total


def cleanup_disk():
    while disk_usage() > MAX_DISK_SIZE:
        files = []
        try:
            for f in os.listdir(DOWNLOAD_DIR):
                fp = os.path.join(DOWNLOAD_DIR, f)
                if os.path.isfile(fp):
                    files.append((os.path.getmtime(fp), fp))
        except Exception:
            break
        if not files:
            break
        files.sort()
        safe_remove(files[0][1])


# ========================= Bale API helpers =========================

async def bale_api_call(method: str, payload: dict, max_retries: int = 3) -> dict:
    url = f"{BALE_API_BASE}/{method}"
    last_err = None
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    result = await resp.json()
                    if result.get("ok"):
                        return result
                    desc = result.get("description", "")
                    if resp.status and resp.status >= 500:
                        last_err = Exception(sanitize_error(desc or f"HTTP {resp.status}"))
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2 ** attempt)
                            continue
                    return result
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError, OSError) as e:
            last_err = e
            logger.warning("bale_api_call attempt %d/%d failed: %s", attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
    if last_err:
        raise last_err
    return {"ok": False, "description": "Unknown error"}


async def bale_edit_message_caption(chat_id, msg_id, caption="", reply_markup=None):
    data = {"chat_id": chat_id, "message_id": msg_id, "caption": safe_caption(caption)}
    if reply_markup is not None:
        rm = reply_markup_to_dict(reply_markup)
        data["reply_markup"] = rm if rm else empty_inline_dict()
    return await bale_api_call("editMessageCaption", data)


async def bale_edit_message_text(chat_id, msg_id, text="", reply_markup=None):
    data = {"chat_id": chat_id, "message_id": msg_id, "text": text}
    if reply_markup is not None:
        rm = reply_markup_to_dict(reply_markup)
        data["reply_markup"] = rm if rm else empty_inline_dict()
    return await bale_api_call("editMessageText", data)


async def bale_edit_message_reply_markup(chat_id, msg_id, reply_markup):
    rm = reply_markup_to_dict(reply_markup)
    if not rm:
        rm = empty_inline_dict()
    data = {"chat_id": chat_id, "message_id": msg_id, "reply_markup": rm}
    return await bale_api_call("editMessageReplyMarkup", data)


async def bale_forward_message(chat_id, from_chat_id, message_id):
    return await bale_api_call(
        "forwardMessage",
        {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id},
    )


async def bale_answer_callback(callback_query_id: int, text: str = "", show_alert: bool = False):
    return await bale_api_call(
        "answerCallbackQuery",
        {"callback_query_id": str(callback_query_id), "text": text, "show_alert": show_alert},
    )


async def bale_upload_file(
    method: str, chat_id: int, filepath: str, file_field: str,
    caption: str = "", reply_markup=None, reply_to_message_id: int = None,
    duration: int = None, width: int = None, height: int = None, max_retries: int = 3,
) -> dict:
    url = f"{BALE_API_BASE}/{method}"
    filename = safe_filename(os.path.basename(filepath))
    content_type = get_content_type(filename)
    last_err = None
    for attempt in range(max_retries):
        try:
            with open(filepath, "rb") as f:
                file_bytes = f.read()
            form = aiohttp.FormData()
            form.add_field("chat_id", str(chat_id))
            cap = safe_caption(caption)
            if cap:
                form.add_field("caption", cap)
            if reply_to_message_id:
                form.add_field("reply_to_message_id", str(reply_to_message_id))
            if duration is not None:
                form.add_field("duration", str(duration))
            if width is not None:
                form.add_field("width", str(width))
            if height is not None:
                form.add_field("height", str(height))
            if reply_markup is not None:
                rm = reply_markup_to_dict(reply_markup)
                form.add_field("reply_markup", json.dumps(rm if rm else empty_inline_dict()))
            form.add_field(file_field, file_bytes, filename=filename, content_type=content_type)
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=form, timeout=aiohttp.ClientTimeout(total=180)) as resp:
                    result = await resp.json()
                    if result.get("ok"):
                        return result
                    desc = result.get("description", "")
                    if "too long" in desc.lower() or "bad request" in desc.lower():
                        raise Exception(sanitize_error(desc))
                    if attempt < max_retries - 1:
                        await asyncio.sleep(3 * (attempt + 1))
                        continue
                    raise Exception(sanitize_error(desc))
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError, OSError) as e:
            last_err = e
            if attempt < max_retries - 1:
                await asyncio.sleep(3 * (attempt + 1))
                continue
            raise Exception(sanitize_error(str(last_err)))
    raise Exception(sanitize_error(str(last_err)))


# ========================= Payment / Subscription =========================

async def bale_send_invoice(chat_id: int, title: str, description: str,
                           payload: str, start_parameter: str,
                           currency: str, prices: list) -> dict:
    data = {
        "chat_id": str(chat_id),
        "title": title[:32],
        "description": description[:255],
        "payload": payload[:128],
        "provider_token": WALLET_TOKEN,
        "start_parameter": start_parameter[:64],
        "currency": currency,
        "prices": json.dumps(prices),
    }
    return await bale_api_call("sendInvoice", data)


async def bale_answer_pre_checkout(pre_checkout_query_id, ok=True, error_message=""):
    data = {
        "pre_checkout_query_id": str(pre_checkout_query_id),
        "ok": ok,
    }
    if not ok and error_message:
        data["error_message"] = error_message
    return await bale_api_call("answerPreCheckoutQuery", data)


async def send_subscription_invoice(chat_id: int):
    payload = f"sub_{chat_id}_{int(time.time())}"
    start_param = f"sub_{chat_id}"
    return await bale_send_invoice(chat_id, t(chat_id, "sub_title"), t(chat_id, "sub_desc"),
                                   payload, start_param, "IRR",
                                   [{"label": "Weekly Subscription", "amount": SUBSCRIPTION_PRICE_IRR}])


async def send_donate_invoice(chat_id: int, toman_amount: int):
    irr_amount = toman_amount * 10
    payload = f"donate_{chat_id}_{irr_amount}_{int(time.time())}"
    start_param = f"donate_{chat_id}"
    return await bale_send_invoice(chat_id, t(chat_id, "donate_title"), t(chat_id, "donate_desc"),
                                   payload, start_param, "IRR",
                                   [{"label": "Donation", "amount": irr_amount}])


async def handle_successful_payment(msg_data):
    chat = msg_data.get("chat", {}) if isinstance(msg_data, dict) else {}
    cid = chat.get("id", 0) if isinstance(chat, dict) else 0
    payment = msg_data.get("successful_payment", {}) if isinstance(msg_data, dict) else {}
    if not isinstance(payment, dict):
        payment = {}
    payload = payment.get("invoice_payload", "")
    amount_irr = payment.get("total_amount", 0)

    if payload.startswith("sub_"):
        expiry = time.time() + SUBSCRIPTION_DAYS * 86400
        await db.add_user(cid)
        await db.set_subscription(cid, expiry)
        ds = time.strftime("%Y-%m-%d %H:%M", time.localtime(expiry))
        try:
            await bot.send_message(cid, t(cid, "sub_activated", date=ds))
        except Exception:
            pass
        uinfo = db.get_user(cid) or {}
        un = uinfo.get("username", "")
        fn = uinfo.get("first_name", "")
        ud = f"@{un}" if un else str(cid)
        if fn:
            ud = f"{fn} ({ud})"
        try:
            await bot.send_message(ADMIN_GROUP_ID,
                f"⭐ Subscription activated\n👤 {ud}\n💰 {amount_irr} IRR\n📅 Until {ds}")
        except Exception:
            pass

    elif payload.startswith("donate_"):
        amount_t = amount_irr // 10
        try:
            await bot.send_message(cid, t(cid, "donate_thanks", amount=amount_t))
        except Exception:
            pass
        uinfo = db.get_user(cid) or {}
        un = uinfo.get("username", "")
        fn = uinfo.get("first_name", "")
        ud = f"@{un}" if un else str(cid)
        if fn:
            ud = f"{fn} ({ud})"
        try:
            await bot.send_message(ADMIN_GROUP_ID,
                f"💰 Donation\n👤 {ud}\n💵 {amount_t} Tomans ({amount_irr} IRR)")
        except Exception:
            pass


# ========================= LibGen =========================

LIBGEN_MIRRORS = ["https://libgen.li", "https://libgen.la", "https://libgen.gl"]

async def libgen_search(query: str, max_results: int = 10) -> Optional[List[dict]]:
    for mirror in LIBGEN_MIRRORS:
        try:
            url = f"{mirror}/search.php?req={quote(query)}&res={max_results}&open=0&view=simple&phrase=1&column=def&format=json"
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, list) and data:
                            return data
        except Exception:
            continue
    return None


async def libgen_download_book(md5: str, download_dir: str) -> Optional[str]:
    for mirror_base in [f"https://download.library.lol/main/{md5}"]:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
                async with session.get(mirror_base, allow_redirects=True) as resp:
                    if resp.status == 200:
                        cd = resp.headers.get("Content-Disposition", "")
                        fn_match = re.search(r'filename="?([^";\n]+)"?', cd)
                        fn = fn_match.group(1) if fn_match else f"book_{md5}"
                        fn = safe_filename(fn)
                        fp = os.path.join(download_dir, fn)
                        with open(fp, "wb") as f:
                            async for chunk in resp.content.iter_chunked(8192):
                                f.write(chunk)
                        if os.path.getsize(fp) > 10000:
                            return fp
                        safe_remove(fp)
        except Exception:
            pass

    for mirror in LIBGEN_MIRRORS:
        try:
            page_url = f"{mirror}/ads.php?md5={md5}"
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.get(page_url) as resp:
                    if resp.status != 200:
                        continue
                    html = await resp.text()
                    match = re.search(r'href="(https?://[^"]*get[^"]*)"', html)
                    if not match:
                        match = re.search(r'href="(/get[^"]*)"', html)
                    if not match:
                        continue
                    dl_url = match.group(1)
                    if dl_url.startswith("/"):
                        dl_url = mirror + dl_url
                    async with session.get(dl_url, timeout=aiohttp.ClientTimeout(total=120)) as r2:
                        if r2.status != 200:
                            continue
                        cd = r2.headers.get("Content-Disposition", "")
                        fn_match = re.search(r'filename="?([^";\n]+)"?', cd)
                        fn = fn_match.group(1) if fn_match else f"book_{md5}"
                        fn = safe_filename(fn)
                        fp = os.path.join(download_dir, fn)
                        with open(fp, "wb") as f:
                            async for chunk in r2.content.iter_chunked(8192):
                                f.write(chunk)
                        if os.path.getsize(fp) > 10000:
                            return fp
                        safe_remove(fp)
        except Exception:
            continue
    return None


async def convert_to_pdf(filepath: str) -> Optional[str]:
    if not EBOOK_CONVERT_AVAILABLE:
        return None
    base, _ = os.path.splitext(filepath)
    pdf_path = base + ".pdf"
    cmd = f"ebook-convert {shlex.quote(filepath)} {shlex.quote(pdf_path)}"
    try:
        proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await asyncio.wait_for(proc.communicate(), timeout=300)
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1000:
            return pdf_path
        safe_remove(pdf_path)
    except Exception as e:
        logger.warning("convert_to_pdf failed: %s", e)
        safe_remove(pdf_path)
    return None


async def process_libgen_search(message, query: str, page: int = 0):
    chat_id = message.chat.id
    if not db.has_subscription(chat_id):
        await bot.send_message(chat_id, t(chat_id, "libgen_requires_sub"),
                               reply_markup=build_main_keyboard(chat_id))
        return
    status = await bot.send_message(chat_id, t(chat_id, "libgen_searching", query=query))
    status_id = get_msg_id(status)
    try:
        results = await libgen_search(query)
        if not results:
            try:
                await bale_edit_message_text(chat_id, status_id, t(chat_id, "libgen_no_results", query=query))
            except Exception:
                pass
            return
        user_states[chat_id] = {
            "libgen_results": results,
            "libgen_query": query,
        }
        await show_libgen_page(chat_id, status_id, page)
    except Exception as e:
        logger.error("LibGen search error: %s", sanitize_error(str(e)))


async def show_libgen_page(chat_id, msg_id, page: int = 0):
    session = user_states.get(chat_id)
    if not session or "libgen_results" not in session:
        return
    results = session["libgen_results"]
    query = session.get("libgen_query", "")
    per_page = 5
    total_pages = max(1, math.ceil(len(results) / per_page))
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    end = start + per_page
    buttons = []
    for i, book in enumerate(results[start:end]):
        title = book.get("title", "???")[:50]
        author = book.get("author", "")[:20]
        ext = book.get("extension", "?")
        btn_text = f"📚 {title} - {author} ({ext})"
        buttons.append((btn_text, f"lgdl_{start + i}"))
    if page > 0:
        buttons.append((t(chat_id, "btn_prev"), f"lgpage_{page - 1}"))
    if page < total_pages - 1:
        buttons.append((t(chat_id, "btn_next"), f"lgpage_{page + 1}"))
    buttons.append((t(chat_id, "btn_back"), "back_to_main"))
    kbd = build_vertical_keyboard(buttons)
    page_text = f"{page + 1}/{total_pages}"
    text = t(chat_id, "libgen_results", query=query, page=page_text)
    try:
        await bale_edit_message_text(chat_id, msg_id, text=text, reply_markup=kbd)
    except Exception:
        await bot.send_message(chat_id, text, reply_markup=kbd)


async def process_libgen_download(chat_id, book_index: int):
    session = user_states.get(chat_id)
    if not session or "libgen_results" not in session:
        await bot.send_message(chat_id, t(chat_id, "session_expired"))
        return
    if not db.has_subscription(chat_id):
        await bot.send_message(chat_id, t(chat_id, "libgen_requires_sub"))
        return
    results = session["libgen_results"]
    if book_index >= len(results):
        await bot.send_message(chat_id, t(chat_id, "link_invalid"))
        return
    book = results[book_index]
    md5 = book.get("md5", "")
    title = book.get("title", "???")
    if not md5:
        await bot.send_message(chat_id, t(chat_id, "libgen_download_failed"))
        return
    status = await bot.send_message(chat_id, t(chat_id, "libgen_downloading"))
    status_id = get_msg_id(status)
    try:
        filepath = await libgen_download_book(md5, DOWNLOAD_DIR)
        if not filepath or not os.path.exists(filepath):
            await bale_edit_message_text(chat_id, status_id, t(chat_id, "libgen_download_failed"))
            return
        ext = os.path.splitext(filepath)[1].lower()
        if ext != ".pdf" and EBOOK_CONVERT_AVAILABLE:
            try:
                await bale_edit_message_text(chat_id, status_id, t(chat_id, "libgen_converting"))
                pdf_path = await convert_to_pdf(filepath)
                if pdf_path:
                    safe_remove(filepath)
                    filepath = pdf_path
                else:
                    try:
                        await bot.send_message(chat_id, t(chat_id, "libgen_convert_failed"))
                    except Exception:
                        pass
            except Exception:
                pass
        file_size = os.path.getsize(filepath)
        if file_size <= MAX_FILE_SIZE_BYTES:
            caption = safe_caption(f"📚 {title}")
            await bale_upload_file("sendDocument", chat_id, filepath, "document", caption=caption)
        else:
            caption = t(chat_id, "download_caption", title=title)
            await send_file_safely(chat_id, filepath, caption=caption, url="", channel="LibGen")
        try:
            await bale_edit_message_text(chat_id, status_id, t(chat_id, "libgen_sent"))
        except Exception:
            pass
    except Exception as e:
        logger.error("LibGen download error: %s", sanitize_error(str(e)))
        try:
            await bale_edit_message_text(chat_id, status_id, t(chat_id, "libgen_download_failed"))
        except Exception:
            pass


# ========================= State Management =========================

user_states: Dict[int, Dict[str, Any]] = {}
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)


def get_quality_sizes(info: Dict) -> Dict[str, Optional[int]]:
    formats = info.get("formats", [])
    duration = info.get("duration", 0) or 0
    result: Dict[str, Optional[int]] = {}
    video_fmts, audio_fmts = [], []
    for f in formats:
        if f.get("vcodec") != "none" and f.get("height"):
            video_fmts.append(f)
        if f.get("acodec") != "none" and f.get("vcodec") == "none":
            audio_fmts.append(f)
    best_audio_size, best_audio_tbr = None, 0
    for f in audio_fmts:
        tbr = f.get("tbr") or 0
        if tbr > best_audio_tbr:
            best_audio_tbr = tbr
            best_audio_size = f.get("filesize") or f.get("filesize_approx")
    if not best_audio_size and duration and best_audio_tbr:
        best_audio_size = int(best_audio_tbr * 1000 / 8 * duration)
    for preset in VIDEO_PRESETS:
        target = int(preset.replace("p", ""))
        best_v, best_v_tbr = None, 0
        for f in video_fmts:
            h, tbr = f.get("height"), f.get("tbr") or 0
            if h <= target and tbr > best_v_tbr:
                best_v_tbr, best_v = tbr, f
        if best_v:
            v_size = best_v.get("filesize") or best_v.get("filesize_approx")
            if not v_size and duration and best_v_tbr:
                v_size = int(best_v_tbr * 1000 / 8 * duration)
            total_size = (v_size or 0) + (best_audio_size or 0)
            result[preset] = total_size if total_size > 0 else None
        else:
            result[preset] = None
    for preset in AUDIO_PRESETS:
        result[preset] = best_audio_size
    return result


# ========================= Downloader =========================

class Downloader:
    _BASE_OPTS: Dict[str, Any] = {
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Charset": "ISO-8859-1,utf-8;q=0.7,*;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-us,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
        },
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        "socket_timeout": 30, "retries": 5, "fragment_retries": 3,
        "skip_unavailable_fragments": True, "concurrent_fragments": 1,
        "limit_rate": "1M", "sleep_interval": 1, "max_sleep_interval": 5,
        "ignoreerrors": False, "no_cache_dir": True, "rm_cache_dir": True,
        "quiet": True, "no_warnings": True, "no_color": True,
    }

    @staticmethod
    async def extract_info(url: str) -> Optional[Dict]:
        loop = asyncio.get_running_loop()
        for label, extra in [
            ("#1", {"extractor_args": {"youtube": {"player_client": ["android", "web"]}}}),
            ("#2", {"extractor_args": {"youtube": {"player_client": ["ios", "web"]}}}),
            ("#3", {}),
        ]:
            opts = Downloader._BASE_OPTS.copy()
            if extra:
                opts.update(extra)
            opts.update({"skip_download": True, "extract_flat": False})
            try:
                r = await loop.run_in_executor(None, lambda u=url, o=opts: Downloader._sync_extract(u, o))
                if r:
                    return r
            except Exception as e:
                logger.warning("extract_info %s: %s", label, e)
        return None

    @staticmethod
    def _sync_extract(url, opts):
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    @staticmethod
    async def extract_flat(url: str) -> Optional[Dict]:
        loop = asyncio.get_running_loop()
        opts = Downloader._BASE_OPTS.copy()
        opts.update({"skip_download": True, "extract_flat": True})
        try:
            return await loop.run_in_executor(None, lambda u=url, o=opts: Downloader._sync_extract(u, o))
        except Exception as e:
            logger.warning("extract_flat: %s", e)
            return None

    @staticmethod
    async def search_youtube(query: str, max_results: int = SEARCH_TOTAL) -> Optional[List[Dict]]:
        loop = asyncio.get_running_loop()
        search_url = f"ytsearch{max_results}:{query}"
        for extra in [{"extractor_args": {"youtube": {"player_client": ["android", "web"]}}}, {}]:
            opts = Downloader._BASE_OPTS.copy()
            if extra:
                opts.update(extra)
            opts.update({"skip_download": True, "extract_flat": True})
            try:
                result = await loop.run_in_executor(None, lambda u=search_url, o=opts: Downloader._sync_extract(u, o))
                if result and result.get("entries"):
                    return [e for e in result["entries"] if e and (e.get("id") or e.get("url"))]
            except Exception as e:
                logger.warning("search: %s", e)
        return None

    @staticmethod
    async def download_preset(url: str, preset: str, progress_hooks: list = None) -> Optional[Dict]:
        loop = asyncio.get_running_loop()
        for attempt, (preset_val, fallback) in enumerate([(preset, False), (preset, True), (None, False)]):
            opts = Downloader._build_preset_opts(preset_val, fallback)
            if progress_hooks:
                opts["progress_hooks"] = progress_hooks
            try:
                return await loop.run_in_executor(None, lambda u=url, o=opts: Downloader._sync_download(u, o))
            except Exception as e:
                level = logging.ERROR if attempt == 2 else logging.WARNING
                logger.log(level, "download_preset attempt %d: %s", attempt + 1, e)
        raise Exception("All download attempts failed")

    @staticmethod
    def _build_preset_opts(preset: str = None, fallback: bool = False) -> dict:
        opts = Downloader._BASE_OPTS.copy()
        opts.update({"outtmpl": f"{DOWNLOAD_DIR}/%(title).50s.%(ext)s", "no_playlist": True})
        if preset is None:
            if FFMPEG_AVAILABLE:
                opts["format"] = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
                opts["merge_output_format"] = "mp4"
            else:
                opts["format"] = "best[height<=720][ext=mp4]/best[height<=720]/best"
            return opts
        if preset in AUDIO_PRESETS:
            opts["format"] = "bestaudio/best"
            if FFMPEG_AVAILABLE:
                codec, qual = ("mp3", "192") if preset == "mp3" else ("vorbis", "5")
                opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": codec, "preferredquality": qual}]
            return opts
        height_str = preset.replace("p", "")
        if FFMPEG_AVAILABLE and not fallback:
            opts["format"] = f"bestvideo[height<={height_str}]+bestaudio/best[height<={height_str}]/best"
            opts["merge_output_format"] = "mp4"
        elif FFMPEG_AVAILABLE and fallback:
            opts["format"] = f"best[height<={height_str}]/best"
            opts["merge_output_format"] = "mp4"
        else:
            opts["format"] = f"best[height<={height_str}][ext=mp4]/best[height<={height_str}]/best"
        return opts

    @staticmethod
    def _sync_download(url, opts):
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                return None
            filepath = Downloader._resolve_filepath(ydl, info)
            return {**info, "filepath": filepath}

    @staticmethod
    def _resolve_filepath(ydl, info) -> Optional[str]:
        if "requested_downloads" in info:
            for rd in info["requested_downloads"]:
                fp = rd.get("filepath") or rd.get("_filename")
                if fp and os.path.exists(fp):
                    return fp
        prepared = ydl.prepare_filename(info)
        if prepared and os.path.exists(prepared):
            return prepared
        if prepared:
            base, _ = os.path.splitext(prepared)
            for ext in (".mp4", ".mkv", ".webm", ".flv", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".3gp"):
                candidate = base + ext
                if os.path.exists(candidate):
                    return candidate
        now = time.time()
        recent = []
        for f in os.listdir(DOWNLOAD_DIR):
            fpath = os.path.join(DOWNLOAD_DIR, f)
            if os.path.isfile(fpath) and (now - os.path.getmtime(fpath)) < 300:
                recent.append((os.path.getmtime(fpath), fpath))
        if recent:
            recent.sort(reverse=True)
            return recent[0][1]
        return None


async def get_video_info(filepath: str) -> Optional[Dict]:
    if not FFMPEG_AVAILABLE:
        return None
    cmd = f"ffprobe -v error -show_entries format=duration:stream=width,height -of json {shlex.quote(filepath)}"
    try:
        proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        data = json.loads(stdout.decode().strip())
        duration = float(data.get("format", {}).get("duration", 0))
        w, h = None, None
        for stream in data.get("streams", []):
            if stream.get("width"):
                w, h = stream["width"], stream.get("height")
                break
        return {"duration": duration, "width": w, "height": h}
    except Exception as e:
        logger.warning("get_video_info failed for %s: %s", filepath, e)
        return None


async def _ffmpeg_copy_segment(input_path: str, output_path: str, start: float, duration: float) -> bool:
    cmd = (
        f"ffmpeg -y -nostdin -ss {start:.3f} -i {shlex.quote(input_path)} "
        f"-t {duration:.3f} -c copy -fflags +genpts -avoid_negative_ts make_zero "
        f"-movflags +faststart -map 0:v? -map 0:a? -map 0:s? -err_detect ignore_err "
        f"{shlex.quote(output_path)}"
    )
    proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        await asyncio.wait_for(proc.communicate(), timeout=180)
    except asyncio.TimeoutError:
        proc.kill()
        return False
    if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
        safe_remove(output_path)
        return False
    return True


async def _ffmpeg_encode_segment(input_path: str, output_path: str, start: float, duration: float) -> bool:
    cmd = (
        f"ffmpeg -y -nostdin -ss {start:.3f} -i {shlex.quote(input_path)} "
        f"-t {duration:.3f} -c:v libx264 -crf 28 -preset ultrafast -c:a aac -b:a 96k "
        f"-movflags +faststart -avoid_negative_ts make_zero -map 0:v? -map 0:a? -err_detect ignore_err "
        f"{shlex.quote(output_path)}"
    )
    proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        await asyncio.wait_for(proc.communicate(), timeout=600)
    except asyncio.TimeoutError:
        proc.kill()
        return False
    if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
        safe_remove(output_path)
        return False
    return True


async def split_video_file(input_path: str, output_dir: str, max_size: int) -> List[Dict[str, Any]]:
    if not FFMPEG_AVAILABLE:
        return []
    info = await get_video_info(input_path)
    if not info or not info.get("duration") or info["duration"] <= 0:
        return []
    total_duration = info["duration"]
    file_size = os.path.getsize(input_path)
    basename = os.path.splitext(os.path.basename(input_path))[0][:30]
    ext = os.path.splitext(input_path)[1] or ".mp4"
    target_size = int(max_size * 0.45)
    num_parts = max(2, math.ceil(file_size / target_size))
    for attempt in range(5):
        for f in os.listdir(output_dir):
            fp = os.path.join(output_dir, f)
            if os.path.isfile(fp):
                safe_remove(fp)
        part_dur = total_duration / num_parts
        parts, failed = [], False
        for i in range(num_parts):
            start = i * part_dur
            seg_dur = part_dur if i < num_parts - 1 else (total_duration - start)
            if seg_dur < 0.3:
                continue
            out_path = os.path.join(output_dir, f"{basename}_p{i + 1:03d}{ext}")
            ok = await _ffmpeg_copy_segment(input_path, out_path, start, seg_dur)
            if not ok:
                safe_remove(out_path)
                ok = await _ffmpeg_encode_segment(input_path, out_path, start, seg_dur)
            if not ok:
                for p in parts:
                    safe_remove(p["path"])
                failed = True
                break
            part_size = os.path.getsize(out_path)
            if part_size > max_size:
                safe_remove(out_path)
                for p in parts:
                    safe_remove(p["path"])
                failed = True
                break
            pinfo = await get_video_info(out_path)
            parts.append({"path": out_path, "duration": pinfo.get("duration") if pinfo else seg_dur,
                          "width": pinfo.get("width") if pinfo else None, "height": pinfo.get("height") if pinfo else None})
        if not failed and parts:
            return parts
        num_parts = int(num_parts * 1.5) + 1
        if num_parts > 50:
            break
    return []


def binary_split_file(filepath: str, part_size: int) -> List[Dict[str, Any]]:
    base = os.path.splitext(os.path.basename(filepath))[0][:30]
    ext = os.path.splitext(filepath)[1].lower()
    out_dir = os.path.join(DOWNLOAD_DIR, f"bsplit_{int(time.time() * 1000)}")
    os.makedirs(out_dir, exist_ok=True)
    parts = []
    with open(filepath, "rb") as f:
        idx = 1
        while True:
            chunk = f.read(part_size)
            if not chunk:
                break
            part_path = os.path.join(out_dir, f"{base}_part{idx:03d}{ext}")
            with open(part_path, "wb") as pf:
                pf.write(chunk)
            parts.append({"path": part_path, "duration": None, "width": None, "height": None})
            idx += 1
    return parts


async def split_large_file(filepath: str) -> List[Dict[str, Any]]:
    ext = os.path.splitext(filepath)[1].lower()
    is_video_ext = ext in (".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".m4v", ".3gp")
    if is_video_ext and FFMPEG_AVAILABLE:
        split_dir = os.path.join(DOWNLOAD_DIR, f"split_{int(time.time() * 1000)}")
        os.makedirs(split_dir, exist_ok=True)
        parts = await split_video_file(filepath, split_dir, MAX_FILE_SIZE_BYTES)
        if parts:
            return parts
        cleanup_dir(split_dir)
        try:
            os.rmdir(split_dir)
        except Exception:
            pass
    return binary_split_file(filepath, MAX_FILE_SIZE_BYTES)


bot = Client(BOT_TOKEN)


def build_preset_keyboard(chat_id: int, quality_sizes: Dict[str, Optional[int]] = None) -> InlineKeyboardMarkup:
    buttons, qs = [], quality_sizes or {}
    for p in VIDEO_PRESETS:
        size_str = f" - {format_size(qs[p])}" if p in qs and qs[p] is not None else (" - N/A" if p in qs else "")
        buttons.append((f"🎬 {p}{size_str}", f"dl_{p}"))
    for p in AUDIO_PRESETS:
        size_str = f" - {format_size(qs[p])}" if p in qs and qs[p] is not None else (" - N/A" if p in qs else "")
        buttons.append((f"🎵 {p.upper()}{size_str}", f"dl_{p}"))
    buttons.append((t(chat_id, "btn_back"), "back_to_info"))
    return build_vertical_keyboard(buttons)


def build_upload_method_keyboard(chat_id: int, preset: str) -> InlineKeyboardMarkup:
    buttons = [
        (f"{t(chat_id, 'upload_bale')} - {t(chat_id, 'upload_bale_desc')}", f"bale_{preset}"),
        (f"{t(chat_id, 'upload_github')} - {t(chat_id, 'upload_github_desc')}", f"gh_{preset}"),
        (t(chat_id, "btn_back"), "back_to_formats"),
    ]
    return build_vertical_keyboard(buttons)


def build_download_button(chat_id: int) -> InlineKeyboardMarkup:
    kbd = InlineKeyboardMarkup()
    kbd.add_button(t(chat_id, "btn_download"), callback_data="show_formats")
    _make_vertical(kbd)
    return kbd


def build_main_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add_button(t(chat_id, "btn_search"), callback_data="search_prompt")
    kb.add_button(t(chat_id, "btn_channel"), callback_data="channel_prompt")
    kb.add_button(t(chat_id, "btn_libgen"), callback_data="libgen_prompt")
    if db.has_subscription(chat_id):
        kb.add_button(t(chat_id, "btn_subscribed"), callback_data="sub_info")
    else:
        kb.add_button(t(chat_id, "btn_subscribe"), callback_data="sub_prompt")
    kb.add_button(t(chat_id, "btn_donate"), callback_data="donate_prompt")
    kb.add_button(t(chat_id, "btn_help"), callback_data="help")
    kb.add_button(t(chat_id, "btn_sites"), callback_data="sites")
    kb.add_button(t(chat_id, "btn_lang_fa"), callback_data="lang_fa")
    kb.add_button(t(chat_id, "btn_lang_en"), callback_data="lang_en")
    _make_vertical(kb)
    return kb


def make_progress_hook(state: dict):
    def hook(d):
        if d["status"] == "downloading":
            state["status"] = "downloading"
            state["downloaded_bytes"] = d.get("downloaded_bytes", 0)
            state["total_bytes"] = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            state["speed"] = d.get("speed") or 0
            state["eta"] = d.get("eta") or 0
        elif d["status"] == "finished":
            state["status"] = "finished"
    return hook


def format_progress_text(chat_id, percent, downloaded, total, speed, eta) -> str:
    d_str = format_size(downloaded)
    t_str = format_size(total) if total else "???"
    s_str = format_size(speed) if speed else "???"
    lang = db.get_lang(chat_id)
    eta_str = (f"{eta:.0f} ثانیه" if lang == "fa" else f"{eta:.0f}s") if eta else "???"
    return t(chat_id, "progress_downloading", percent=f"{percent:.1f}", downloaded=d_str, total=t_str, speed=s_str, eta=eta_str)


async def _edit_info_msg(chat_id, msg_id, msg_type, text, reply_markup=None):
    try:
        if msg_type == "photo":
            await bale_edit_message_caption(chat_id, msg_id, caption=text, reply_markup=reply_markup)
        else:
            await bale_edit_message_text(chat_id, msg_id, text=text, reply_markup=reply_markup)
    except Exception as e:
        logger.warning("_edit_info_msg: %s", sanitize_error(str(e)))


async def _progress_updater(chat_id, msg_id, msg_type, state):
    while not state.get("done"):
        await asyncio.sleep(1)
        if state.get("done"):
            break
        if state.get("status") == "finished":
            await _edit_info_msg(chat_id, msg_id, msg_type, t(chat_id, "progress_processing"))
            continue
        downloaded = state.get("downloaded_bytes", 0)
        total = state.get("total_bytes", 0)
        speed = state.get("speed", 0)
        eta = state.get("eta", 0)
        percent = (downloaded / total * 100) if total > 0 else 0
        text = format_progress_text(chat_id, percent, downloaded, total, speed, eta)
        await _edit_info_msg(chat_id, msg_id, msg_type, text)


async def download_with_queue(chat_id, url, preset, info_msg_id, info_msg_type) -> Optional[Dict]:
    cleanup_disk()
    state = {"status": "waiting", "downloaded_bytes": 0, "total_bytes": 0, "speed": 0, "eta": 0, "done": False}
    hook = make_progress_hook(state)
    if download_semaphore._value <= 0:
        await _edit_info_msg(chat_id, info_msg_id, info_msg_type, t(chat_id, "queue_wait"))
    await download_semaphore.acquire()
    try:
        await _edit_info_msg(chat_id, info_msg_id, info_msg_type, t(chat_id, "download_starting"))
        updater = asyncio.create_task(_progress_updater(chat_id, info_msg_id, info_msg_type, state))
        try:
            return await Downloader.download_preset(url, preset, progress_hooks=[hook])
        finally:
            state["done"] = True
            updater.cancel()
            try:
                await updater
            except asyncio.CancelledError:
                pass
    finally:
        download_semaphore.release()


async def send_video_file(chat_id, filepath, caption="", duration=None, width=None, height=None):
    kwargs = {}
    if duration is not None:
        kwargs["duration"] = duration
    if width is not None:
        kwargs["width"] = width
    if height is not None:
        kwargs["height"] = height
    return await bale_upload_file("sendVideo", chat_id, filepath, "video", caption=caption, **kwargs)


async def send_single_file(chat_id, filepath, caption="", force_document=False, duration=None, width=None, height=None):
    ext = os.path.splitext(filepath)[1].lower()
    cap = safe_caption(caption)
    actual_size = os.path.getsize(filepath)
    if actual_size > MAX_FILE_SIZE_BYTES:
        raise Exception(f"File too large ({format_size(actual_size)})")
    if not force_document and ext in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".3gp"):
        try:
            return await send_video_file(chat_id, filepath, caption=cap, duration=duration, width=width, height=height)
        except Exception as e:
            err = str(e).lower()
            if "too long" in err:
                raise
        try:
            return await send_video_file(chat_id, filepath, caption=cap)
        except Exception as e:
            err = str(e).lower()
            if "too long" in err:
                raise
    if not force_document and ext in (".mp3", ".m4a", ".aac", ".ogg", ".wav", ".opus"):
        try:
            return await bale_upload_file("sendAudio", chat_id, filepath, "audio", caption=cap)
        except Exception as e:
            if "too long" in str(e).lower():
                raise
    if not force_document and ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
        try:
            return await bale_upload_file("sendPhoto", chat_id, filepath, "photo", caption=cap)
        except Exception as e:
            if "too long" in str(e).lower():
                raise
    return await bale_upload_file("sendDocument", chat_id, filepath, "document", caption=cap)


async def send_file_part(chat_id, part_info, caption):
    path = part_info["path"]
    part_dur, part_w, part_h = part_info.get("duration"), part_info.get("width"), part_info.get("height")
    ext = os.path.splitext(path)[1].lower()
    is_video_ext = ext in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".3gp")
    if is_video_ext:
        dur_int = int(part_dur) if part_dur else None
        cap = safe_caption(caption)
        for c in [cap, "📹"]:
            try:
                result = await send_video_file(chat_id, path, caption=c, duration=dur_int, width=part_w, height=part_h)
                if result.get("ok"):
                    return True
            except Exception:
                pass
        try:
            result = await send_video_file(chat_id, path, caption="📹")
            if result.get("ok"):
                return True
        except Exception:
            pass
    for c in [safe_caption(caption), "📁"]:
        try:
            result = await bale_upload_file("sendDocument", chat_id, path, "document", caption=c)
            if result.get("ok"):
                return True
        except Exception:
            pass
    return False


async def forward_to_admin_group(chat_id, msg_id, url, channel, title, username="", first_name="", github_url=""):
    user_info = db.get_user(chat_id)
    if user_info:
        if not username:
            username = user_info.get("username", "")
        if not first_name:
            first_name = user_info.get("first_name", "")
    user_display = f"@{username}" if username else str(chat_id)
    if first_name:
        user_display = f"{first_name} ({user_display})"
    if msg_id:
        try:
            await bale_forward_message(ADMIN_GROUP_ID, chat_id, msg_id)
        except Exception as e:
            logger.warning("forward_to_admin_group failed: %s", sanitize_error(str(e)))
    try:
        bid = _store_admin_block(url, channel, title)
        kbd = InlineKeyboardMarkup()
        kbd.add_button("🚫 Block Video", callback_data=f"ablkv_{bid}")
        kbd.add_button("🚫 Block Channel", callback_data=f"ablkc_{bid}")
        _make_vertical(kbd)
        info_text = f"📹 {title[:80]}\n👤 Channel: {channel[:40]}\n🔗 {url[:60]}\n👤 Downloader: {user_display}"
        if github_url:
            info_text += f"\n📥 GitHub: {github_url}"
        await bot.send_message(ADMIN_GROUP_ID, info_text, reply_markup=kbd)
    except Exception as e:
        logger.error("admin_group info log failed: %s", sanitize_error(str(e)))


async def send_file_safely(chat_id, filepath, caption="", url="", channel=""):
    try:
        file_size = os.path.getsize(filepath)
    except FileNotFoundError:
        await bot.send_message(chat_id, t(chat_id, "file_not_found"))
        return
    user_info = db.get_user(chat_id)
    uname = user_info.get("username", "") if user_info else ""
    fname = user_info.get("first_name", "") if user_info else ""
    if file_size <= MAX_FILE_SIZE_BYTES:
        dur_val, w_val, h_val = None, None, None
        ext = os.path.splitext(filepath)[1].lower()
        if ext in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".3gp") and FFMPEG_AVAILABLE:
            vinfo = await get_video_info(filepath)
            if vinfo:
                if vinfo.get("duration"):
                    dur_val = int(vinfo["duration"])
                w_val, h_val = vinfo.get("width"), vinfo.get("height")
        try:
            result = await send_single_file(chat_id, filepath, caption, duration=dur_val, width=w_val, height=h_val)
            if result.get("ok") and result.get("result", {}).get("message_id"):
                msg_id = result["result"]["message_id"]
                title = caption.replace("✅ ", "")[:60]
                asyncio.create_task(forward_to_admin_group(chat_id, msg_id, url, channel, title, username=uname, first_name=fname))
        except Exception as e:
            err = sanitize_error(str(e))
            logger.error("send_file_safely single: %s", err)
            if "too long" in err.lower():
                try:
                    result = await send_single_file(chat_id, filepath, "📁", force_document=True)
                    if result.get("ok") and result.get("result", {}).get("message_id"):
                        msg_id = result["result"]["message_id"]
                        asyncio.create_task(forward_to_admin_group(chat_id, msg_id, url, channel, "📁", username=uname, first_name=fname))
                except Exception as e2:
                    logger.error("send_file_safely fallback: %s", sanitize_error(str(e2)))
        finally:
            safe_remove(filepath)
        return
    logger.info("File too large (%s), splitting...", format_size(file_size))
    status_msg = await bot.send_message(chat_id, t(chat_id, "file_too_large"))
    status_id = get_msg_id(status_msg)
    split_parts = []
    try:
        split_parts = await split_large_file(filepath)
        if not split_parts:
            try:
                await bale_edit_message_text(chat_id, status_id, t(chat_id, "split_failed"))
            except Exception:
                pass
            return
        total = len(split_parts)
        for idx, part_info in enumerate(split_parts, 1):
            part_path = part_info["path"]
            part_caption = t(chat_id, "part_caption", caption=caption, idx=idx, total=total)
            sent_ok = await send_file_part(chat_id, part_info, part_caption)
            safe_remove(part_path)
            if not sent_ok:
                for rem_idx in range(idx, len(split_parts)):
                    safe_remove(split_parts[rem_idx]["path"])
                try:
                    await bale_edit_message_text(chat_id, status_id, f"❌ Part {idx}/{total} failed to send.")
                except Exception:
                    pass
                return
        title = caption.replace("✅ ", "")[:60]
        asyncio.create_task(forward_to_admin_group(chat_id, 0, url, channel, title, username=uname, first_name=fname))
        try:
            await bale_edit_message_text(chat_id, status_id, t(chat_id, "sent_parts", count=total))
        except Exception:
            pass
    except Exception as e:
        logger.error("Split/send error: %s", sanitize_error(str(e)))
        try:
            await bale_edit_message_text(chat_id, status_id, f"❌ {sanitize_error(str(e))}")
        except Exception:
            pass
    finally:
        for part_info in split_parts:
            p = part_info.get("path")
            safe_remove(p)
            if p:
                part_dir = os.path.dirname(p)
                if part_dir and os.path.isdir(part_dir) and part_dir != DOWNLOAD_DIR:
                    cleanup_dir(part_dir)
                    try:
                        os.rmdir(part_dir)
                    except Exception:
                        pass
        safe_remove(filepath)


# ========================= GitHub upload handler =========================

async def send_file_to_github(chat_id, filepath, url, channel, title, info_msg_id, info_msg_type, session):
    logger.info("[GH-HANDLER] START for chat_id=%s file=%s", chat_id, os.path.basename(filepath))
    try:
        file_size = os.path.getsize(filepath)
    except FileNotFoundError:
        await _edit_info_msg(chat_id, info_msg_id, info_msg_type, t(chat_id, "file_not_found"))
        session["downloading"] = False
        return
    logger.info("[GH-HANDLER] File size: %s", _fmt_len(file_size))
    if file_size > GITHUB_MAX_FILE_SIZE:
        await _edit_info_msg(chat_id, info_msg_id, info_msg_type, t(chat_id, "github_too_large"))
        safe_remove(filepath)
        session["downloading"] = False
        return
    user_info = db.get_user(chat_id)
    uname = user_info.get("username", "") if user_info else ""
    fname = user_info.get("first_name", "") if user_info else ""
    repo_name = str(chat_id)
    await _edit_info_msg(chat_id, info_msg_id, info_msg_type, t(chat_id, "github_creating_repo"))

    stop_event = asyncio.Event()
    phase_info = {"phase": "encoding"}

    async def progress_callback(phase: str):
        phase_info["phase"] = phase
        logger.info("[GH-HANDLER] Phase changed to: %s", phase)
        if phase == "encoding":
            await _edit_info_msg(chat_id, info_msg_id, info_msg_type, t(chat_id, "github_encoding", elapsed=0))
        elif phase == "uploading":
            await _edit_info_msg(chat_id, info_msg_id, info_msg_type, t(chat_id, "github_uploading_progress", elapsed=0))

    progress_task = asyncio.create_task(
        _github_progress_updater(chat_id, info_msg_id, info_msg_type, stop_event, phase_info)
    )

    try:
        logger.info("[GH-HANDLER] Calling github_upload_file (Releases API)...")
        download_url = await github_upload_file(repo_name, filepath, progress_callback=progress_callback)
        logger.info("[GH-HANDLER] github_upload_file returned: %s", "SUCCESS" if download_url else "FAILED")
        stop_event.set()
        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass

        if download_url:
            await db.increment_github_upload(chat_id)
            kbd = InlineKeyboardMarkup()
            kbd.add_button(t(chat_id, "github_link_btn"), url=download_url)
            _make_vertical(kbd)
            success_text = t(chat_id, "github_success", link=download_url)
            await _edit_info_msg(chat_id, info_msg_id, info_msg_type, success_text, reply_markup=kbd)
            asyncio.create_task(forward_to_admin_group(
                chat_id, 0, url, channel, title, username=uname, first_name=fname, github_url=download_url
            ))
        else:
            await _edit_info_msg(chat_id, info_msg_id, info_msg_type, t(chat_id, "github_failed", error="Upload to GitHub failed. Try Bale instead."))
    except Exception as e:
        stop_event.set()
        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass
        logger.error("[GH-HANDLER] Exception: %s", sanitize_error(str(e)))
        await _edit_info_msg(chat_id, info_msg_id, info_msg_type, t(chat_id, "github_failed", error=sanitize_error(str(e))))

    safe_remove(filepath)
    session["downloading"] = False
    logger.info("[GH-HANDLER] DONE for chat_id=%s", chat_id)


# ========================= Search & Channel =========================

async def process_search(message, query, page=0):
    chat_id = message.chat.id
    status = await bot.send_message(chat_id, t(chat_id, "searching", query=query))
    status_id = get_msg_id(status)
    try:
        entries = await Downloader.search_youtube(query)
        if not entries:
            try:
                await bale_edit_message_text(chat_id, status_id, t(chat_id, "no_results", query=query))
            except Exception:
                pass
            return
        user_states[chat_id] = {
            "search_results": [
                e.get("url") or e.get("webpage_url") or f"https://www.youtube.com/watch?v={e.get('id', '')}"
                for e in entries
            ],
            "search_titles": [e.get("title", "???")[:60] for e in entries],
            "search_query": query,
        }
        await show_search_page(chat_id, status_id, page)
    except Exception as e:
        logger.error("Search error: %s", sanitize_error(str(e)))


async def show_search_page(chat_id, msg_id, page):
    session = user_states.get(chat_id)
    if not session or "search_results" not in session:
        return
    results = session["search_results"]
    titles = session.get("search_titles", ["???"] * len(results))
    query = session.get("search_query", "")
    total_pages = math.ceil(len(results) / SEARCH_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * SEARCH_PER_PAGE
    end = start + SEARCH_PER_PAGE
    buttons = [(f"🔗 {title[:40]}", f"srch_{start + i}") for i, (url, title) in enumerate(zip(results[start:end], titles[start:end]))]
    total_pages = max(1, total_pages)
    if page > 0:
        buttons.append((t(chat_id, "btn_prev"), f"spage_{page - 1}"))
    if page < total_pages - 1:
        buttons.append((t(chat_id, "btn_next"), f"spage_{page + 1}"))
    kbd = build_vertical_keyboard(buttons)
    page_text = f"{page + 1}/{total_pages}"
    text = t(chat_id, "search_results", query=query, page=page_text)
    try:
        await bale_edit_message_text(chat_id, msg_id, text=text, reply_markup=kbd)
    except Exception:
        await bot.send_message(chat_id, text, reply_markup=kbd)


async def process_channel_search(message, query):
    chat_id = message.chat.id
    status = await bot.send_message(chat_id, t(chat_id, "analyzing"))
    status_id = get_msg_id(status)
    try:
        search_url = f"https://www.youtube.com/results?search_query={query}&sp=EgIQAg%253D%253D"
        info = await Downloader.extract_flat(search_url)
        if not info or not info.get("entries"):
            try:
                await bale_edit_message_text(chat_id, status_id, t(chat_id, "channel_not_found"))
            except Exception:
                pass
            return
        channels = [{"url": e.get("url"), "title": e.get("title", "Unknown Channel")} for e in info["entries"] if e and e.get("url")]
        if not channels:
            try:
                await bale_edit_message_text(chat_id, status_id, t(chat_id, "channel_not_found"))
            except Exception:
                pass
            return
        user_states[chat_id] = {"ch_search_results": channels[:5]}
        buttons = [(f"📺 {ch['title'][:40]}", f"churl_{i}") for i, ch in enumerate(channels[:5])]
        kbd = build_vertical_keyboard(buttons)
        text = t(chat_id, "search_results", query=query, page="Channels")
        try:
            await bale_edit_message_text(chat_id, status_id, text=text, reply_markup=kbd)
        except Exception:
            await bot.send_message(chat_id, text, reply_markup=kbd)
    except Exception as e:
        logger.error("Channel search error: %s", sanitize_error(str(e)))


async def process_channel(message, url):
    chat_id = message.chat.id
    status = await bot.send_message(chat_id, t(chat_id, "analyzing"))
    status_id = get_msg_id(status)
    try:
        info = await Downloader.extract_flat(url)
        if not info:
            try:
                await bale_edit_message_text(chat_id, status_id, t(chat_id, "channel_not_found"))
            except Exception:
                pass
            return
        entries = [e for e in (info.get("entries") or []) if e and (e.get("id") or e.get("url"))]
        if not entries:
            try:
                await bale_edit_message_text(chat_id, status_id, t(chat_id, "channel_not_found"))
            except Exception:
                pass
            return
        channel_name = info.get("channel") or info.get("title") or "Unknown"
        user_states[chat_id] = {
            "channel_results": [
                e.get("url") or e.get("webpage_url") or f"https://www.youtube.com/watch?v={e.get('id', '')}"
                for e in entries
            ],
            "channel_titles": [e.get("title", "???")[:60] for e in entries],
            "channel_name": channel_name,
        }
        await show_channel_page(chat_id, status_id, 0)
    except Exception as e:
        logger.error("Channel error: %s", sanitize_error(str(e)))


async def show_channel_page(chat_id, msg_id, page):
    session = user_states.get(chat_id)
    if not session or "channel_results" not in session:
        return
    results = session["channel_results"]
    titles = session.get("channel_titles", ["???"] * len(results))
    channel_name = session.get("channel_name", "Channel")
    total_pages = math.ceil(len(results) / SEARCH_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * SEARCH_PER_PAGE
    end = start + SEARCH_PER_PAGE
    buttons = [(f"📹 {title[:40]}", f"srch_{start + i}") for i, (url, title) in enumerate(zip(results[start:end], titles[start:end]))]
    total_pages = max(1, total_pages)
    if page > 0:
        buttons.append((t(chat_id, "btn_prev"), f"cpage_{page - 1}"))
    if page < total_pages - 1:
        buttons.append((t(chat_id, "btn_next"), f"cpage_{page + 1}"))
    kbd = build_vertical_keyboard(buttons)
    text = t(chat_id, "channel_browse", name=channel_name, count=len(results))
    try:
        await bale_edit_message_text(chat_id, msg_id, text=text, reply_markup=kbd)
    except Exception:
        await bot.send_message(chat_id, text, reply_markup=kbd)


# ========================= Process link =========================

async def process_link(message, url):
    chat_id = message.chat.id
    if is_nsfw_url(url):
        await bot.send_message(chat_id, t(chat_id, "nsfw_blocked"))
        return
    if is_tiktok_url(url) and not db.has_subscription(chat_id):
        await bot.send_message(chat_id, t(chat_id, "tiktok_requires_sub"),
                               reply_markup=build_main_keyboard(chat_id))
        return
    username, first_name = extract_user_info(message)
    is_new = await db.add_user(chat_id, username, first_name)
    if is_new:
        admin_text = t(chat_id, "admin_new_user", uid=chat_id, username=username or "-", first_name=first_name or "-")
        try:
            await bot.send_message(ADMIN_GROUP_ID, admin_text)
        except Exception:
            pass
    if not db.is_user_allowed(chat_id):
        await bot.send_message(chat_id, t(chat_id, "blocked"))
        return
    if db.is_video_blocked(url):
        await bot.send_message(chat_id, t(chat_id, "video_blocked"))
        return
    status = await bot.send_message(chat_id, t(chat_id, "analyzing"))
    status_id = get_msg_id(status)
    try:
        info = await Downloader.extract_info(url)
    except Exception as e:
        logger.error("extract_info error: %s", sanitize_error(str(e)))
        info = None
    if not info:
        try:
            await bale_edit_message_text(chat_id, status_id, t(chat_id, "extract_failed"))
        except Exception:
            pass
        return
    channel = info.get("channel") or info.get("uploader") or info.get("uploader_id") or ""
    if channel and db.is_channel_blocked(channel):
        try:
            await bale_edit_message_text(chat_id, status_id, t(chat_id, "channel_blocked"))
        except Exception:
            pass
        return
    if channel and is_political_channel(channel):
        try:
            await bale_edit_message_text(chat_id, status_id, t(chat_id, "political_channel_blocked"))
        except Exception:
            pass
        return
    channel_url = info.get("channel_url") or info.get("uploader_url") or ""
    if channel_url and db.is_channel_blocked(channel_url):
        try:
            await bale_edit_message_text(chat_id, status_id, t(chat_id, "channel_blocked"))
        except Exception:
            pass
        return
    title = info.get("title", "???")
    duration = info.get("duration", 0) or 0
    uploader = info.get("uploader") or info.get("channel") or "???"
    thumbnail = info.get("thumbnail") or ""
    quality_sizes = get_quality_sizes(info)

    # Duration limit for free users
    if duration > MAX_FREE_DURATION and not db.has_subscription(chat_id):
        dur_min = int(duration) // 60
        try:
            await bale_edit_message_text(chat_id, status_id, t(chat_id, "sub_required_duration", dur=dur_min))
        except Exception:
            pass
        return

    user_states[chat_id] = {
        "url": url, "title": title, "channel": channel, "duration": duration,
        "uploader": uploader, "quality_sizes": quality_sizes,
        "info_msg_id": status_id, "info_msg_type": "text", "downloading": False,
    }
    caption = t(chat_id, "video_caption", title=title, uploader=uploader, duration=format_duration(duration))
    kbd = build_download_button(chat_id)
    thumb_sent = False
    if thumbnail:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(thumbnail, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        thumb_bytes = await resp.read()
                        if thumb_bytes and len(thumb_bytes) > 500:
                            thumb_path = os.path.join(DOWNLOAD_DIR, f"thumb_{chat_id}_{int(time.time())}.jpg")
                            with open(thumb_path, "wb") as tf:
                                tf.write(thumb_bytes)
                            try:
                                result = await bale_upload_file("sendPhoto", chat_id, thumb_path, "photo", caption=safe_caption(caption), reply_markup=kbd)
                                if result.get("ok"):
                                    thumb_sent = True
                                    msg_id = result.get("result", {}).get("message_id", 0)
                                    user_states[chat_id]["info_msg_id"] = msg_id
                                    user_states[chat_id]["info_msg_type"] = "photo"
                                    try:
                                        await bale_api_call("deleteMessage", {"chat_id": chat_id, "message_id": status_id})
                                    except Exception:
                                        pass
                            except Exception as e:
                                logger.warning("sendPhoto thumb failed: %s", sanitize_error(str(e)))
                            finally:
                                safe_remove(thumb_path)
        except Exception as e:
            logger.warning("Thumbnail download failed: %s", e)
    if not thumb_sent:
        try:
            await bale_edit_message_text(chat_id, status_id, text=caption, reply_markup=kbd)
        except Exception:
            pass


# ========================= Download handlers =========================

async def handle_download_bale(chat_id, preset):
    session = user_states.get(chat_id)
    if not session or "url" not in session:
        await bot.send_message(chat_id, t(chat_id, "session_expired"))
        return
    if session.get("downloading"):
        await bot.send_message(chat_id, t(chat_id, "already_downloading"))
        return
    url, channel, title = session["url"], session.get("channel", ""), session.get("title", "???")
    info_msg_id, info_msg_type = session.get("info_msg_id", 0), session.get("info_msg_type", "text")
    session["downloading"] = True
    try:
        result = await download_with_queue(chat_id, url, preset, info_msg_id, info_msg_type)
        if not result or not result.get("filepath"):
            await _edit_info_msg(chat_id, info_msg_id, info_msg_type, t(chat_id, "download_failed"))
            session["downloading"] = False
            return
        filepath = result["filepath"]
        if not os.path.exists(filepath):
            await _edit_info_msg(chat_id, info_msg_id, info_msg_type, t(chat_id, "file_not_found"))
            session["downloading"] = False
            return
        await _edit_info_msg(chat_id, info_msg_id, info_msg_type, t(chat_id, "downloading"))
        caption = t(chat_id, "download_caption", title=title)
        await send_file_safely(chat_id, filepath, caption=caption, url=url, channel=channel)
        try:
            await _edit_info_msg(chat_id, info_msg_id, info_msg_type, t(chat_id, "download_caption", title=title))
        except Exception:
            pass
    except Exception as e:
        logger.error("handle_download_bale error: %s", sanitize_error(str(e)))
        await _edit_info_msg(chat_id, info_msg_id, info_msg_type, f"❌ {sanitize_error(str(e))}")
    finally:
        session["downloading"] = False


async def handle_download_github(chat_id, preset):
    session = user_states.get(chat_id)
    if not session or "url" not in session:
        await bot.send_message(chat_id, t(chat_id, "session_expired"))
        return
    if session.get("downloading"):
        await bot.send_message(chat_id, t(chat_id, "already_downloading"))
        return

    # Check GitHub upload rate limit
    if not db.can_github_upload(chat_id):
        count = db.get_github_uploads_today(chat_id)
        await bot.send_message(chat_id, t(chat_id, "github_upload_limit", limit=FREE_GH_DAILY_LIMIT, count=count),
                               reply_markup=build_main_keyboard(chat_id))
        return

    url, channel, title = session["url"], session.get("channel", ""), session.get("title", "???")
    info_msg_id, info_msg_type = session.get("info_msg_id", 0), session.get("info_msg_type", "text")
    session["downloading"] = True
    try:
        result = await download_with_queue(chat_id, url, preset, info_msg_id, info_msg_type)
        if not result or not result.get("filepath"):
            await _edit_info_msg(chat_id, info_msg_id, info_msg_type, t(chat_id, "download_failed"))
            session["downloading"] = False
            return
        filepath = result["filepath"]
        if not os.path.exists(filepath):
            await _edit_info_msg(chat_id, info_msg_id, info_msg_type, t(chat_id, "file_not_found"))
            session["downloading"] = False
            return
        await send_file_to_github(chat_id, filepath, url, channel, title, info_msg_id, info_msg_type, session)
    except Exception as e:
        logger.error("handle_download_github error: %s", sanitize_error(str(e)))
        await _edit_info_msg(chat_id, info_msg_id, info_msg_type, f"❌ {sanitize_error(str(e))}")
        session["downloading"] = False


# ========================= Admin panel =========================

ADMIN_USERS_PER_PAGE = 5


async def show_admin_panel(chat_id, msg_id=0):
    all_users = db.all_users()
    bc = db.data.get("blocked_channels", [])
    bv = db.data.get("blocked_videos", [])
    blocked_count = len(db.blocked_users())
    subs_count = db.count_subscribers()
    text = t(chat_id, "admin_panel", users=len(all_users), blocked=blocked_count, bc=len(bc), bv=len(bv), subs=subs_count)
    kbd = build_vertical_keyboard([
        (f"👥 Users ({len(all_users)})", "admin_list_users"),
        (f"🚫 Blocked Users ({blocked_count})", "admin_list_blocked_users"),
        (f"📺 Blocked Channels ({len(bc)})", "admin_list_channels"),
        (f"📹 Blocked Videos ({len(bv)})", "admin_list_videos"),
    ])
    if msg_id:
        try:
            await bale_edit_message_text(chat_id, msg_id, text=text, reply_markup=kbd)
            return
        except Exception:
            pass
    await bot.send_message(chat_id, text, reply_markup=kbd)


async def show_admin_users(chat_id, msg_id, page=0):
    all_users = db.all_users()
    if not all_users:
        try:
            await bale_edit_message_text(chat_id, msg_id, t(chat_id, "admin_no_blocked"))
        except Exception:
            pass
        return
    user_list = list(all_users.items())
    total_pages = max(1, math.ceil(len(user_list) / ADMIN_USERS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))
    start = page * ADMIN_USERS_PER_PAGE
    end = start + ADMIN_USERS_PER_PAGE
    items_text = ""
    buttons = []
    for uid_str, uinfo in user_list[start:end]:
        name = uinfo.get("first_name", "???")[:20]
        uname = uinfo.get("username", "-")[:15]
        blocked_mark = " 🚫" if uinfo.get("blocked") else ""
        sub_mark = " ⭐" if uinfo.get("subscription_expiry", 0) > time.time() else ""
        items_text += f"• {name} (@{uname}) [{uid_str}]{blocked_mark}{sub_mark}\n"
        if uinfo.get("blocked"):
            buttons.append((f"✅ Unblock {uid_str}", f"aulkusr_{uid_str}"))
        else:
            buttons.append((f"🚫 Block {uid_str}", f"ablkusr_{uid_str}"))
        if uinfo.get("subscription_expiry", 0) > time.time():
            buttons.append((f"❌ Remove Sub {uid_str}", f"aremsub_{uid_str}"))
        else:
            buttons.append((f"⭐ Add Sub {uid_str}", f"aaddsub_{uid_str}"))
    if page > 0:
        buttons.append((t(chat_id, "btn_prev"), f"aupage_{page - 1}"))
    if page < total_pages - 1:
        buttons.append((t(chat_id, "btn_next"), f"aupage_{page + 1}"))
    buttons.append((t(chat_id, "admin_back"), "admin_back"))
    kbd = build_vertical_keyboard(buttons)
    text = t(chat_id, "admin_users_list", page=page + 1, total=total_pages, items=items_text)
    try:
        await bale_edit_message_text(chat_id, msg_id, text=text, reply_markup=kbd)
    except Exception:
        pass


async def show_admin_blocked_users(chat_id, msg_id):
    blocked = db.blocked_users()
    if not blocked:
        try:
            await bale_edit_message_text(chat_id, msg_id, t(chat_id, "admin_no_blocked"))
        except Exception:
            pass
        return
    items_text = ""
    buttons = []
    for idx, (uid_str, uinfo) in enumerate(blocked.items()):
        if idx >= 20:
            items_text += f"… and {len(blocked) - 20} more\n"
            break
        name = uinfo.get("first_name", "???")[:20]
        uname = uinfo.get("username", "-")[:15]
        items_text += f"• {name} (@{uname}) [{uid_str}]\n"
        buttons.append((f"✅ Unblock {uid_str}", f"aulkusr_{uid_str}"))
    buttons.append((t(chat_id, "admin_back"), "admin_back"))
    kbd = build_vertical_keyboard(buttons)
    text = t(chat_id, "admin_blocked_users_list", items=items_text)
    try:
        await bale_edit_message_text(chat_id, msg_id, text=text, reply_markup=kbd)
    except Exception:
        pass


async def show_admin_blocked_channels(chat_id, msg_id):
    bc = db.data.get("blocked_channels", [])
    if not bc:
        try:
            await bale_edit_message_text(chat_id, msg_id, t(chat_id, "admin_no_blocked"))
        except Exception:
            pass
        return
    items_text, buttons = "", []
    for idx, ch in enumerate(bc[:20]):
        items_text += f"{idx + 1}. {ch[:60]}\n"
        buttons.append((f"✅ Unblock: {ch[:30]}", f"aunbc_{idx}"))
    buttons.append((t(chat_id, "admin_back"), "admin_back"))
    kbd = build_vertical_keyboard(buttons)
    try:
        await bale_edit_message_text(chat_id, msg_id, text=t(chat_id, "admin_blocked_list", items=items_text), reply_markup=kbd)
    except Exception:
        pass


async def show_admin_blocked_videos(chat_id, msg_id):
    bv = db.data.get("blocked_videos", [])
    if not bv:
        try:
            await bale_edit_message_text(chat_id, msg_id, t(chat_id, "admin_no_blocked"))
        except Exception:
            pass
        return
    items_text, buttons = "", []
    for idx, vurl in enumerate(bv[:20]):
        items_text += f"{idx + 1}. {vurl[:60]}\n"
        buttons.append((f"✅ Unblock: {vurl[:30]}", f"aunbv_{idx}"))
    buttons.append((t(chat_id, "admin_back"), "admin_back"))
    kbd = build_vertical_keyboard(buttons)
    try:
        await bale_edit_message_text(chat_id, msg_id, text=t(chat_id, "admin_blocked_list", items=items_text), reply_markup=kbd)
    except Exception:
        pass


# ========================= Startup =========================

_startup_done = False

async def _ensure_startup():
    global _startup_done
    if _startup_done:
        return
    _startup_done = True
    asyncio.create_task(get_github_owner())
    logger.info("Startup background tasks initiated.")


# ========================= Callback handler =========================

@bot.on_callback_query()
async def handle_callback(callback: CallbackQuery):
    try:
        chat_id = callback.message.chat.id if callback.message else 0
        if not chat_id:
            return
        data = getattr(callback, "data", "") or ""
        if not data:
            return
        msg_id = get_msg_id(callback.message)
        cq_id = getattr(callback, "id", "") or ""
        session_cb = user_states.get(chat_id, {})
        msg_type = session_cb.get("info_msg_type", "text") if session_cb else "text"

        # ---- Language ----
        if data == "lang_fa":
            await db.set_lang(chat_id, "fa")
            await bale_answer_callback(cq_id, t(chat_id, "lang_changed"))
            await _edit_info_msg(chat_id, msg_id, msg_type, t(chat_id, "welcome", bot=BOT_USERNAME), reply_markup=build_main_keyboard(chat_id))
            return
        if data == "lang_en":
            await db.set_lang(chat_id, "en")
            await bale_answer_callback(cq_id, t(chat_id, "lang_changed"))
            await _edit_info_msg(chat_id, msg_id, msg_type, t(chat_id, "welcome", bot=BOT_USERNAME), reply_markup=build_main_keyboard(chat_id))
            return

        # ---- Info pages ----
        if data == "help":
            await bale_answer_callback(cq_id)
            await _edit_info_msg(chat_id, msg_id, msg_type, t(chat_id, "help"), reply_markup=build_main_keyboard(chat_id))
            return
        if data == "sites":
            await bale_answer_callback(cq_id)
            await _edit_info_msg(chat_id, msg_id, msg_type, t(chat_id, "sites"), reply_markup=build_main_keyboard(chat_id))
            return
        if data == "back_to_main":
            await bale_answer_callback(cq_id)
            await _edit_info_msg(chat_id, msg_id, msg_type, t(chat_id, "welcome", bot=BOT_USERNAME), reply_markup=build_main_keyboard(chat_id))
            return

        # ---- Search prompt ----
        if data == "search_prompt":
            await bale_answer_callback(cq_id)
            await _edit_info_msg(chat_id, msg_id, msg_type, t(chat_id, "search_prompt_msg"))
            session = user_states.get(chat_id, {})
            session["awaiting_search"], session["awaiting_channel"], session["awaiting_libgen"], session["awaiting_donate_custom"] = True, False, False, False
            user_states[chat_id] = session
            return
        if data == "channel_prompt":
            await bale_answer_callback(cq_id)
            await _edit_info_msg(chat_id, msg_id, msg_type, t(chat_id, "channel_prompt"))
            session = user_states.get(chat_id, {})
            session["awaiting_channel"], session["awaiting_search"], session["awaiting_libgen"], session["awaiting_donate_custom"] = True, False, False, False
            user_states[chat_id] = session
            return
        if data == "libgen_prompt":
            await bale_answer_callback(cq_id)
            await _edit_info_msg(chat_id, msg_id, msg_type, t(chat_id, "libgen_prompt"))
            session = user_states.get(chat_id, {})
            session["awaiting_libgen"], session["awaiting_search"], session["awaiting_channel"], session["awaiting_donate_custom"] = True, False, False, False
            user_states[chat_id] = session
            return

        # ---- Subscription ----
        if data == "sub_prompt":
            await bale_answer_callback(cq_id)
            await send_subscription_invoice(chat_id)
            return
        if data == "sub_info":
            await bale_answer_callback(cq_id)
            expiry = db.get_subscription_expiry(chat_id)
            if expiry > time.time():
                ds = time.strftime("%Y-%m-%d %H:%M", time.localtime(expiry))
                await bot.send_message(chat_id, t(chat_id, "sub_active", date=ds))
            else:
                await bot.send_message(chat_id, t(chat_id, "sub_no"))
            return

        # ---- Donate ----
        if data == "donate_prompt":
            await bale_answer_callback(cq_id)
            buttons = [
                ("💰 1,000 T", "donate_1000"),
                ("💰 5,000 T", "donate_5000"),
                ("💰 10,000 T", "donate_10000"),
                ("💰 50,000 T", "donate_50000"),
                ("💰 100,000 T", "donate_100000"),
                (t(chat_id, "donate_custom"), "donate_custom_prompt"),
                (t(chat_id, "btn_back"), "back_to_main"),
            ]
            kbd = build_vertical_keyboard(buttons)
            await _edit_info_msg(chat_id, msg_id, msg_type, t(chat_id, "donate_prompt"), reply_markup=kbd)
            return

        if data == "donate_custom_prompt":
            await bale_answer_callback(cq_id)
            await _edit_info_msg(chat_id, msg_id, msg_type, t(chat_id, "donate_custom_prompt"))
            session = user_states.get(chat_id, {})
            session["awaiting_donate_custom"], session["awaiting_search"], session["awaiting_channel"], session["awaiting_libgen"] = True, False, False, False
            user_states[chat_id] = session
            return

        # Fixed donation amounts
        donate_match = re.match(r"^donate_(\d+)$", data)
        if donate_match:
            toman_amount = int(donate_match.group(1))
            await bale_answer_callback(cq_id)
            if DONATE_MIN_TOMANS <= toman_amount <= DONATE_MAX_TOMANS:
                await send_donate_invoice(chat_id, toman_amount)
            else:
                await bot.send_message(chat_id, t(chat_id, "donate_invalid"))
            return

        # ---- Search result selection ----
        srch_match = re.match(r"^srch_(\d+)$", data)
        if srch_match:
            idx = int(srch_match.group(1))
            session = user_states.get(chat_id, {})
            results = session.get("search_results", []) or session.get("channel_results", [])
            if idx < len(results):
                url = results[idx]
                await bale_answer_callback(cq_id)
                session["awaiting_search"] = False
                session["awaiting_channel"] = False
                user_states[chat_id] = session
                await process_link(callback.message, url)
            else:
                await bale_answer_callback(cq_id, t(chat_id, "link_invalid"))
            return

        # Search pagination
        spage_match = re.match(r"^spage_(\d+)$", data)
        if spage_match:
            page = int(spage_match.group(1))
            await bale_answer_callback(cq_id)
            await show_search_page(chat_id, msg_id, page)
            return

        # Channel pagination
        cpage_match = re.match(r"^cpage_(\d+)$", data)
        if cpage_match:
            page = int(cpage_match.group(1))
            await bale_answer_callback(cq_id)
            await show_channel_page(chat_id, msg_id, page)
            return

        # Channel URL selection
        churl_match = re.match(r"^churl_(\d+)$", data)
        if churl_match:
            idx = int(churl_match.group(1))
            session = user_states.get(chat_id, {})
            ch_results = session.get("ch_search_results", [])
            if idx < len(ch_results):
                ch_url = ch_results[idx]["url"]
                await bale_answer_callback(cq_id)
                session["awaiting_channel"] = False
                user_states[chat_id] = session
                await process_channel(callback.message, ch_url)
            else:
                await bale_answer_callback(cq_id, t(chat_id, "link_invalid"))
            return

        # ---- Show formats / download buttons ----
        if data == "show_formats":
            session = user_states.get(chat_id, {})
            if not session or "url" not in session:
                await bale_answer_callback(cq_id, t(chat_id, "session_expired"))
                return
            quality_sizes = session.get("quality_sizes", {})
            kbd = build_preset_keyboard(chat_id, quality_sizes)
            await bale_answer_callback(cq_id)
            await _edit_info_msg(chat_id, msg_id, msg_type, t(chat_id, "choose_quality"), reply_markup=kbd)
            return

        # Back to info (from format selection)
        if data == "back_to_info":
            session = user_states.get(chat_id, {})
            if not session or "url" not in session:
                await bale_answer_callback(cq_id, t(chat_id, "session_expired"))
                return
            title = session.get("title", "???")
            uploader = session.get("uploader", "???")
            duration = session.get("duration", 0)
            caption = t(chat_id, "video_caption", title=title, uploader=uploader, duration=format_duration(duration))
            kbd = build_download_button(chat_id)
            await bale_answer_callback(cq_id)
            await _edit_info_msg(chat_id, msg_id, msg_type, caption, reply_markup=kbd)
            return

        # ---- Quality / preset selection -> show upload method ----
        dl_match = re.match(r"^dl_(.+)$", data)
        if dl_match:
            preset = dl_match.group(1)
            session = user_states.get(chat_id, {})
            if not session or "url" not in session:
                await bale_answer_callback(cq_id, t(chat_id, "session_expired"))
                return
            kbd = build_upload_method_keyboard(chat_id, preset)
            await bale_answer_callback(cq_id)
            await _edit_info_msg(chat_id, msg_id, msg_type, t(chat_id, "choose_upload_method"), reply_markup=kbd)
            return

        # Back to formats (from upload method)
        if data == "back_to_formats":
            session = user_states.get(chat_id, {})
            if not session or "url" not in session:
                await bale_answer_callback(cq_id, t(chat_id, "session_expired"))
                return
            quality_sizes = session.get("quality_sizes", {})
            kbd = build_preset_keyboard(chat_id, quality_sizes)
            await bale_answer_callback(cq_id)
            await _edit_info_msg(chat_id, msg_id, msg_type, t(chat_id, "choose_quality"), reply_markup=kbd)
            return

        # ---- Bale download ----
        bale_match = re.match(r"^bale_(.+)$", data)
        if bale_match:
            preset = bale_match.group(1)
            await bale_answer_callback(cq_id)
            asyncio.create_task(handle_download_bale(chat_id, preset))
            return

        # ---- GitHub download ----
        gh_match = re.match(r"^gh_(.+)$", data)
        if gh_match:
            preset = gh_match.group(1)
            await bale_answer_callback(cq_id)
            asyncio.create_task(handle_download_github(chat_id, preset))
            return

        # ---- LibGen pagination ----
        lgpage_match = re.match(r"^lgpage_(\d+)$", data)
        if lgpage_match:
            page = int(lgpage_match.group(1))
            await bale_answer_callback(cq_id)
            await show_libgen_page(chat_id, msg_id, page)
            return

        # ---- LibGen download ----
        lgdl_match = re.match(r"^lgdl_(\d+)$", data)
        if lgdl_match:
            book_index = int(lgdl_match.group(1))
            await bale_answer_callback(cq_id)
            asyncio.create_task(process_libgen_download(chat_id, book_index))
            return

        # ---- Admin: block video ----
        ablkv_match = re.match(r"^ablkv_(.+)$", data)
        if ablkv_match and chat_id == ADMIN_ID:
            bid = ablkv_match.group(1)
            block_info = _admin_blocks.get(bid, {})
            url = block_info.get("url", "")
            if url:
                await db.block_video(url)
                await bale_answer_callback(cq_id, "🚫 Video blocked")
            else:
                await bale_answer_callback(cq_id, "❌ Not found")
            return

        # ---- Admin: block channel ----
        ablkc_match = re.match(r"^ablkc_(.+)$", data)
        if ablkc_match and chat_id == ADMIN_ID:
            bid = ablkc_match.group(1)
            block_info = _admin_blocks.get(bid, {})
            channel = block_info.get("channel", "")
            if channel:
                await db.block_channel(channel)
                await bale_answer_callback(cq_id, "🚫 Channel blocked")
            else:
                await bale_answer_callback(cq_id, "❌ Not found")
            return

        # ---- Admin: list users ----
        if data == "admin_list_users" and chat_id == ADMIN_ID:
            await bale_answer_callback(cq_id)
            await show_admin_users(chat_id, msg_id, 0)
            return

        # ---- Admin: list blocked users ----
        if data == "admin_list_blocked_users" and chat_id == ADMIN_ID:
            await bale_answer_callback(cq_id)
            await show_admin_blocked_users(chat_id, msg_id)
            return

        # ---- Admin: list blocked channels ----
        if data == "admin_list_channels" and chat_id == ADMIN_ID:
            await bale_answer_callback(cq_id)
            await show_admin_blocked_channels(chat_id, msg_id)
            return

        # ---- Admin: list blocked videos ----
        if data == "admin_list_videos" and chat_id == ADMIN_ID:
            await bale_answer_callback(cq_id)
            await show_admin_blocked_videos(chat_id, msg_id)
            return

        # ---- Admin: back to panel ----
        if data == "admin_back" and chat_id == ADMIN_ID:
            await bale_answer_callback(cq_id)
            await show_admin_panel(chat_id, msg_id)
            return

        # ---- Admin: user pagination ----
        aupage_match = re.match(r"^aupage_(\d+)$", data)
        if aupage_match and chat_id == ADMIN_ID:
            page = int(aupage_match.group(1))
            await bale_answer_callback(cq_id)
            await show_admin_users(chat_id, msg_id, page)
            return

        # ---- Admin: block/unblock user ----
        ablkusr_match = re.match(r"^ablkusr_(.+)$", data)
        if ablkusr_match and chat_id == ADMIN_ID:
            uid_str = ablkusr_match.group(1)
            try:
                uid = int(uid_str)
            except ValueError:
                await bale_answer_callback(cq_id, "❌ Invalid user ID")
                return
            await db.block_user(uid)
            await bale_answer_callback(cq_id, t(chat_id, "admin_user_blocked", uid=uid))
            await show_admin_users(chat_id, msg_id, 0)
            return

        aulkusr_match = re.match(r"^aulkusr_(.+)$", data)
        if aulkusr_match and chat_id == ADMIN_ID:
            uid_str = aulkusr_match.group(1)
            try:
                uid = int(uid_str)
            except ValueError:
                await bale_answer_callback(cq_id, "❌ Invalid user ID")
                return
            await db.unblock_user(uid)
            await bale_answer_callback(cq_id, t(chat_id, "admin_user_unblocked", uid=uid))
            await show_admin_users(chat_id, msg_id, 0)
            return

        # ---- Admin: add/remove subscription ----
        aaddsub_match = re.match(r"^aaddsub_(.+)$", data)
        if aaddsub_match and chat_id == ADMIN_ID:
            uid_str = aaddsub_match.group(1)
            try:
                uid = int(uid_str)
            except ValueError:
                await bale_answer_callback(cq_id, "❌ Invalid user ID")
                return
            expiry = time.time() + SUBSCRIPTION_DAYS * 86400
            await db.add_user(uid)
            await db.set_subscription(uid, expiry)
            ds = time.strftime("%Y-%m-%d %H:%M", time.localtime(expiry))
            await bale_answer_callback(cq_id, t(chat_id, "admin_sub_added", uid=uid, date=ds))
            await show_admin_users(chat_id, msg_id, 0)
            return

        aremsub_match = re.match(r"^aremsub_(.+)$", data)
        if aremsub_match and chat_id == ADMIN_ID:
            uid_str = aremsub_match.group(1)
            try:
                uid = int(uid_str)
            except ValueError:
                await bale_answer_callback(cq_id, "❌ Invalid user ID")
                return
            await db.remove_subscription(uid)
            await bale_answer_callback(cq_id, t(chat_id, "admin_sub_removed", uid=uid))
            await show_admin_users(chat_id, msg_id, 0)
            return

        # ---- Admin: unblock channel ----
        aunbc_match = re.match(r"^aunbc_(\d+)$", data)
        if aunbc_match and chat_id == ADMIN_ID:
            idx = int(aunbc_match.group(1))
            bc = db.data.get("blocked_channels", [])
            if 0 <= idx < len(bc):
                ch = bc[idx]
                await db.unblock_channel(ch)
                await bale_answer_callback(cq_id, t(chat_id, "admin_unblocked", item=ch[:30]))
                await show_admin_blocked_channels(chat_id, msg_id)
            else:
                await bale_answer_callback(cq_id, "❌ Not found")
            return

        # ---- Admin: unblock video ----
        aunbv_match = re.match(r"^aunbv_(\d+)$", data)
        if aunbv_match and chat_id == ADMIN_ID:
            idx = int(aunbv_match.group(1))
            bv = db.data.get("blocked_videos", [])
            if 0 <= idx < len(bv):
                vurl = bv[idx]
                await db.unblock_video(vurl)
                await bale_answer_callback(cq_id, t(chat_id, "admin_unblocked", item=vurl[:30]))
                await show_admin_blocked_videos(chat_id, msg_id)
            else:
                await bale_answer_callback(cq_id, "❌ Not found")
            return

        # ---- Fallback ----
        await bale_answer_callback(cq_id, "")

    except Exception as e:
        logger.error("handle_callback error: %s", sanitize_error(str(e)))


# ========================= Pre-checkout handler =========================

@bot.on_pre_checkout_query()
async def handle_pre_checkout(pre_checkout):
    try:
        cq_id = getattr(pre_checkout, "id", "") or ""
        payload = getattr(pre_checkout, "invoice_payload", "") or ""
        if isinstance(pre_checkout, dict):
            cq_id = pre_checkout.get("id", "")
            payload = pre_checkout.get("invoice_payload", "")
        # Accept all valid payloads
        if payload.startswith("sub_") or payload.startswith("donate_"):
            await bale_answer_pre_checkout(cq_id, ok=True)
        else:
            await bale_answer_pre_checkout(cq_id, ok=False, error_message="Invalid payment")
    except Exception as e:
        logger.error("pre_checkout error: %s", sanitize_error(str(e)))


# ========================= Message handler =========================

@bot.on_message()
async def handle_message(message: Message):
    try:
        chat_id = message.chat.id if message.chat else 0
        if not chat_id:
            return

        await _ensure_startup()

        # ---- Check for successful_payment in message ----
        msg_dict = None
        if hasattr(message, "to_dict"):
            try:
                msg_dict = message.to_dict()
            except Exception:
                pass
        if msg_dict and msg_dict.get("successful_payment"):
            await handle_successful_payment(msg_dict)
            return
        if hasattr(message, "successful_payment") and message.successful_payment:
            sp = message.successful_payment
            sp_dict = sp if isinstance(sp, dict) else {}
            if hasattr(sp, "to_dict"):
                try:
                    sp_dict = sp.to_dict()
                except Exception:
                    pass
            fake_msg = {
                "chat": {"id": chat_id},
                "successful_payment": sp_dict,
            }
            await handle_successful_payment(fake_msg)
            return

        text = (message.text or "").strip()
        username, first_name = extract_user_info(message)

        # ---- Admin commands ----
        if chat_id == ADMIN_ID:
            if text == "/admin" or text == f"/admin@{BOT_USERNAME.lstrip('@')}":
                await show_admin_panel(chat_id)
                return

            if text.startswith("/broadcast ") or text.startswith(f"/broadcast@{BOT_USERNAME.lstrip('@')} "):
                parts = text.split(" ", 1)
                if len(parts) < 2:
                    await bot.send_message(chat_id, "Usage: /broadcast <message>")
                    return
                broadcast_msg = parts[1].strip()
                all_users = db.all_users()
                sent_count, fail_count = 0, 0
                announce_text = t(chat_id, "announce_format", message=broadcast_msg)
                for uid_str in list(all_users.keys()):
                    try:
                        uid = int(uid_str)
                        if uid == ADMIN_ID:
                            continue
                        if db.is_user_blocked(uid):
                            continue
                        await bot.send_message(uid, announce_text)
                        sent_count += 1
                    except Exception:
                        fail_count += 1
                    await asyncio.sleep(0.05)
                await bot.send_message(chat_id, t(chat_id, "broadcast_done", sent=sent_count, fail=fail_count))
                return

            if text.startswith("/blockchannel ") or text.startswith(f"/blockchannel@{BOT_USERNAME.lstrip('@')} "):
                parts = text.split(" ", 1)
                if len(parts) < 2:
                    await bot.send_message(chat_id, "Usage: /blockchannel <channel_name>")
                    return
                ch_name = parts[1].strip()
                await db.block_channel(ch_name)
                await bot.send_message(chat_id, f"🚫 Channel blocked: {ch_name}")
                return

            if text.startswith("/unblockchannel ") or text.startswith(f"/unblockchannel@{BOT_USERNAME.lstrip('@')} "):
                parts = text.split(" ", 1)
                if len(parts) < 2:
                    await bot.send_message(chat_id, "Usage: /unblockchannel <channel_name>")
                    return
                ch_name = parts[1].strip()
                await db.unblock_channel(ch_name)
                await bot.send_message(chat_id, f"✅ Channel unblocked: {ch_name}")
                return

            if text.startswith("/blockvideo ") or text.startswith(f"/blockvideo@{BOT_USERNAME.lstrip('@')} "):
                parts = text.split(" ", 1)
                if len(parts) < 2:
                    await bot.send_message(chat_id, "Usage: /blockvideo <url>")
                    return
                vurl = parts[1].strip()
                await db.block_video(vurl)
                await bot.send_message(chat_id, f"🚫 Video blocked: {vurl[:60]}")
                return

            if text.startswith("/unblockvideo ") or text.startswith(f"/unblockvideo@{BOT_USERNAME.lstrip('@')} "):
                parts = text.split(" ", 1)
                if len(parts) < 2:
                    await bot.send_message(chat_id, "Usage: /unblockvideo <url>")
                    return
                vurl = parts[1].strip()
                await db.unblock_video(vurl)
                await bot.send_message(chat_id, f"✅ Video unblocked: {vurl[:60]}")
                return

            if text.startswith("/blockuser ") or text.startswith(f"/blockuser@{BOT_USERNAME.lstrip('@')} "):
                parts = text.split(" ", 1)
                if len(parts) < 2:
                    await bot.send_message(chat_id, "Usage: /blockuser <user_id>")
                    return
                try:
                    uid = int(parts[1].strip())
                except ValueError:
                    await bot.send_message(chat_id, "❌ Invalid user ID")
                    return
                await db.block_user(uid)
                await bot.send_message(chat_id, t(chat_id, "admin_user_blocked", uid=uid))
                return

            if text.startswith("/unblockuser ") or text.startswith(f"/unblockuser@{BOT_USERNAME.lstrip('@')} "):
                parts = text.split(" ", 1)
                if len(parts) < 2:
                    await bot.send_message(chat_id, "Usage: /unblockuser <user_id>")
                    return
                try:
                    uid = int(parts[1].strip())
                except ValueError:
                    await bot.send_message(chat_id, "❌ Invalid user ID")
                    return
                await db.unblock_user(uid)
                await bot.send_message(chat_id, t(chat_id, "admin_user_unblocked", uid=uid))
                return

            if text == "/status" or text == f"/status@{BOT_USERNAME.lstrip('@')}":
                uptime_s = int(time.time() - BOT_START_TIME)
                uptime_h = uptime_s // 3600
                uptime_m = (uptime_s % 3600) // 60
                uptime_str = f"{uptime_h}h {uptime_m}m"
                host_info = f"{platform.system()} {platform.release()} ({platform.machine()})"
                dl_size = format_size(get_folder_size(DOWNLOAD_DIR))
                ct_size = format_size(get_folder_size(CONTAINER_DIR))
                total_users = len(db.all_users())
                subs_count = db.count_subscribers()
                ffmpeg_str = "✅" if FFMPEG_AVAILABLE else "❌"
                ebook_str = "✅" if EBOOK_CONVERT_AVAILABLE else "❌"
                disk_free = 0
                try:
                    disk_free = os.statvfs(".").f_bavail * os.statvfs(".").f_frsize
                except Exception:
                    try:
                        stat = os.statvfs(DOWNLOAD_DIR)
                        disk_free = stat.f_bavail * stat.f_frsize
                    except Exception:
                        disk_free = 0
                disk_str = f"{format_size(disk_free)} free"
                status_text = t(chat_id, "status_text",
                    uptime=uptime_str, host=host_info, dl_size=dl_size,
                    ct_size=ct_size, users=total_users, subs=subs_count,
                    ffmpeg=ffmpeg_str, ebook=ebook_str, disk=disk_str)
                await bot.send_message(chat_id, status_text)
                return

        # ---- User commands ----
        if text == "/start" or text == f"/start@{BOT_USERNAME.lstrip('@')}":
            is_new = await db.add_user(chat_id, username, first_name)
            if is_new:
                admin_text = t(chat_id, "admin_new_user", uid=chat_id, username=username or "-", first_name=first_name or "-")
                try:
                    await bot.send_message(ADMIN_GROUP_ID, admin_text)
                except Exception:
                    pass
            await bot.send_message(chat_id, t(chat_id, "welcome", bot=BOT_USERNAME),
                                   reply_markup=build_main_keyboard(chat_id))
            # Reset awaiting states
            session = user_states.get(chat_id, {})
            session["awaiting_search"] = False
            session["awaiting_channel"] = False
            session["awaiting_libgen"] = False
            session["awaiting_donate_custom"] = False
            user_states[chat_id] = session
            return

        if text == "/help" or text == f"/help@{BOT_USERNAME.lstrip('@')}":
            await db.add_user(chat_id, username, first_name)
            await bot.send_message(chat_id, t(chat_id, "help"), reply_markup=build_main_keyboard(chat_id))
            return

        if text == "/subscribe" or text == f"/subscribe@{BOT_USERNAME.lstrip('@')}":
            await db.add_user(chat_id, username, first_name)
            if db.has_subscription(chat_id):
                expiry = db.get_subscription_expiry(chat_id)
                ds = time.strftime("%Y-%m-%d %H:%M", time.localtime(expiry))
                await bot.send_message(chat_id, t(chat_id, "sub_active", date=ds))
            else:
                await send_subscription_invoice(chat_id)
            return

        if text == "/donate" or text == f"/donate@{BOT_USERNAME.lstrip('@')}":
            await db.add_user(chat_id, username, first_name)
            buttons = [
                ("💰 1,000 T", "donate_1000"),
                ("💰 5,000 T", "donate_5000"),
                ("💰 10,000 T", "donate_10000"),
                ("💰 50,000 T", "donate_50000"),
                ("💰 100,000 T", "donate_100000"),
                (t(chat_id, "donate_custom"), "donate_custom_prompt"),
                (t(chat_id, "btn_back"), "back_to_main"),
            ]
            kbd = build_vertical_keyboard(buttons)
            await bot.send_message(chat_id, t(chat_id, "donate_prompt"), reply_markup=kbd)
            return

        if text == "/sites" or text == f"/sites@{BOT_USERNAME.lstrip('@')}":
            await db.add_user(chat_id, username, first_name)
            await bot.send_message(chat_id, t(chat_id, "sites"), reply_markup=build_main_keyboard(chat_id))
            return

        # ---- Register user ----
        is_new = await db.add_user(chat_id, username, first_name)
        if is_new:
            admin_text = t(chat_id, "admin_new_user", uid=chat_id, username=username or "-", first_name=first_name or "-")
            try:
                await bot.send_message(ADMIN_GROUP_ID, admin_text)
            except Exception:
                pass

        if not db.is_user_allowed(chat_id):
            await bot.send_message(chat_id, t(chat_id, "blocked"))
            return

        # ---- Check awaiting states ----
        session = user_states.get(chat_id, {})

        # Awaiting custom donation amount
        if session.get("awaiting_donate_custom"):
            session["awaiting_donate_custom"] = False
            user_states[chat_id] = session
            try:
                cleaned = text.replace(",", "").replace("،", "").strip()
                toman_amount = int(cleaned)
            except ValueError:
                await bot.send_message(chat_id, t(chat_id, "donate_invalid"))
                return
            if DONATE_MIN_TOMANS <= toman_amount <= DONATE_MAX_TOMANS:
                await send_donate_invoice(chat_id, toman_amount)
            else:
                await bot.send_message(chat_id, t(chat_id, "donate_invalid"))
            return

        # Awaiting search query
        if session.get("awaiting_search"):
            session["awaiting_search"] = False
            user_states[chat_id] = session
            await process_search(message, text)
            return

        # Awaiting channel query
        if session.get("awaiting_channel"):
            session["awaiting_channel"] = False
            user_states[chat_id] = session
            if re.match(r"https?://", text):
                await process_channel(message, text)
            else:
                await process_channel_search(message, text)
            return

        # Awaiting LibGen query
        if session.get("awaiting_libgen"):
            session["awaiting_libgen"] = False
            user_states[chat_id] = session
            await process_libgen_search(message, text)
            return

        # ---- URL detection ----
        url_pattern = re.compile(
            r"https?://[^\s<>\"]+|www\.[^\s<>\"]+",
            re.IGNORECASE,
        )
        url_match = url_pattern.search(text)
        if url_match:
            url = url_match.group(0)
            if not url.startswith("http"):
                url = "https://" + url
            await process_link(message, url)
            return

        # ---- Treat as search query ----
        if len(text) >= 2:
            await process_search(message, text)
            return

        # ---- Fallback ----
        await bot.send_message(chat_id, t(chat_id, "send_link"), reply_markup=build_main_keyboard(chat_id))

    except Exception as e:
        logger.error("handle_message error: %s", sanitize_error(str(e)))
        try:
            chat_id = message.chat.id if message.chat else 0
            if chat_id:
                await bot.send_message(chat_id, f"❌ {sanitize_error(str(e))[:200]}")
        except Exception:
            pass

# ========================= Heartbeat =========================
HEARTBEAT_FILE = "t-heartbeat.txt"

def _heartbeat_writer():
    """Background thread that writes to heartbeat.txt every 20 seconds."""
    while True:
        try:
            with open(HEARTBEAT_FILE, "w") as f:
                f.write(str(time.time()))
        except Exception:
            pass
        time.sleep(5)        
        
# ========================= Main Execution =========================

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info(f"{BOT_USERNAME} v15 Starting...")
    logger.info("FFmpeg: %s", "✅" if FFMPEG_AVAILABLE else "❌")
    logger.info("ebook-convert: %s", "✅" if EBOOK_CONVERT_AVAILABLE else "❌")
    logger.info("Download dir: %s", DOWNLOAD_DIR)
    logger.info("Container dir: %s", CONTAINER_DIR)
    logger.info("Max file size: %s", format_size(MAX_FILE_SIZE_BYTES))
    logger.info("Max disk: %s", format_size(MAX_DISK_SIZE))
    logger.info("Admin ID: %s", ADMIN_ID)
    logger.info("Admin Group: %s", ADMIN_GROUP_ID)
    logger.info("=" * 60)

    # Clean up old downloads
    cleanup_dir(DOWNLOAD_DIR)
    try:
        cleanup_dir(CONTAINER_DIR)
    except Exception:
        pass

    # Pyrobale manages its own asyncio loop and polling via .run()
     # Start the heartbeat thread so tmanager.py knows we are alive
    heartbeat_thread = threading.Thread(target=_heartbeat_writer, daemon=True)
    heartbeat_thread.start()
    
    logger.info("Starting bot with pyrobale.Client.run()...")
    try:
        bot.run()
    except Exception as e:
        logger.critical("Fatal error running bot: %s", e)