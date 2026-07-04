# Discord Radio Bot

A minimal Discord bot that streams internet radio and YouTube audio into a voice channel, with queue and playlist support.

## Commands

| Command | What it does |
|---------|--------------|
| `/play url:<url>` | Joins your voice channel and **queues** the URL. Plays immediately if nothing is playing, otherwise adds to the end of the queue. Accepts direct radio stream URLs **and** [yt-dlp](https://github.com/yt-dlp/yt-dlp)-supported links (Youtube, SoundCloud, Bandcamp, …). A **playlist URL enqueues every track**. |
| `/skip` | Skips the current track and plays the next queued one. |
| `/queue` | Shows the current track and what's queued up next. |
| `/clear` | Clears the queue (the current track keeps playing). |
| `/pause` | Pauses playback (the bot stays in the channel). |
| `/resume` | Resumes paused playback. |
| `/stop` | Stops playback, clears the queue, and leaves the channel. |

## Requirements

- Python 3.10+
- [`ffmpeg`](https://ffmpeg.org/) on your `PATH` (`ffmpeg -version` to check)

## Setup

1. **Create the bot** at https://discord.com/developers/applications → *New Application* → *Bot* → copy the **token**.
2. **Invite it**: *OAuth2 → URL Generator* → scopes `bot` + `applications.commands`, permissions `Connect` + `Speak`. Open the generated URL and add the bot to your server.
3. **Configure secrets**: put your token in `.env` (already git-ignored):
   ```
   DISCORD_TOKEN=your_real_token_here
   ```
4. **Install deps** (creates the venv and installs everything):
   ```bash
   make update
   ```
## Run

```bash
make run                  # or: python bot.py
```

### Playing content that needs sign-in or age verification

By default the bot reads cookies from **Chrome** so yt-dlp can access content gated behind sign-in or age verification. The browser must be signed in to an account that can view that content. Override the browser, or disable cookies entirely, with `--cookies-from-browser`:

```bash
make run BROWSER=firefox   # use Firefox's cookies
make run BROWSER=none       # no cookies
# equivalently: python bot.py --cookies-from-browser firefox
```

Supported: `brave, chrome, chromium, edge, opera, vivaldi, whale, firefox, safari`.

> macOS note: Chrome triggers a one-time Keychain prompt on first cookie read (grant "Always Allow"); **Firefox** avoids it; **Safari** needs Full Disk Access for your terminal.

## Test

1. Join a voice channel in your server.
2. `/play url:https://ice1.somafm.com/groovesalad-128-mp3` — the bot joins and plays a radio stream.
3. `/play url:https://www.youtube.com/watch?v=...` — the YouTube track is queued behind the current one; `/queue` shows both.
4. `/skip` — advances to the next queued track.
5. `/play url:<playlist URL>` — every track in the playlist is added to the queue.
6. `/stop` — the bot clears the queue and leaves.

Tip: verify any stream URL plays at all with `ffplay "<url>"` before debugging the bot.