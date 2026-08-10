import io
import json
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import usage


class UsageTests(unittest.TestCase):
    def test_five_hour_usage_is_always_the_display_value(self):
        data = usage.normalize({"limits": [
            {"kind": "session", "group": "session", "percent": 12},
            {"kind": "weekly_all", "group": "weekly", "percent": 98, "is_active": True},
        ]})
        self.assertEqual(data["display"]["percent"], 12)
        self.assertEqual(data["weekly"]["percent"], 98)

    def test_legacy_response_and_reset_countdown(self):
        data = usage.normalize({
            "five_hour": {"utilization": 34, "resets_at": "1970-01-01T03:04:00+00:00"},
            "seven_day": {"utilization": 56},
        })
        self.assertEqual(data["session"]["percent"], 34)
        self.assertEqual(data["weekly"]["percent"], 56)
        self.assertEqual(usage.time_remaining(data["session"]["resets_at"], 0), "03h 04m")

    def test_invalid_percentages_are_safe(self):
        self.assertEqual(usage.percent({"percent": -10}), 0)
        self.assertEqual(usage.percent({"percent": 150}), 100)
        self.assertEqual(usage.percent({"percent": "invalid"}), 0)

    def test_malformed_cache_and_credentials_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory, "cache.json")
            credentials = Path(directory, "credentials.json")
            cache.write_text("[]")
            credentials.write_text(json.dumps({"claudeAiOauth": {"accessToken": ""}}))
            with patch.object(usage, "CACHE", str(cache)), patch.object(usage, "CREDENTIALS", str(credentials)):
                self.assertIsNone(usage.load_cache())
                self.assertIsNone(usage.load_token())

    def test_network_failure_uses_cached_values(self):
        cached = {"five_hour": {"utilization": 41}, "seven_day": {"utilization": 22}}
        output = io.StringIO()
        with patch.object(usage, "load_cache", return_value=cached), redirect_stdout(output):
            with self.assertRaises(SystemExit):
                usage.stale("network")
        data = json.loads(output.getvalue())
        self.assertEqual(data["state"], "stale")
        self.assertEqual(data["reason"], "network")
        self.assertEqual(data["session"]["percent"], 41)

    def test_cache_file_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory, "cache", "usage.json")
            with patch.object(usage, "CACHE", str(cache)):
                usage.save({"state": "ok"})
            self.assertEqual(stat.S_IMODE(cache.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
