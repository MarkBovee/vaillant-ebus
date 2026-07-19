# ebusd TCP Transport

## Requirements

1. Connect to ebusd via TCP (plain text, port 8888 default)
2. Send commands: `f` (find all), `r` (read), `write -c` (write), `i` (info), `s` (signal)
3. Receive line-delimited text responses
4. Parse responses: single value, semicolon-separated multi-field, "ERR: ...", "done"
5. Connection lifecycle: connect, disconnect, reconnect with exponential backoff (1s-60s)
6. Thread-safe: asyncio lock per connection

## Implementation

```python
class EbusdTcpBackend(Backend):
    async def connect(self, host: str, port: int)
    async def disconnect(self)
    async def find(self) -> list[Register]
    async def read(self, circuit: str, name: str) -> str
    async def write(self, circuit: str, name: str, value: str) -> WriteResult
    async def info(self) -> str
    async def signal(self) -> str
```

## Command reference

| Send | Receive |
|------|---------|
| `f\n` | `Circuit Name = value\n` (362 lines) |
| `r <c> <n>\n` | `value` or `ERR: element not found` |
| `write -c <c> <n> <v>\n` | `done` or `ERR: ...` |
| `i\n` | `version: ebusd 26.1.26.1` |
| `s\n` | `signal acquired, ...` |

## Edge cases
- Connection refused → retry after backoff
- Connection lost mid-command → reconnect, resend
- Partial read → wait for `\n`
- Malformed response → ignore, log DEBUG
- Empty response → retry once
