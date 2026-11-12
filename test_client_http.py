"""Calls the running HTTP server (start it first: python mcp_server_v2.py http).
Uses only the cached-file Resources, so no database is needed."""
import asyncio

from mcp import Client


async def main():
    async with Client("http://127.0.0.1:8765/mcp") as client:
        tools = await client.list_tools()
        print("tools:", [t.name for t in tools.tools])

        res = await client.list_resources()
        print("resources:", [r.uri for r in res.resources])

        tmpl = await client.list_resource_templates()
        print("templates:", [t.uri_template for t in tmpl.resource_templates])

        r = await client.read_resource("fred://series/FEDFUNDS")
        print("read:", r.contents[0].text.replace("\n", " ")[:160])

        try:
            await client.read_resource("fred://series/NOPE")
        except Exception as e:
            print("missing ->", type(e).__name__, getattr(e, "code", None), str(e)[:80])


asyncio.run(main())
