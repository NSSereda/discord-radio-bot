import argparse
import asyncio
import logging
import os
import re
import shutil
import sys
from collections import deque
from dataclasses import dataclass, field
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

# Single-video opts, used at play time to get a real (expiring) stream URL.
YDL_OPTS: dict = {}
# Playlist-aware opts, used only to expand a playlist URL into lightweight
# entries (webpage URL + title) without resolving each track's stream.
YDL_FLAT_OPTS: dict = {}

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

    global YDL_OPTS, YDL_FLAT_OPTS
    YDL_OPTS = opts
    YDL_FLAT_OPTS = {**opts, "noplaylist": False, "extract_flat": "in_playlist"}


@dataclass
class QueueItem:
    source_url: str # what to resolve at play time (webpage URL or direct stream)
    title: str | None = None
    is_direct: bool = False  # direct stream needs no yt-dlp resolution


async def resolve_entries(url: str) -> list[QueueItem]:
    if DIRECT_STREAM_RE.search(urlparse(url).path):
        return [QueueItem(url, url, is_direct=True)]

    def _extract() -> list[QueueItem]:
        with yt_dlp.YoutubeDL(YDL_FLAT_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)

        entries = info.get("entries") if isinstance(info, dict) else None
        if entries:  # a playlist -> one item per entry
            items = []
            for entry in entries:
                if not entry:
                    continue
                items.append(
                    QueueItem(entry.get("url", url), entry.get("title"))
                )
            return items or [QueueItem(url, info.get("title"))]
        
        return [QueueItem(url, info.get("title"))]

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _extract)


async def resolve_stream(item: QueueItem) -> tuple[str, str]:
    if item.is_direct:
        return item.source_url, item.title or item.source_url

    def _extract() -> tuple[str, str]:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(item.source_url, download=False)
            if "entries" in info:  # search result
                info = info["entries"][0]
            return info["url"], info.get("title", item.source_url)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _extract)

intents = discord.Intents.default()  # slash commands need no privileged intents
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

@dataclass
class GuildState:
    queue: deque[QueueItem] = field(default_factory=deque)
    current: QueueItem | None = None
    text_channel: discord.abc.Messageable | None = None


guild_states: dict[int, GuildState] = {}

def _state_for(guild: discord.Guild) -> GuildState:
    return guild_states.setdefault(guild.id, GuildState())


@client.event
async def on_ready():
    await tree.sync()
    log.info("Logged in as %s (slash commands synced)", client.user)


async def _play_next(guild: discord.Guild) -> None:
    vc = guild.voice_client
    if vc is None or not vc.is_connected():  # gone (e.g. via /stop)
        return

    state = _state_for(guild)
    channel = state.text_channel
    if not state.queue:
        state.current = None
        await vc.disconnect()
        guild_states.pop(guild.id, None)

        if channel is not None:
            await channel.send("📻 Queue finished — leaving the channel.")

        return

    item = state.queue.popleft()
    state.current = item
    try:
        stream_url, title = await resolve_stream(item)
    except Exception as exc:
        log.exception("Failed to resolve queued item %s", item.source_url)
        if channel is not None:
            label = item.title or item.source_url
            await channel.send(f"⚠️ Skipping (couldn't resolve): {label} — {exc}")
        await _play_next(guild)  # move on to the next track
        return

    item.title = title

    def _after(error, guild=guild):
        asyncio.run_coroutine_threadsafe(_advance(guild, error), client.loop)

    vc.play(discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTS), after=_after)
    if channel is not None:
        await channel.send(f"▶️ Now playing: {title}")


async def _advance(guild: discord.Guild, error) -> None:
    if error is not None:
        log.error("Playback error: %s", error)

        state = guild_states.get(guild.id)
        if state is not None and state.text_channel is not None:
            await state.text_channel.send(f"⚠️ Playback error: {error}")

    await _play_next(guild)

