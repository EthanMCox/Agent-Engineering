import random
from fastmcp import FastMCP

mcp = FastMCP("NumberServer")

@mcp.tool
def get_random_number() -> int:
    return random.randint(1, 100)


if __name__ == "__main__":
    mcp.run(transport="http", port=8000)
