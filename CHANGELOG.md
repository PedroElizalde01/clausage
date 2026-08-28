# Changelog

## 1.1.0 — 2026-08-27

- Add a Windows 10 system tray indicator (`tray.py`) with the same ring, usage bars, and console-style panel as the GNOME extension.
- Poll every five minutes and back off after a failure, doubling up to one hour and honouring `Retry-After`. The previous fixed 60-second retry meant a single rate-limited response could keep the indicator frozen indefinitely.
- Show `--%` rather than a cached percentage once that window has reset. Usage returns to zero at rollover, so the stored figure is known to be wrong, not merely old.
- Draw stale readings with a grey ring and report how old the cache is, so cached data is never mistaken for live data.
- Name the actual problem in the status line: `RATE LIMITED`, `AUTH EXPIRED`, `OFFLINE`, or `API ERROR`, instead of reporting every failure as a network error.
- Skip requests that would carry an access token already past its expiry.
- Fix the Windows startup launcher writing a hardcoded path, which registered a launcher that could only work on the author's machine.
- Keep polling alive when a refresh raises an unexpected error, instead of losing the timer for the rest of the session.

## 1.0.4 — 2026-08-10

- Match the refresh action to the console UI and show its running state.

## 1.0.3 — 2026-08-10

- Add spacing between each progress meter and its percentage.

## 1.0.2 — 2026-08-10

- Replace compact ASCII meters with labeled 20-column block progress bars.

## 1.0.1 — 2026-08-10

- Keep the usage menu open when refreshing.

## 1.0.0 — 2026-08-10

- Show five-hour usage permanently in the GNOME top bar.
- Add a console-style menu with five-hour and weekly usage.
- Add the five-hour reset countdown and offline cache.
- Keep Claude Code credentials read-only and tokens out of process arguments.
