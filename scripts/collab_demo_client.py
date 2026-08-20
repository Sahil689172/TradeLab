"""Terminal client for a TradeLab collaborative room.

Open two terminals with different ``--user`` values to see the shared chat,
shared paper portfolio, and grounded AI assistant working between two people.

    python scripts/collab_demo_client.py --room <ROOM_ID> --user sahil

Commands inside the client:

    <text>                        send a chat message
    @ai <question>                ask the grounded assistant
    /buy RELIANCE 10              place a paper order on the shared book
    /sell RELIANCE 10
    /idea RELIANCE LONG <thesis>  post a structured trade idea
    /history                      reload recent messages
    /quit
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

try:
    import websockets
except ImportError:  # pragma: no cover - demo script only
    print("This demo needs the websockets package: pip install websockets")
    raise SystemExit(1)


RESET = "\033[0m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"


def render(frame: dict) -> None:
    """Print one server frame in a readable form."""
    kind = frame.get("type")
    data = frame.get("data") or {}

    if kind == "history":
        messages = data.get("messages", [])
        print(f"{DIM}--- {len(messages)} earlier messages ---{RESET}")
        for message in messages:
            render({"type": "message", "data": message})
        print(f"{DIM}--- end of history ---{RESET}")

    elif kind == "message":
        author = data.get("author", "?")
        text = data.get("text", "")
        message_kind = data.get("kind")
        if message_kind == "AI_REPLY":
            tools = ", ".join(data.get("ai_tools_used") or []) or "no tools"
            source = data.get("ai_source", "?")
            print(f"{CYAN}[AI/{source}]{RESET} {text}")
            print(f"{DIM}       grounded via: {tools}{RESET}")
        elif message_kind == "ORDER_EVENT":
            accepted = (data.get("metadata") or {}).get("accepted")
            colour = GREEN if accepted else RED
            print(f"{colour}[order]{RESET} {text}")
        elif message_kind == "TRADE_IDEA":
            idea = data.get("trade_idea") or {}
            price = idea.get("price_at_post")
            stamp = f" (price at post: {price})" if price else ""
            print(f"{YELLOW}[idea]{RESET} {author}: {text}{stamp}")
        elif message_kind == "SYSTEM":
            print(f"{DIM}[system] {text}{RESET}")
        else:
            print(f"{GREEN}{author}{RESET}: {text}")

    elif kind == "portfolio":
        kpis = data.get("kpis") or {}
        positions = data.get("positions") or []
        print(
            f"{DIM}[portfolio] cash={kpis.get('available_cash', 0):,.0f} "
            f"value={kpis.get('current_value', 0):,.0f} "
            f"unrealised={kpis.get('unrealized_pnl', 0):,.0f} "
            f"positions={len(positions)}{RESET}",
        )

    elif kind == "presence":
        members = ", ".join(data.get("online_members") or [])
        print(f"{DIM}[presence] online: {members}{RESET}")

    elif kind == "ai_thinking":
        print(f"{DIM}[ai] thinking...{RESET}")

    elif kind == "error":
        print(f"{RED}[error]{RESET} {data.get('message')}")


def parse_command(line: str) -> dict | None:
    """Translate a typed line into an outbound websocket frame."""
    line = line.strip()
    if not line:
        return None

    if not line.startswith("/"):
        return {"type": "chat", "text": line}

    parts = line.split()
    command = parts[0].lower()

    if command in {"/buy", "/sell"} and len(parts) >= 3:
        return {
            "type": "order",
            "order": {
                "author": "placeholder",  # server overrides with the socket user
                "side": "BUY" if command == "/buy" else "SELL",
                "symbol": parts[1],
                "quantity": float(parts[2]),
            },
        }

    if command == "/idea" and len(parts) >= 3:
        return {
            "type": "trade_idea",
            "idea": {
                "symbol": parts[1],
                "direction": parts[2].upper(),
                "thesis": " ".join(parts[3:]),
            },
        }

    if command == "/history":
        return {"type": "history", "limit": 50}

    print(f"{RED}Unknown command.{RESET} Try /buy, /sell, /idea, /history, /quit")
    return None


async def receive_loop(socket) -> None:
    """Print every frame the server sends."""
    async for raw in socket:
        try:
            render(json.loads(raw))
        except json.JSONDecodeError:
            print(f"{DIM}[raw] {raw}{RESET}")


async def send_loop(socket) -> None:
    """Read stdin without blocking the event loop and forward frames."""
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line or line.strip() == "/quit":
            await socket.close()
            return
        frame = parse_command(line)
        if frame is not None:
            await socket.send(json.dumps(frame))


async def main(host: str, room: str, user: str) -> None:
    """Connect to a room and run the send/receive loops together."""
    url = f"{host}/api/v1/collab/ws/rooms/{room}?user={user}"
    print(f"{DIM}Connecting to {url}{RESET}")
    async with websockets.connect(url) as socket:
        print(f"{GREEN}Connected as {user}.{RESET} Type a message, or /quit to exit.")
        receiver = asyncio.create_task(receive_loop(socket))
        sender = asyncio.create_task(send_loop(socket))
        done, pending = await asyncio.wait(
            {receiver, sender},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TradeLab collaborative room client")
    parser.add_argument("--host", default="ws://127.0.0.1:8000", help="Server websocket base URL")
    parser.add_argument("--room", required=True, help="Room id from POST /api/v1/collab/rooms")
    parser.add_argument("--user", required=True, help="Your handle in the room")
    args = parser.parse_args()

    try:
        asyncio.run(main(args.host, args.room, args.user))
    except KeyboardInterrupt:
        print("\nDisconnected.")
