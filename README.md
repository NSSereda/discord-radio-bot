# Discord Radio Bot

A minimal Discord bot that streams internet radio and YouTube audio into a voice channel.

## Commands

| Command | What it does |
|---------|--------------|
| `/start url:<url>` | Joins your voice channel and plays the URL. Accepts direct radio stream URLs **and** YouTube / other [yt-dlp](https://github.com/yt-dlp/yt-dlp)-supported links (SoundCloud, Bandcamp, …). If something is already playing, it switches to the new URL. |
| `/stop` | Stops playback and leaves the channel. |

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
4. **Install deps**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

## Run

```bash
python bot.py
```
You should see `Logged in as ... (slash commands synced)`.

## Test

1. Join a voice channel in your server.
2. `/start url:https://ice1.somafm.com/groovesalad-128-mp3` — the bot joins and plays a radio stream.
3. `/start url:https://www.youtube.com/watch?v=...` — audio switches to the YouTube track (the reply shows its title).
4. `/stop` — the bot leaves.

Tip: verify any stream URL plays at all with `ffplay "<url>"` before debugging the bot.

> Slash commands can take a minute to appear the first time after `tree.sync()`.
