#!/usr/bin/env python3
import json
import math
import os
import sys
import tempfile
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HOME = os.path.expanduser("~")
CREDENTIALS = os.path.join(HOME, ".claude", ".credentials.json")
if sys.platform == "win32":
    _cache_root = os.environ.get("LOCALAPPDATA") or os.path.join(HOME, "AppData", "Local")
else:
    _cache_root = os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache")
CACHE = os.path.join(_cache_root, "clausage", "usage.json")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"


def emit(data):
    print(json.dumps(data))
    raise SystemExit(0)


def load_cache():
    try:
        with open(CACHE) as file:
            data = json.load(file)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def stale(reason):
    data = load_cache()
    if data:
        data.update(state="stale", fresh=False, reason=reason)
        emit(normalize(data))
    emit({"state": reason, "fresh": False, "reason": reason})


def fetch_usage(token):
    request = Request(
        USAGE_URL,
        headers={
            "authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "anthropic-version": "2023-06-01",
            "user-agent": "claude-cli",
        },
    )
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def save(data):
    temporary = None
    try:
        directory = os.path.dirname(CACHE)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=directory)
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as file:
            json.dump(data, file)
        os.replace(temporary, CACHE)
        temporary = None
    except OSError:
        pass
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def limit(data, group, kind=None):
    for item in data.get("limits") or []:
        if item.get("group") == group and (kind is None or item.get("kind") == kind):
            return item
    return None


def percent(item, fallback=0):
    try:
        value = item.get("percent") if item else fallback
        return max(0, min(100, int(round(float(value or 0)))))
    except (AttributeError, TypeError, ValueError):
        return 0


def time_remaining(resets_at, now=None):
    try:
        deadline = datetime.fromisoformat(resets_at.replace("Z", "+00:00")).timestamp()
        minutes = max(0, math.ceil((deadline - (time.time() if now is None else now)) / 60))
    except (AttributeError, TypeError, ValueError):
        return "--"
    if not minutes:
        return "now"
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}h {minutes:02d}m"


def normalize(data):
    session = limit(data, "session")
    weekly = limit(data, "weekly", "weekly_all") or limit(data, "weekly")

    if not session and isinstance(data.get("five_hour"), dict):
        session = {
            "percent": data["five_hour"].get("utilization"),
            "severity": "normal",
            "resets_at": data["five_hour"].get("resets_at"),
        }
    if not weekly and isinstance(data.get("seven_day"), dict):
        weekly = {
            "percent": data["seven_day"].get("utilization"),
            "resets_at": data["seven_day"].get("resets_at"),
        }

    session_reset = (session or {}).get("resets_at")
    data["session"] = {
        "percent": percent(session),
        "severity": (session or {}).get("severity") or "normal",
        "resets_at": session_reset,
        "remaining": time_remaining(session_reset),
    }
    data["weekly"] = {
        "percent": percent(weekly),
        "resets_at": (weekly or {}).get("resets_at"),
    }
    data["display"] = {**data["session"], "kind": "session"}
    return data


def load_token():
    try:
        with open(CREDENTIALS) as file:
            token = json.load(file)["claudeAiOauth"]["accessToken"]
        return token if isinstance(token, str) and token else None
    except (KeyError, OSError, TypeError, json.JSONDecodeError):
        return None


def self_check():
    assert time_remaining("1970-01-01T03:04:00+00:00", 0) == "03h 04m"
    assert time_remaining(None, 0) == "--"
    data = normalize({"limits": [
        {"kind": "session", "group": "session", "percent": 12, "resets_at": None},
        {"kind": "weekly_all", "group": "weekly", "percent": 98, "is_active": True},
    ]})
    assert data["display"]["percent"] == 12
    print("ok")


def main():
    if "--self-check" in sys.argv:
        self_check()
        return

    token = load_token()
    if not token:
        stale("auth")

    try:
        data = fetch_usage(token)
    except HTTPError as error:
        stale("auth" if error.code in (401, 403) else "api")
    except (URLError, TimeoutError, OSError):
        stale("network")
    except (UnicodeDecodeError, json.JSONDecodeError):
        stale("api")

    if not isinstance(data, dict) or data.get("error"):
        stale("api")

    data.update(state="ok", fresh=True, fetched_at=int(time.time()))
    data = normalize(data)
    save(data)
    emit(data)


if __name__ == "__main__":
    main()
