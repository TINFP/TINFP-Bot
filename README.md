# TINFP-Bot

**TheIranianNetFreedomBot** – a feature-rich media downloader and subscription bot for the **Bale** messaging platform.

> **Main Script:** `tinfp.py`  
> **Watchdog Manager:** `tmanager.py`

---

## 📌 Overview

TINFP-Bot is a powerful Bale bot that allows users to download videos/audio from YouTube, Instagram, TikTok, and 1000+ other sites, search YouTube channels, browse channel content, search and download books from **LibGen**, and upload files to **GitHub Releases** for direct download.

The bot implements a **weekly subscription** (via Bale Wallet) that unlocks premium features: unlimited video length, TikTok downloads, LibGen book search/PDF conversion, and unlimited GitHub uploads. Free users have a 35‑minute video limit and 2 GitHub uploads per day.

An **admin panel** provides user management, blocklists (videos, channels, users), subscription granting/revocation, and system status monitoring. A watchdog manager (`tmanager.py`) automatically restarts the bot if it crashes or freezes.

---

## ✨ Features

### For all users (free)
- Download video/audio from YouTube, Instagram, Twitter, SoundCloud, TikTok*, and many more.
- Search YouTube by keyword.
- Browse any YouTube channel and view its videos.
- Choose video quality (720p … 128p) or audio only (MP3, OGG).
- Files larger than 19 MB are **automatically split** and sent as multiple messages.
- GitHub upload (2 uploads/day, files up to 100 MB) with direct download link.
- Language: English / فارسی (Persian).
- Donation via Bale Wallet (1,000 – 1,000,000 Tomans).

### With weekly subscription (⭐)
- **Unlimited video length** (no 35‑minute restriction).
- **TikTok video download**.
- **LibGen book search** + download (supports PDF conversion via `ebook-convert`).
- **Unlimited GitHub uploads** (no daily limit).

### Admin features
- Block/unblock users, channels, individual videos.
- Grant/revoke subscription for any user.
- Broadcast messages to all users.
- View bot status (uptime, disk usage, tool availability, subscriber count).
- Inline admin panel for quick actions.

### Technical highlights
- Multi‑session resilient downloader (yt‑dlp).
- FFmpeg‑based splitting and video info extraction.
- GitHub Releases API for file hosting.
- Automatic disk cleanup (max 650 MB).
- Connection error handling + auto‑reconnect.
- Heartbeat file → watchdog monitors liveness.

---

## 🧰 Requirements

