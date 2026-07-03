# Troubleshooting

## Repeated trust prompts

Use `scripts/daemon.py` so one session stays alive while you restart wrappers.

## Double connection

VR921 may close with code `4201 Double connection` when another session is still open.
Stop old daemon/test processes first.

## No values for described scopes

Some scopes are described by VR921 but do not currently produce values through the implemented measurement path.
Use poll fallback and inspect `/scopes`.

## mDNS name collision

Service registration now allows name changes automatically. If discovery still behaves oddly, stop duplicate local processes.
