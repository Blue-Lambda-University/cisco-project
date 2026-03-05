#!/usr/bin/env python3
"""
Manual test: connect with cdca2 subprotocol and verify server returns it.
Run with server up: uv run python scripts/test_cdca2_handshake.py
"""
import asyncio
import sys

try:
    import websockets
except ImportError:
    print("Install websockets: uv add websockets  (or pip install websockets)")
    sys.exit(1)


async def test_cdca2(uri: str = "ws://127.0.0.1:8000/ciscoua/api/v1/ws"):
    """Connect with cdca2 (and optional token); print response subprotocol."""
    subprotocols = ["cdca2", "token-eyJraWQiOlitUkXPL"]
    print(f"Connecting to {uri} with subprotocols: {subprotocols}")
    async with websockets.connect(
        uri,
        subprotocols=subprotocols,
        close_timeout=2,
    ) as ws:
        # Server's selected subprotocol is on the response
        selected = ws.subprotocol
        print(f"Server selected subprotocol: {selected!r}")
        if selected == "cdca2":
            print("OK: cdca2 was returned in response.")
        else:
            print(f"FAIL: expected 'cdca2', got {selected!r}")
        return selected == "cdca2"


if __name__ == "__main__":
    uri = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8000/ciscoua/api/v1/ws"
    ok = asyncio.run(test_cdca2(uri))
    sys.exit(0 if ok else 1)
