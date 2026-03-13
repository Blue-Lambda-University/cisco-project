"""
Test script for WebSocket rate limiting (Token Bucket).

Rapidly sends messages to verify that the burst allowance is honoured
and subsequent messages are throttled with a -32429 error.

Usage:
    .venv/bin/python scripts/test_rate_limit.py [--url WS_URL] [--count N]

Defaults:
    url   = ws://localhost:8000/ciscoua/api/v1/ws
    count = 8
"""

import argparse
import asyncio
import json

import websockets


RATE_LIMIT_CODE = -32429

SAMPLE_MESSAGE = {
    "jsonrpc": "2.0",
    "id": "rl-test-0",
    "method": "agent/sendMessage",
    "params": {
        "sessionId": "rate-limit-test-session",
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": "rate limit test"}],
        },
        "metadata": {"conversationId": "rl-conv-001"},
    },
}


async def _recv_skip_pings(ws, timeout: float = 5.0) -> dict:
    """Read from the socket, skipping server heartbeat pings."""
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        data = json.loads(raw)
        if data.get("type") == "ping":
            continue
        return data


async def run(url: str, count: int) -> None:
    print(f"Connecting to {url} …")
    async with websockets.connect(url) as ws:
        print(f"Connected. Sending {count} messages as fast as possible.\n")

        throttled = 0
        for i in range(count):
            msg = {**SAMPLE_MESSAGE, "id": f"rl-test-{i}"}
            await ws.send(json.dumps(msg))

            resp = await _recv_skip_pings(ws)

            if "error" in resp and resp["error"].get("code") == RATE_LIMIT_CODE:
                retry_ms = resp["error"].get("data", {}).get("retryAfterMs", "?")
                print(f"  [{i}] THROTTLED  (retryAfterMs={retry_ms})")
                throttled += 1
            else:
                print(f"  [{i}] OK")

        print(f"\nDone — {throttled}/{count} messages were throttled.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test WebSocket rate limiting")
    parser.add_argument(
        "--url",
        default="ws://localhost:8000/ciscoua/api/v1/ws",
        help="WebSocket URL (default: ws://localhost:8000/ciscoua/api/v1/ws)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=8,
        help="Number of messages to send (default: 8)",
    )
    args = parser.parse_args()
    asyncio.run(run(args.url, args.count))


if __name__ == "__main__":
    main()
