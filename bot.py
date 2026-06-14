"""Minimal Discord radio bot.

Two slash commands:
  /start url:<stream-url>  -- join the caller's voice channel and play the URL
  /stop                   -- stop playback and leave the channel
"""

import logging
import os
import sys

import discord
from discord import app_commands
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("radio-bot")

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
if not TOKEN or TOKEN == "your_bot_token_here":
    sys.exit("DISCORD_TOKEN is missing. Set a real token in your .env file.")

# ffmpeg reads the stream URL and decodes it. Reconnect flags keep long-running
# radio streams alive if the connection hiccups: retry up to 3 times (then give
# up with an error), waiting at most 5s between attempts. -vn drops any video track.
FFMPEG_OPTS = {
    "before_options": (
        "-reconnect 1 -reconnect_streamed 1 "
        "-reconnect_max_retries 3 -reconnect_delay_max 5"
    ),
    "options": "-vn",
}

intents = discord.Intents.default()  # slash commands need no privileged intents
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@client.event
async def on_ready():
    await tree.sync()
    log.info("Logged in as %s (slash commands synced)", client.user)


@tree.command(name="start", description="Play an internet radio stream by URL.")
@app_commands.describe(url="Direct stream URL (e.g. an .mp3/.aac/.ogg radio stream)")
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

        if vc.is_playing():
            vc.stop()  # switch: drop the current stream, start the new one

        vc.play(discord.FFmpegPCMAudio(url, **FFMPEG_OPTS))
    except Exception as exc:  # noqa: BLE001 - report any failure back to the user
        log.exception("Failed to start playback")
        await interaction.followup.send(f"Couldn't play that stream: {exc}", ephemeral=True)
        return

    await interaction.followup.send(f"📻 Now playing: {url}")


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
