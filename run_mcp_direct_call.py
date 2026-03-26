import asyncio
import sys
from mcp.client.stdio import stdio_client
from mcp import ClientSession, StdioServerParameters

async def main():
    server_params = StdioServerParameters(
        command=sys.executable,
        args=['-m', 'mcp_integration.server'],
        env=None
    )

    # start server subprocess and create session
    async with stdio_client(server_params) as transport:
        stdio, write = transport
        async with ClientSession(stdio, write) as session:
            await session.initialize()
            print("✅ Connected to MCP server, calling tool...")

            try:
                result = await session.call_tool('google-search', {
                    'query': 'mcp smoke test',
                    'limit': 1,
                    'timeout': 30000
                })
                print("--- Tool result (repr) ---")
                print(repr(result))
                print("--- Tool result (text items) ---")
                for item in result:
                    try:
                        print(item.text)
                    except Exception:
                        print(item)
            except Exception as e:
                print(f"Tool call failed: {e}")

if __name__ == '__main__':
    asyncio.run(main())