- **Python 3.8+**
- **Bale Bot Token** – obtain from [Bale's BotFather](https://ble.ir/botfather)
- **Bale Wallet Token** – for receiving payments (optional but required for subscriptions/donations)
- **GitHub Personal Access Token** – with `repo` scope (for uploading files)
- **FFmpeg** (recommended) – for better splitting, merging, and video info
- **Calibre `ebook-convert`** (optional) – for converting e‑books to PDF
- **Linux / Unix** environment (the bot uses `shlex.quote`, `os.kill`, etc.)

### Python dependencies
Install with:
```bash
pip install pyrobale yt-dlp aiohttp
```

---

## ⚙️ Configuration

Before running, edit `tinfp.py` (or rename it from `tinfp-raw.py`) and set the following variables:

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Your Bale bot token |
| `BOT_USERNAME` | Bot username (without `@`) |
| `ADMIN_ID` | Your numeric user ID (admin) |
| `ADMIN_GROUP_ID` | Group ID where logs & block buttons are sent |
| `WALLET_TOKEN` | Bale Wallet token for payments |
| `GITHUB_TOKEN` | GitHub personal access token (repo scope) |
| `SUBSCRIPTION_PRICE_IRR` | Price in Iranian Rials (default: 250,000 IRR = 25,000 Toman) |
| `DOWNLOAD_DIR` | Folder for temporary downloads (default: `downloads`) |
| `CONTAINER_DIR` | Alternative folder (used for monitoring) |
| `MAX_FILE_SIZE_BYTES` | Max size per Bale message (19 MB default) |
| `MAX_DISK_SIZE` | Auto‑cleanup threshold (650 MB) |

> ⚠️ **Do not share your tokens.** Consider using environment variables or a `config.py` for production.

### GitHub token setup
1. Go to GitHub Settings → Developer settings → Personal access tokens → Tokens (classic).
2. Generate a token with **`repo`** scope.
3. Copy the token into `GITHUB_TOKEN`.

### Bale Wallet token
- Contact Bale support to enable Wallet for your bot.
- You will receive a `provider_token` – paste it as `WALLET_TOKEN`.

---

## 🚀 Running the Bot

### Single process (manual)
```bash
python tinfp.py
```

### With watchdog manager (recommended)
The manager (`tmanager.py`) starts `tinfp.py` and monitors a heartbeat file (`t-heartbeat.txt`). If the bot freezes or crashes, it is automatically restarted.

```bash
python tmanager.py
```

The manager runs forever – press `Ctrl+C` to stop both manager and bot.

---

## 📱 Usage (User Commands)

| Command / Action | Description |
|------------------|-------------|
| `/start` | Welcome message + main menu |
| `/help` | Help text |
| `/subscribe` | Purchase weekly subscription (Bale Wallet) |
| `/donate` | Send donation (custom amount) |
| `/sites` | List supported websites |
| Send a **YouTube / Instagram / TikTok** link | Start download process |
| Send any **text** (≥2 characters) | YouTube search |
| Inline buttons | Choose quality, upload method (Bale or GitHub), browse search results, etc. |

### Download process
1. Send a link (or search query).
2. Bot shows video info + **Download** button.
3. Choose video quality / audio format.
4. Choose upload method:
   - **Bale** – file sent directly (split if >19 MB).
   - **GitHub** – upload to GitHub Releases, receive a direct download link.

### LibGen book search (⭐ subscription required)
- Tap **📚 LibGen** button → enter book title/author → select book → download (PDF conversion if available).

### Channel browsing
- Tap **📺 Channel** button → send channel URL or name → browse videos → tap any to download.

---

## 🛠️ Admin Commands

Admin must use the commands in a private chat with the bot (or in the group where the bot is added, if `ADMIN_ID` matches).

| Command | Description |
|---------|-------------|
| `/admin` | Open inline admin panel |
| `/broadcast <message>` | Send a message to all users (except blocked) |
| `/blockchannel <name>` | Block a channel by name |
| `/unblockchannel <name>` | Unblock channel |
| `/blockvideo <url>` | Block a specific video URL |
| `/unblockvideo <url>` | Unblock video |
| `/blockuser <user_id>` | Block a user |
| `/unblockuser <user_id>` | Unblock user |
| `/status` | Show bot status (uptime, disk usage, tools, subscribers) |

**Inline admin panel** provides:
- List users (block/unblock, add/remove subscription)
- List blocked channels / videos (unblock)
- View blocked users

> ℹ️ Admin automatically has active subscription (no need to purchase).

---

## 🧹 File Management

- Downloads are stored in `DOWNLOAD_DIR` (default `downloads`).
- When disk usage exceeds `MAX_DISK_SIZE` (650 MB), the oldest file is deleted.
- Splitting creates temporary directories inside `downloads`; they are cleaned after sending.
- GitHub uploads use your GitHub account as storage – files are uploaded to a **public repository** named after the user ID.

---

## 🔧 Troubleshooting

### Bot does not respond
- Check that `BOT_TOKEN` is correct.
- Ensure the bot is added to the admin group (if `ADMIN_GROUP_ID` is set).
- Run `python tinfp.py` manually to see error logs.

### FFmpeg or ebook‑convert not found
- Install FFmpeg: `sudo apt install ffmpeg` (Debian/Ubuntu)
- Install Calibre: `sudo apt install calibre` (provides `ebook-convert`)
- The bot works without them but with reduced functionality (e.g., no video splitting, no PDF conversion).

### GitHub upload fails
- Verify `GITHUB_TOKEN` has `repo` scope.
- File size must be ≤ 100 MB.
- Check your GitHub rate limits (free tier: 60 API calls/hour).

### Subscription payment not working
- Ensure `WALLET_TOKEN` is valid.
- Bale Wallet must be activated for your bot.
- The currency is hardcoded to `IRR` – do not change unless you adjust prices accordingly.

---

## 📁 Project Structure

```
TINFP-Bot/
├── tinfp.py          # Main bot code
├── tmanager.py       # Watchdog manager
├── t-heartbeat.txt   # Created automatically (heartbeat)
├── downloads/        # Temporary downloads (auto‑created)
├── bot_database.json # User data (auto‑created)
├── LICENSE
└── README.md
```

---

## ⚠️ Disclaimer

This bot is intended for **personal and educational use** only.  
The developer is not responsible for any misuse, copyright violations, or legal consequences arising from downloading protected content.  
Users must comply with their local laws and the terms of service of the platforms they access.

The bot includes filters to block **NSFW** content and **political/news channels** as defined in the source code. These lists are hardcoded and can be modified by the admin.

---

**Enjoy your media freedom!** 🕊️  
For questions or improvements, feel free to open an issue on GitHub.
