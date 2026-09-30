import os
import ssl
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.calendar_sources import timetree


class TimeTreeTlsTests(unittest.TestCase):
    def test_system_bundle_is_valid_and_removed_after_export(self):
        paths = []

        def export(command, **kwargs):
            bundle = Path(kwargs["env"]["REQUESTS_CA_BUNDLE"])
            paths.append(bundle)
            context = ssl.create_default_context(cafile=str(bundle))
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
            Path(command[-1]).write_text("BEGIN:VCALENDAR\nEND:VCALENDAR", encoding="utf-8")
            return SimpleNamespace(returncode=0)

        with patch.dict(os.environ, {}, clear=True), patch.object(timetree, "configured", return_value=True), patch.object(timetree.subprocess, "run", side_effect=export):
            self.assertIn("BEGIN:VCALENDAR", timetree.fetch_ics())
        self.assertFalse(paths[0].exists())

    def test_explicit_ca_bundle_is_preserved_on_failure(self):
        def export(command, **kwargs):
            self.assertEqual(kwargs["env"]["REQUESTS_CA_BUNDLE"], "custom.pem")
            return SimpleNamespace(returncode=1)

        with patch.dict(os.environ, {"REQUESTS_CA_BUNDLE": "custom.pem"}), patch.object(timetree, "configured", return_value=True), patch.object(timetree.subprocess, "run", side_effect=export):
            with self.assertRaises(RuntimeError):
                timetree.fetch_ics()
