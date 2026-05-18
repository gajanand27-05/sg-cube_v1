"""Finance tools (Phase 11d) — stocks via Yahoo Finance JSON, crypto via CoinGecko.

Both are free, no API key. Uses httpx directly to avoid pulling in pandas
(which yfinance does). Caches the CoinGecko coin-id list lazily.
"""
import httpx

from backend.core.tools.registry import tool

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
COINGECKO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
USER_AGENT = "Mozilla/5.0 (SG_CUBE)"

# Common-name -> coingecko-id quick map. (Full /coins/list is 500KB; only need
# the popular ones in a voice context.)
COIN_ALIASES = {
    "btc": "bitcoin", "bitcoin": "bitcoin",
    "eth": "ethereum", "ethereum": "ethereum", "ether": "ethereum",
    "sol": "solana", "solana": "solana",
    "doge": "dogecoin", "dogecoin": "dogecoin",
    "ada": "cardano", "cardano": "cardano",
    "xrp": "ripple", "ripple": "ripple",
    "dot": "polkadot", "polkadot": "polkadot",
    "matic": "matic-network", "polygon": "matic-network",
    "shib": "shiba-inu", "shiba": "shiba-inu",
    "ltc": "litecoin", "litecoin": "litecoin",
    "link": "chainlink", "chainlink": "chainlink",
    "avax": "avalanche-2", "avalanche": "avalanche-2",
    "bnb": "binancecoin", "binance coin": "binancecoin",
    "trx": "tron", "tron": "tron",
}


@tool
def get_stock_price(symbol: str) -> dict:
    """Get the current price for a stock ticker (e.g. "AAPL", "TSLA", "MSFT",
    "RELIANCE.NS"). Returns price, currency, and intraday change percent."""
    sym = symbol.strip().upper()
    if not sym:
        return {"status": "blocked", "reason": "empty symbol"}

    try:
        with httpx.Client(timeout=10.0, headers={"User-Agent": USER_AGENT}) as c:
            r = c.get(YAHOO_URL.format(symbol=sym))
    except Exception as e:
        return {"status": "error", "reason": f"Yahoo Finance error: {e}"}

    if r.status_code != 200:
        return {"status": "blocked", "reason": f"no data for {sym!r} (HTTP {r.status_code})"}

    body = r.json()
    chart = (body.get("chart") or {}).get("result") or []
    if not chart:
        err = ((body.get("chart") or {}).get("error") or {}).get("description") or "no result"
        return {"status": "blocked", "reason": f"no data for {sym!r}: {err}"}

    meta = chart[0].get("meta") or {}
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose")
    name = meta.get("longName") or meta.get("shortName") or sym
    currency = meta.get("currency") or "USD"

    if price is None:
        return {"status": "blocked", "reason": f"no price for {sym!r}"}

    change_pct = ((price - prev) / prev * 100.0) if prev else 0.0
    sign = "+" if change_pct >= 0 else ""

    return {
        "status": "success",
        "message": f"{name} ({sym}): {price:.2f} {currency} ({sign}{change_pct:.2f}%)",
        "args": {
            "symbol": sym,
            "name": name,
            "price": price,
            "currency": currency,
            "change_pct": round(change_pct, 2),
        },
    }


@tool
def get_crypto_price(symbol: str) -> dict:
    """Get the current USD price for a cryptocurrency (e.g. "btc", "bitcoin",
    "eth", "solana"). Returns price and 24-hour change percent."""
    sym = symbol.strip().lower()
    if not sym:
        return {"status": "blocked", "reason": "empty symbol"}

    coin_id = COIN_ALIASES.get(sym, sym)

    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(
                COINGECKO_PRICE_URL,
                params={
                    "ids": coin_id,
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                },
            )
    except Exception as e:
        return {"status": "error", "reason": f"CoinGecko error: {e}"}

    if r.status_code != 200:
        return {"status": "blocked", "reason": f"CoinGecko HTTP {r.status_code}"}

    data = r.json().get(coin_id)
    if not data:
        return {"status": "blocked", "reason": f"no price for {sym!r} (id={coin_id!r})"}

    price = data.get("usd")
    change_pct = data.get("usd_24h_change") or 0.0
    sign = "+" if change_pct >= 0 else ""

    if price is None:
        return {"status": "blocked", "reason": "no price"}

    return {
        "status": "success",
        "message": f"{coin_id.title()}: ${price:,.2f} ({sign}{change_pct:.2f}% / 24h)",
        "args": {
            "symbol": sym,
            "coin_id": coin_id,
            "price_usd": price,
            "change_pct_24h": round(change_pct, 2),
        },
    }
