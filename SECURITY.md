# Security

Use GitHub's private vulnerability reporting for security issues. Do not open a public issue containing access tokens, credential files, cache contents, or other secrets.

Clausage must keep `~/.claude/.credentials.json` read-only. Changes that log, persist, transmit elsewhere, or expose Claude Code tokens in process arguments or environment variables will not be accepted.
