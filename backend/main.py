"""PETIT application entrypoint.

Run with:  uvicorn backend.main:app --reload
or:        python -m backend.main
"""
from __future__ import annotations

from . import config
from .app import create_app

app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("backend.main:app", host=config.HOST, port=config.PORT, reload=False)


if __name__ == "__main__":
    main()
