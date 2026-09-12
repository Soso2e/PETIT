"""Create/refresh the OAuth token used by optional Google Calendar push sync."""
from __future__ import annotations

from backend.google_calendar_push import load_credentials, token_file


def main() -> None:
    load_credentials(allow_interactive=True)
    print(f"Google Calendar OAuth token saved: {token_file()}")


if __name__ == "__main__":
    main()
