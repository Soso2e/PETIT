"""Restart control shared by the managed Core worker and its admin API."""
from threading import Event
from uuid import uuid4

instance = uuid4().hex
managed = False
development_mode = False
requested = Event()
