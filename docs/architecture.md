# Architecture

## Overview

```text
VR921 <-> SHIP/TLS/WebSocket <-> vaillant/ <-> custom_components/vaillant_eebus <-> Home Assistant
```

## Layers

- `vaillant/ship.py`: SHIP handshake and frame transport
- `vaillant/spine.py`: SPINE datagram helpers
- `vaillant/discovery.py`: entity and feature discovery
- `vaillant/measurement.py`: measurement description and value parsing
- `vaillant/client.py`: persistent session lifecycle
- `custom_components/vaillant_eebus/`: Home Assistant integration
- `scripts/daemon.py`: local development daemon with cached HTTP state

## Development flow

- Use `scripts/daemon.py` to hold a stable VR921 session
- Use `scripts/test_local.py` to capture and inspect state
- Use `tests/fixtures/measurements.jsonl` for parser tests
