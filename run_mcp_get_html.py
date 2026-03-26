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

    async with stdio_client(server_params) as transport:
        stdio, write = transport
        async with ClientSession(stdio, write) as session:
            await session.initialize()
            print("✅ Connected to MCP server, calling get-webpage-html tool...")

            try:
                result = await session.call_tool('get-webpage-html', {
                    'query': 'mcp smoke test html',
                    'saveToFile': True,
                    'outputPath': './mcp_html_output'
                })

                print("--- Tool result (repr) ---")
                print(repr(result))
                print("--- Tool result (text items) ---")

                content_items = None
                if hasattr(result, 'content') and result.content:
                    content_items = result.content
                elif isinstance(result, (list, tuple)):
                    content_items = result

                if content_items is not None:
                    for item in content_items:
                        try:
                            print(item.text)
                        except Exception:
                            print(item)
                else:
                    print(result)

            except Exception as e:
                print(f"Tool call failed: {e}")


if __name__ == '__main__':
    asyncio.run(main())
