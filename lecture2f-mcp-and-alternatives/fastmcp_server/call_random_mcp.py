import asyncio

from fastmcp import Client

async def call_mcp():
    async with Client("http://127.0.0.1:8000/mcp") as client:
        result = await client.call_tool(
            "get_random_number"
        )
        print(result.structured_content)


if __name__ == "__main__":
    asyncio.run(call_mcp())
