"""Resolve playable audio stream URLs from user-provided links."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp

from services.cookie_refresh_service import CookieRefreshService

log = logging.getLogger("radio-bot.audio-resolver")

DIRECT_STREAM_RE = re.compile(r"\.(mp3|aac|ogg|opus|m4a|flac|wav|m3u8|pls)$", re.I)
YOUTUBE_RE = re.compile(r"(youtube\.com|youtu\.be|music\.youtube\.com)", re.I)
URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>\"']+", re.I)

# With cookies: yt-dlp defaults minus PO-Token clients; still auto-adds tv_embedded for 18+.
# See https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide
_WITH_COOKIES_CLIENTS = "default,-web,-web_creator,-mweb,-web_music"
_WITHOUT_COOKIES_CLIENTS = "android_vr"


class StreamResolutionError(Exception):
    """yt-dlp could not produce a playable stream URL."""


@dataclass(frozen=True)
class ResolvedStream:
    stream_url: str
    title: str


@dataclass(frozen=True)
class ResolverConfig:
    cookies_file: str | None = None
    player_client: str | None = None
    cookies_max_age_days: int = 21


class AudioResolverService:
    """Turns a user URL into a direct audio stream URL via yt-dlp."""

    def __init__(
        self,
        config: ResolverConfig | None = None,
        cookie_refresh: CookieRefreshService | None = None,
    ) -> None:
        self._config = config or ResolverConfig()
        self._cookie_refresh = cookie_refresh
        self._cookies_file = self._resolve_cookies_file()
        self._player_client = self._resolve_player_client()
        self._warn_if_cookies_stale()

        if self._cookie_refresh:
            log.info(
                "Automatic cookie refresh enabled via browser: %s",
                self._cookie_refresh.browser,
            )
        elif self._cookies_file:
            log.info("yt-dlp cookies enabled: %s", self._cookies_file)
        log.info("yt-dlp player_client: %s", self._player_client)

    @classmethod
    def from_env(
        cls,
        cookies_env: str = "YTDLP_COOKIES_FILE",
        player_client_env: str = "YTDLP_PLAYER_CLIENT",
        cookies_max_age_env: str = "YTDLP_COOKIES_MAX_AGE_DAYS",
    ) -> AudioResolverService:
        cookie_refresh = CookieRefreshService.from_env(cookies_max_age_env=cookies_max_age_env)
        cookies_value = os.getenv(cookies_env, "").strip() or None

        if cookie_refresh is not None and cookies_value is None:
            cookies_value = str(cookie_refresh.cookies_path)

        player_client = os.getenv(player_client_env, "").strip() or None
        cookies_max_age_days = _env_int(cookies_max_age_env, default=21)

        return cls(
            ResolverConfig(
                cookies_file=cookies_value,
                player_client=player_client,
                cookies_max_age_days=cookies_max_age_days,
            ),
            cookie_refresh=cookie_refresh,
        )

    def _resolve_cookies_file(self) -> str | None:
        if self._cookie_refresh is not None:
            existing = self._cookie_refresh.cookies_file()
            if existing:
                return existing

            configured = str(self._cookie_refresh.cookies_path.resolve())
            if self._config.cookies_file:
                configured = str(Path(self._config.cookies_file).expanduser().resolve())
            return configured

        return self._normalize_existing_cookies_path(self._config.cookies_file)

    def _resolve_player_client(self) -> str:
        if self._config.player_client:
            return self._config.player_client
        if self._cookies_file or self._cookie_refresh is not None:
            return _WITH_COOKIES_CLIENTS
        return _WITHOUT_COOKIES_CLIENTS

    def _player_client_list(self) -> list[str]:
        return [client.strip() for client in self._player_client.split(",") if client.strip()]

    def _build_ydl_opts(self) -> dict:
        opts = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "js_runtimes": _resolve_js_runtimes(),
            "extractor_args": {
                "youtube": {
                    "player_client": self._player_client_list(),
                },
            },
        }
        cookies_file = self._resolve_cookies_file()
        if cookies_file and Path(cookies_file).is_file():
            opts["cookiefile"] = cookies_file
        return opts

    @staticmethod
    def _normalize_existing_cookies_path(cookies_file: str | None) -> str | None:
        if not cookies_file:
            return None

        path = Path(cookies_file).expanduser()
        if not path.is_file():
            log.warning("YTDLP_COOKIES_FILE not found: %s", path)
            return None

        return str(path.resolve())

    def _warn_if_cookies_stale(self) -> None:
        cookies_file = self._resolve_cookies_file()
        if not cookies_file or self._config.cookies_max_age_days <= 0:
            return
        if not Path(cookies_file).is_file():
            return

        age_days = (time.time() - Path(cookies_file).stat().st_mtime) / 86400
        if age_days < self._config.cookies_max_age_days:
            return

        if self._cookie_refresh is not None:
            log.warning(
                "cookies file is %.0f days old (limit %d); automatic refresh will run when needed.",
                age_days,
                self._config.cookies_max_age_days,
            )
            return

        log.warning(
            "cookies.txt is %.0f days old (limit %d). "
            "Re-export from the browser if YouTube links start failing.",
            age_days,
            self._config.cookies_max_age_days,
        )

    async def prepare(self) -> None:
        if self._cookie_refresh is None:
            return

        refreshed = await self._cookie_refresh.refresh_on_startup()
        if refreshed:
            self._cookies_file = self._resolve_cookies_file()

    @staticmethod
    def _normalize_input_url(url: str) -> str:
        cleaned = url.strip()
        if cleaned.startswith("<") and cleaned.endswith(">"):
            cleaned = cleaned[1:-1].strip()

        parsed = urlparse(cleaned)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return cleaned

        match = URL_IN_TEXT_RE.search(cleaned)
        if match:
            extracted = match.group(0).rstrip(".,);]")
            log.info("Extracted URL from input: %s", extracted)
            return extracted

        raise StreamResolutionError(
            "That does not look like a valid URL. Use /start with a direct link, "
            "not the bot's \"Now playing\" message."
        )

    @staticmethod
    def _is_direct_stream(url: str) -> bool:
        return bool(DIRECT_STREAM_RE.search(urlparse(url).path))

    @staticmethod
    def _is_youtube(url: str) -> bool:
        return bool(YOUTUBE_RE.search(url))

    @staticmethod
    def _looks_like_auth_failure(exc: Exception) -> bool:
        message = str(exc).lower()
        return any(
            token in message
            for token in ("sign in", "age", "confirm your age", "login", "cookies")
        )

    def _extract_sync(self, url: str) -> ResolvedStream:
        with yt_dlp.YoutubeDL(self._build_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)

        if info is None:
            raise StreamResolutionError(f"No media found at {url}")

        if "entries" in info:
            entries = info["entries"]
            if not entries:
                raise StreamResolutionError(f"No media found at {url}")
            info = entries[0]

        if info is None:
            raise StreamResolutionError(f"No media found at {url}")

        stream_url = info.get("url")
        if not stream_url:
            raise StreamResolutionError(f"No stream URL in metadata for {url}")

        return ResolvedStream(stream_url=stream_url, title=info.get("title") or url)

    def _hint_for_error(self, url: str, exc: Exception) -> str:
        message = str(exc).lower()
        cookies_file = self._resolve_cookies_file()
        has_cookies = bool(cookies_file) and Path(cookies_file).is_file()

        if "not a valid url" in message or "unsupported url" in message:
            return (
                "Paste only the video link into /start, not the bot's "
                "\"Now playing\" message."
            )

        if "sign in" in message or "age" in message or "confirm your age" in message:
            if self._cookie_refresh is not None:
                return (
                    "YouTube rejected the session. Close Chrome/Edge (if used), stay logged in "
                    "to YouTube in the configured browser, then retry or run "
                    "python scripts/refresh_cookies.py."
                )
            if has_cookies:
                return (
                    "YouTube rejected the session. Re-export cookies.txt from a logged-in "
                    "browser (incognito method) and restart the bot."
                )
            return (
                "This YouTube video is age-restricted. Set YTDLP_COOKIES_BROWSER or "
                "YTDLP_COOKIES_FILE in .env and restart the bot."
            )

        if "403" in message or "po token" in message or "gvs" in message:
            return (
                "YouTube blocked the stream request. Cookies last longer than PO Tokens; "
                "keep the default YTDLP_PLAYER_CLIENT (default,-web,-web_creator,…) "
                "when cookies are configured."
            )

        if (
            "format is not available" in message
            or "javascript runtime" in message
            or "challenge solving failed" in message
            or "only images are available" in message
        ):
            return (
                "YouTube needs a JavaScript runtime for extraction. "
                "Install Node.js and pip install \"yt-dlp[default]\", "
                "or set YTDLP_JS_RUNTIMES=node in .env."
            )

        if self._is_youtube(url) and not has_cookies:
            return (
                "Configure YTDLP_COOKIES_BROWSER for automatic cookies, "
                "or YTDLP_COOKIES_FILE for a manual cookies.txt."
            )

        return "Check that the URL plays in a browser or with yt-dlp on the server."

    async def _try_refresh_cookies(self) -> bool:
        if self._cookie_refresh is None or not self._cookie_refresh._config.refresh_on_auth_failure:
            return False

        refreshed = await self._cookie_refresh.refresh()
        if refreshed:
            self._cookies_file = self._resolve_cookies_file()
        return refreshed

    async def resolve(self, url: str) -> ResolvedStream:
        url = self._normalize_input_url(url)

        if self._is_direct_stream(url):
            return ResolvedStream(stream_url=url, title=url)

        loop = asyncio.get_running_loop()
        retried = False

        while True:
            try:
                return await loop.run_in_executor(None, self._extract_sync, url)
            except Exception as exc:
                if (
                    self._is_youtube(url)
                    and not retried
                    and self._looks_like_auth_failure(exc)
                    and await self._try_refresh_cookies()
                ):
                    retried = True
                    continue

                if self._is_youtube(url):
                    hint = self._hint_for_error(url, exc)
                    raise StreamResolutionError(f"{exc}. {hint}") from exc

                log.warning(
                    "yt-dlp couldn't resolve %s (%s); falling back to direct stream",
                    url,
                    exc,
                )
                return ResolvedStream(stream_url=url, title=url)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _resolve_js_runtimes() -> dict[str, dict]:
    raw = os.getenv("YTDLP_JS_RUNTIMES", "node").strip() or "node"
    runtimes: dict[str, dict] = {}
    for name in raw.split(","):
        runtime = name.strip()
        if runtime:
            runtimes[runtime] = {}
    return runtimes or {"node": {}}
