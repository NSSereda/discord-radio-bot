"""Minimal Discord radio bot.

Two slash commands:
  /start url:<url>  -- join the caller's voice channel and play the URL
  /stop             -- stop playback and leave the channel
"""

import asyncio
import logging
import os
import re
import sys
from urllib.parse import urlparse

import discord
import yt_dlp
from discord import app_commands
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("radio-bot")

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
if not TOKEN or TOKEN == "your_bot_token_here":
    sys.exit("DISCORD_TOKEN is missing. Set a real token in your .env file.")

FFMPEG_OPTS = {
    "before_options": (
        "-reconnect 1 -reconnect_streamed 1 "
        "-reconnect_max_retries 3 -reconnect_delay_max 5"
    ),
    "options": "-vn",
}

YDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,  # a video inside a playlist URL -> just the video
    "quiet": True,
    "no_warnings": True,
}

DIRECT_STREAM_RE = re.compile(r"\.(mp3|aac|ogg|opus|m4a|flac|wav|m3u8|pls)$", re.I)

async def resolve_audio(url: str) -> tuple[str, str]:
    if DIRECT_STREAM_RE.search(urlparse(url).path):
        return url, url

    def _extract() -> tuple[str, str]:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
            if "entries" in info:  # playlist/search result
                info = info["entries"][0]
            return info["url"], info.get("title", url)

    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _extract)
    except Exception:
        log.warning("yt-dlp couldn't resolve %s; falling back to direct stream", url)
        return url, url

intents = discord.Intents.default()  # slash commands need no privileged intents
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

@client.event
async def on_ready():
    await tree.sync()
    log.info("Logged in as %s (slash commands synced)", client.user)

@tree.command(name="start", description="Play audio by URL.")
@app_commands.describe(url="The URL to play")
async def start(interaction: discord.Interaction, url: str):
    # Connecting to voice can take longer than Discord's 3s ack window, so defer.
    await interaction.response.defer()

    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.followup.send("Join a voice channel first.", ephemeral=True)
        return

    channel = interaction.user.voice.channel
    vc = interaction.guild.voice_client

    try:
        if vc is None:
            vc = await channel.connect()
        elif vc.channel != channel:
            await vc.move_to(channel)

        stream_url, title = await resolve_audio(url)

        if vc.is_playing():
            vc.stop()  # switch: drop the current stream, start the new one

        vc.play(discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTS))
    except Exception as exc:
        log.exception("Failed to start playback")
        await interaction.followup.send(f"Couldn't play that stream: {exc}", ephemeral=True)
        return

    await interaction.followup.send(f"📻 Now playing: {title}")


@tree.command(name="stop", description="Stop playback and leave the voice channel.")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc is None:
        await interaction.response.send_message("Not playing anything.", ephemeral=True)
        return

    await vc.disconnect()
    await interaction.response.send_message("⏹️ Stopped.")


if __name__ == "__main__":
    client.run(TOKEN)
