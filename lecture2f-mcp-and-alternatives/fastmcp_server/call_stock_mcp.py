import asyncio
import sys

from fastmcp import Client

async def call_mcp(ticker: str):
    async with Client("http://127.0.0.1:8000/mcp") as client:
        result = await client.call_tool(
            "get_stock_quote",
            {"ticker": ticker}
        )
        print(result.structured_content)


if __name__ == "__main__":
    ticker = "GOOG" if len(sys.argv) == 1 else sys.argv[1]
    asyncio.run(call_mcp(ticker))
