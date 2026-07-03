# Developer Guide

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements_test.txt
```

## Useful commands

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
.venv/bin/python scripts/daemon.py --host 192.168.1.130
curl http://127.0.0.1:8125/scopes
```

## Local debugging

- Keep daemon running in one terminal
- Use `/state` and `/scopes` to inspect live cached data
- Use `scripts/test_local.py` for protocol-level capture summaries
