"""Read-only smoke test for mcp_server_v2.py (no FRED calls, no DB writes)."""
import asyncio

from mcp import Client

from mcp_server_v2 import mcp


async def main():
    # Passing the server object connects in memory: no process, no pipes, no network.
    async with Client(mcp) as client:
        tools = await client.list_tools()
        for t in tools.tools:
            print(t.name, "->", t.input_schema)

        r = await client.call_tool("get_latest_indicator", {"indicator_id": "GDP"})
        print("latest:", r.content[0].text.replace("\n", " "))

        r = await client.call_tool("get_indicator_history", {"indicator_id": "GDP", "limit": 2})
        print("history:", r.content[0].text.replace("\n", " "))

        # A value outside the enum should be rejected before your code runs.
        r = await client.call_tool("get_latest_indicator", {"indicator_id": "BOGUS"})
        print("bogus is_error:", r.is_error)


if __name__ == "__main__":
    asyncio.run(main())
