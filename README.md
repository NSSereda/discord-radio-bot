# Discord Radio Bot

A minimal Discord bot that streams internet radio and YouTube audio into a voice channel.

## Commands

| Command | What it does |
|---------|--------------|
| `/start url:<url>` | Joins your voice channel and plays the URL. Accepts direct radio stream URLs **and** YouTube / other [yt-dlp](https://github.com/yt-dlp/yt-dlp)-supported links (SoundCloud, Bandcamp, …). If something is already playing, it switches to the new URL. |
| `/stop` | Stops playback and leaves the channel. |

Pass **only the link** to `/start`, not the bot's previous `Now playing` message.

## Requirements

- Python 3.10+
- [`ffmpeg`](https://ffmpeg.org/) on your `PATH` (`ffmpeg -version` to check)
  - Windows: `winget install Gyan.FFmpeg`
- **Node.js 22+** for YouTube (yt-dlp solves JS challenges via Node)
- `pip install -r requirements.txt` installs `yt-dlp[default]` (includes `yt-dlp-ejs`)

## Setup

1. **Create the bot** at https://discord.com/developers/applications → *New Application* → *Bot* → copy the **token**.
2. **Invite it**: *OAuth2 → URL Generator* → scopes `bot` + `applications.commands`, permissions `Connect` + `Speak`. Open the generated URL and add the bot to your server.
3. **Configure** `.env` (git-ignored; copy from `env` if needed):
   ```
   DISCORD_TOKEN=your_real_token_here
   ```
4. **Install deps**:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate          # Windows
   # source .venv/bin/activate     # macOS / Linux
   pip install -r requirements.txt
   ```

## YouTube cookies (18+ and authenticated videos)

The bot reads a `cookies.txt` file on the server. Users still send only a URL.

### Option A — automatic (recommended on Windows)

1. Install **Firefox** and log into YouTube there.
2. Add to `.env`:
   ```
   YTDLP_COOKIES_BROWSER=firefox
   YTDLP_COOKIES_FILE=cookies.txt
   ```
3. Start the bot. It exports Firefox cookies into `cookies.txt` on startup.

**Firefox can be closed** after login. The bot plays from `cookies.txt`; it does not need the browser open during `/start`.

Re-export manually if YouTube starts failing again:
```bash
python scripts/refresh_cookies.py
```

### Option B — manual `cookies.txt`

Export `youtube.com` cookies (Netscape format) with a browser extension such as [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc), save as `cookies.txt`, and set:
```
YTDLP_COOKIES_FILE=cookies.txt
```
Do **not** set `YTDLP_COOKIES_BROWSER` if you use a manual file.

See the [yt-dlp cookie guide](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies).

### Browser support for auto-export

| Browser | Windows | macOS | Notes |
|---------|---------|-------|-------|
| **Firefox** | Yes | Yes | **Recommended on Windows** |
| Chrome / Edge / Brave | Unreliable | Varies | App-Bound Encryption often breaks auto-export on Windows; use manual `cookies.txt` instead |
| Safari | No | Yes | `YTDLP_COOKIES_BROWSER=safari` only on macOS |

### Optional `.env` tuning

```
YTDLP_COOKIES_BROWSER_PROFILE=Default
YTDLP_COOKIES_REFRESH_ON_STARTUP=true
YTDLP_COOKIES_REFRESH_ON_FAILURE=true
YTDLP_COOKIES_MAX_AGE_DAYS=21
YTDLP_JS_RUNTIMES=node
YTDLP_PLAYER_CLIENT=default,-web,-web_creator,-mweb,-web_music
```

## Stability

| Source | How long it lasts | Notes |
|--------|-------------------|-------|
| Direct radio / `.m3u8` URL | Months–years | **Most stable.** No YouTube, no cookies. |
| `cookies.txt` | Days–months | Re-export or refresh when YouTube rejects the session. |
| PO Token | Hours per video | Bot avoids clients that need them when cookies are set. |

For 24/7 radio, use a direct stream URL (e.g. SomaFM). Use YouTube for on-demand tracks.

## Run

```bash
python bot.py
```

You should see `Logged in as ... (slash commands synced)`.

## Test

1. Join a voice channel in your server.
2. `/start url:https://ice1.somafm.com/groovesalad-128-mp3` — radio stream.
3. `/start url:https://www.youtube.com/watch?v=...` — YouTube audio (title in the reply).
4. `/stop` — the bot leaves.

Tip: verify a stream with `ffplay "<url>"` before debugging the bot.

> Slash commands can take a minute to appear the first time after `tree.sync()`.

## Troubleshooting

| Error | Fix |
|-------|-----|
| `ffmpeg was not found` | Install ffmpeg and restart the terminal / bot |
| `Sign in to confirm your age` | Refresh cookies; ensure Firefox is logged into YouTube |
| `format is not available` / JS challenge | Install Node.js and `pip install "yt-dlp[default]"` |
| `Failed to decrypt with DPAPI` (Chrome) | Switch to Firefox auto-export or manual `cookies.txt` |
| Invalid URL / `Now playing: https://...` | Pass only the video URL to `/start` |
