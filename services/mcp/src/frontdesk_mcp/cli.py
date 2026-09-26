"""`frontdesk-mcp serve`."""

from __future__ import annotations

import argparse

from .config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="frontdesk-mcp")
    parser.add_argument("command", choices=["serve"])
    parser.parse_args()
    import uvicorn

    settings = get_settings()
    uvicorn.run("frontdesk_mcp.server:create_app", factory=True, host=settings.host, port=settings.port,
                log_config=None)


if __name__ == "__main__":
    main()
