import argparse
import asyncio
import logging
import os
import re
import shutil
import sys
from urllib.parse import urlparse

import discord
import yt_dlp
from discord import app_commands
from dotenv import load_dotenv
from yt_dlp.cookies import SUPPORTED_BROWSERS

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
JS_RUNTIMES = ("deno", "node", "bun")
BUNDLED_SOLVER_RUNTIMES = ("deno", "bun")

DIRECT_STREAM_RE = re.compile(r"\.(mp3|aac|ogg|opus|m4a|flac|wav|m3u8|pls)$", re.I)
YDL_OPTS: dict = {}

def build_ydl_opts(browser: str | None) -> None:
    opts = {
        "format": "bestaudio/best",
        "noplaylist": True,  # a video inside a playlist URL -> just the video
        "quiet": True,
        "no_warnings": True,
    }
    if browser:  # None when --cookies-from-browser none was passed
        opts["cookiesfrombrowser"] = (browser,)

    runtimes = {name: {} for name in JS_RUNTIMES if shutil.which(name)}
    if runtimes:
        opts["js_runtimes"] = runtimes
        # Without a bundled solver (deno/bun), the runtime can't solve YouTube's
        # signature challenge offline; allow fetching the solver from GitHub.
        if not any(r in runtimes for r in BUNDLED_SOLVER_RUNTIMES):
            opts["remote_components"] = ["ejs:github"]
    else:
        log.warning(
            "No JavaScript runtime (deno/node/bun) found on PATH; some sites need "
            "one to extract media reliably. Install one, e.g. `brew install deno`."
        )

    global YDL_OPTS
    YDL_OPTS = opts


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
    return await loop.run_in_executor(None, _extract)

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Minimal Discord radio bot.")
    parser.add_argument(
        "--cookies-from-browser",
        default="chrome",
        metavar="BROWSER",
        help="Browser to read cookies from so yt-dlp can access content that "
             "requires sign-in or age verification (%(default)s by default). "
             "Use 'none' to disable. "
             f"Supported: {', '.join(sorted(SUPPORTED_BROWSERS))}.",
    )
    args = parser.parse_args()

    browser = args.cookies_from_browser.lower()
    if browser == "none":
        browser = None
    elif browser not in SUPPORTED_BROWSERS:
        parser.error(
            f"unsupported browser {args.cookies_from_browser!r}; choose from "
            f"{', '.join(sorted(SUPPORTED_BROWSERS))}, or 'none'"
        )

    build_ydl_opts(browser)
    log.info("Using cookies from browser: %s", browser or "none")

    client.run(TOKEN)


if __name__ == "__main__":
    main()
