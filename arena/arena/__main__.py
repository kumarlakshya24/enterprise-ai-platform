"""python -m arena serves the demo. python -m arena.cli runs the bench."""

from __future__ import annotations

import uvicorn

from arena.app import create_app
from arena.settings import Settings


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
