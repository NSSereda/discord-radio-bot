"""CLI helper: export browser cookies for the Discord radio bot."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.cookie_refresh_service import CookieRefreshService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> int:
    load_dotenv()

    service = CookieRefreshService.from_env()
    if service is None:
        print(
            "Set YTDLP_COOKIES_BROWSER in .env (firefox, chrome, edge, …).",
            file=sys.stderr,
        )
        return 1

    import asyncio

    ok = asyncio.run(service.refresh())
    if not ok:
        return 1

    print(f"Cookies saved to {service.cookies_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
