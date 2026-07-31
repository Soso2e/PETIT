"""PETIT backend package."""

try:
    import fastapi as _fastapi  # noqa: F401
except ModuleNotFoundError:
    # Lightweight diagnostics can import backend without installing the Web app.
    pass
else:
    from . import notification_center as _notification_center

    _notification_center.install()
