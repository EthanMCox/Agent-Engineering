from fastmcp import FastMCP
from typing import Any, Dict
import yfinance as yf

mcp = FastMCP("Stock_Ticker_Server")


@mcp.tool
def get_stock_quote(ticker: str) -> Dict[str, Any]:
    """Return the last price for a stock. Input must be a valid stock ticker.
    ticker: A valid ticker symbol.
    Returns: {'ticker': ticker, 'last_price': price}
    """
    t = yf.Ticker(ticker)
    info = getattr(t, "fast_info", {})
    last = getattr(info, "last_price", None) or (info.get("last_price") if isinstance(info, dict) else None)
    if last is None:
        hist = t.history(period="1d")
        last = float(hist["Close"][-1]) if len(hist) else None
    return {"ticker": ticker.upper(), "last_price": last}


if __name__ == "__main__":
    mcp.run(transport="http", port=8000)


