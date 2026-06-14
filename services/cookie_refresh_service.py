"""Export YouTube session cookies from a local browser into a cookies file."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

log = logging.getLogger("radio-bot.cookie-refresh")

YOUTUBE_ROBOTS_URL = "https://www.youtube.com/robots.txt"  # legacy; refresh no longer needs a URL
SUPPORTED_BROWSERS = frozenset(
    {"brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi", "whale"}
)


@dataclass(frozen=True)
class CookieRefreshConfig:
    browser: str
    cookies_file: str
    profile: str | None = None
    refresh_on_startup: bool = True
    refresh_on_auth_failure: bool = True
    refresh_if_missing: bool = True
    refresh_if_stale: bool = True
    cookies_max_age_days: int = 21


class CookieRefreshError(Exception):
    """Browser cookies could not be exported."""


class CookieRefreshService:
    """Writes yt-dlp-compatible cookies by reading a logged-in local browser."""

    def __init__(self, config: CookieRefreshConfig) -> None:
        browser = config.browser.strip().lower()
        if browser not in SUPPORTED_BROWSERS:
            raise ValueError(
                f"Unsupported browser {config.browser!r}. "
                f"Use one of: {', '.join(sorted(SUPPORTED_BROWSERS))}"
            )

        self._config = CookieRefreshConfig(
            browser=browser,
            cookies_file=config.cookies_file,
            profile=config.profile,
            refresh_on_startup=config.refresh_on_startup,
            refresh_on_auth_failure=config.refresh_on_auth_failure,
            refresh_if_missing=config.refresh_if_missing,
            refresh_if_stale=config.refresh_if_stale,
            cookies_max_age_days=config.cookies_max_age_days,
        )
        self._cookies_path = Path(config.cookies_file).expanduser()
        self._lock = asyncio.Lock()

    @classmethod
    def from_env(
        cls,
        browser_env: str = "YTDLP_COOKIES_BROWSER",
        cookies_file_env: str = "YTDLP_COOKIES_FILE",
        profile_env: str = "YTDLP_COOKIES_BROWSER_PROFILE",
        refresh_on_startup_env: str = "YTDLP_COOKIES_REFRESH_ON_STARTUP",
        refresh_on_failure_env: str = "YTDLP_COOKIES_REFRESH_ON_FAILURE",
        cookies_max_age_env: str = "YTDLP_COOKIES_MAX_AGE_DAYS",
    ) -> CookieRefreshService | None:
        browser = os.getenv(browser_env, "").strip().lower()
        if not browser:
            return None

        cookies_file = os.getenv(cookies_file_env, "cookies.txt").strip() or "cookies.txt"
        profile = os.getenv(profile_env, "").strip() or None

        return cls(
            CookieRefreshConfig(
                browser=browser,
                cookies_file=cookies_file,
                profile=profile,
                refresh_on_startup=_env_flag(refresh_on_startup_env, default=True),
                refresh_on_auth_failure=_env_flag(refresh_on_failure_env, default=True),
                cookies_max_age_days=_env_int(cookies_max_age_env, default=21),
            )
        )

    @property
    def browser(self) -> str:
        return self._config.browser

    @property
    def cookies_path(self) -> Path:
        return self._cookies_path

    def cookies_file(self) -> str | None:
        if not self._cookies_path.is_file():
            return None
        return str(self._cookies_path.resolve())

    def _browser_tuple(self) -> tuple[str, ...]:
        if self._config.profile:
            return (self._config.browser, self._config.profile)
        return (self._config.browser,)

    def _is_stale(self) -> bool:
        if not self._cookies_path.is_file():
            return True
        if self._config.cookies_max_age_days <= 0:
            return False

        age_days = (time.time() - self._cookies_path.stat().st_mtime) / 86400
        return age_days >= self._config.cookies_max_age_days

    def should_refresh(self, *, missing: bool = False, stale: bool = False) -> bool:
        if missing and self._config.refresh_if_missing:
            return True
        if stale and self._config.refresh_if_stale:
            return True
        return False

    def _refresh_sync(self) -> None:
        self._cookies_path.parent.mkdir(parents=True, exist_ok=True)

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "cookiesfrombrowser": self._browser_tuple(),
            "cookiefile": str(self._cookies_path),
        }

        log.info(
            "Refreshing cookies from %s into %s",
            self._config.browser,
            self._cookies_path,
        )

        try:
            with yt_dlp.YoutubeDL(ydl_opts):
                pass
        except Exception as exc:
            raise CookieRefreshError(
                f"Could not read cookies from {self._config.browser}. "
                "On Windows, Chrome often fails (DPAPI / locked database). "
                "Use the 'Get cookies.txt LOCALLY' extension to export cookies.txt manually, "
                "or install Firefox, log into YouTube there, and set YTDLP_COOKIES_BROWSER=firefox."
            ) from exc

        if not self._cookies_path.is_file():
            raise CookieRefreshError(
                f"yt-dlp did not create {self._cookies_path}. "
                "Check that the browser profile is logged into YouTube."
            )

        log.info("Cookies refreshed: %s", self._cookies_path)

    async def refresh(self) -> bool:
        async with self._lock:
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, self._refresh_sync)
                return True
            except CookieRefreshError:
                log.exception("Cookie refresh failed")
                return False

    async def refresh_on_startup(self) -> bool:
        if not self._config.refresh_on_startup:
            return self._cookies_path.is_file()

        if self.should_refresh(missing=not self._cookies_path.is_file(), stale=self._is_stale()):
            return await self.refresh()

        log.info("Cookie file is present and fresh: %s", self._cookies_path)
        return True


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