@tree.command(name="play", description="Queue audio by URL (playlists add every track).")
@app_commands.describe(url="The URL to play or queue")
async def play(interaction: discord.Interaction, url: str):
    # Connecting to voice can take longer than Discord's 3s ack window, so defer.
    await interaction.response.defer()

    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.followup.send("Join a voice channel first.", ephemeral=True)
        return

    channel = interaction.user.voice.channel
    guild = interaction.guild
    vc = guild.voice_client

    try:
        if vc is None:
            vc = await channel.connect()
        elif vc.channel != channel:
            await vc.move_to(channel)

        items = await resolve_entries(url)
    except Exception as exc:
        log.exception("Failed to queue URL")
        await interaction.followup.send(f"Couldn't queue that URL: {exc}", ephemeral=True)
        return

    if not items:
        await interaction.followup.send("Nothing playable found at that URL.", ephemeral=True)
        return

    state = _state_for(guild)
    state.text_channel = interaction.channel
    idle = not vc.is_playing() and not vc.is_paused()
    state.queue.extend(items)

    if idle:
        # _play_next posts the "Now playing" message itself.
        await _play_next(guild)

        await interaction.followup.send(
            f"📻 Started playback ({len(items)} track(s) queued)."
            if len(items) > 1
            else "📻 Started playback."
        )
    elif len(items) > 1:
        await interaction.followup.send(f"➕ Queued {len(items)} tracks.")
    else:
        label = items[0].title or url
        await interaction.followup.send(
            f"➕ Queued: {label} (position {len(state.queue)})."
        )


@tree.command(name="stop", description="Stop playback, clear the queue, and leave.")
async def stop(interaction: discord.Interaction):
    guild = interaction.guild
    vc = guild.voice_client
    if vc is None:
        await interaction.response.send_message("Not playing anything.", ephemeral=True)
        return

    # Clear state before disconnecting so the resulting `after` callback finds
    # an empty queue + disconnected client and does not restart playback.
    guild_states.pop(guild.id, None)
    await vc.disconnect()
    await interaction.response.send_message("⏹️ Stopped.")


@tree.command(name="skip", description="Skip the current track.")
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc is None or not (vc.is_playing() or vc.is_paused()):
        await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        return

    vc.stop()  # the `after` callback advances to the next queued track
    await interaction.response.send_message("⏭️ Skipped.")


@tree.command(name="queue", description="Show the current track and what's queued next.")
async def queue(interaction: discord.Interaction):
    state = guild_states.get(interaction.guild.id)
    if state is None or (state.current is None and not state.queue):
        await interaction.response.send_message("Queue is empty.", ephemeral=True)
        return

    lines = []
    if state.current is not None:
        lines.append(f"▶️ Now playing: {state.current.title or state.current.source_url}")

    upcoming = list(state.queue)
    shown = upcoming[:10]
    for i, item in enumerate(shown, start=1):
        lines.append(f"{i}. {item.title or item.source_url}")
    if len(upcoming) > len(shown):
        lines.append(f"…and {len(upcoming) - len(shown)} more.")
    elif not upcoming:
        lines.append("(nothing queued up next)")

    await interaction.response.send_message("\n".join(lines))


@tree.command(name="clear", description="Clear the queue (keeps the current track playing).")
async def clear(interaction: discord.Interaction):
    state = guild_states.get(interaction.guild.id)
    if state is None or not state.queue:
        await interaction.response.send_message("Queue is already empty.", ephemeral=True)
        return

    count = len(state.queue)
    state.queue.clear()
    await interaction.response.send_message(f"🗑️ Cleared {count} queued track(s).")


@tree.command(name="pause", description="Pause playback.")
async def pause(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc is None or not vc.is_playing():
        await interaction.response.send_message("Nothing is playing.", ephemeral=True)
        return
    if vc.is_paused():
        await interaction.response.send_message("Already paused.", ephemeral=True)
        return

    vc.pause()
    await interaction.response.send_message("⏸️ Paused.")


@tree.command(name="resume", description="Resume paused playback.")
async def resume(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc is None:
        await interaction.response.send_message("Not connected.", ephemeral=True)
        return
    if not vc.is_paused():
        await interaction.response.send_message("Nothing is paused.", ephemeral=True)
        return

    vc.resume()
    await interaction.response.send_message("▶️ Resumed.")


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
