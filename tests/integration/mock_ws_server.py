import asyncio
import json

import websockets


async def handler(websocket):
    async for message in websocket:
        request = json.loads(message)
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "method": request["method"],
                "params": request.get("params"),
            },
        }
        await websocket.send(json.dumps(response))


async def main():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
