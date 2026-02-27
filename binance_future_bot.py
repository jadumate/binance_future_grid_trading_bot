"""
Binance Futures Grid Auto-Trading Bot
======================================
- Symbol   : BTCUSDT
- Leverage : 10x
- Order size: $150 notional per order (quantity auto-calculated from entry price)
- Polling  : every 10 seconds

If open orders != 4, cancel all and re-place the grid.
"""

import hmac
import hashlib
import time
import math
import logging
import os
import sys
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv
from typing import Optional, List

# ============================================================
# Load .env
# ============================================================
load_dotenv()

API_KEY          = os.getenv("BINANCE_API_KEY", "")
API_SECRET       = os.getenv("BINANCE_API_SECRET", "")
USE_TESTNET      = os.getenv("USE_TESTNET", "false").lower() == "true"
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

if not API_KEY or not API_SECRET:
    sys.exit("Please set BINANCE_API_KEY / BINANCE_API_SECRET in the .env file.")

# ============================================================
# Configuration (editable)
# ============================================================
SYMBOL        = "BTCUSDT"
LEVERAGE      = 10
ORDER_USDT    = 150         # Notional value per order (USDT); margin used = ORDER_USDT / LEVERAGE
POLL_INTERVAL = 10          # Polling interval (seconds)

# When the last fill was a SELL
SELL_AFTER_SELL = [0.007, 0.015]    # SELL order offsets (multiplied by consecutive SELL count)
BUY_AFTER_SELL  = [-0.007, -0.015]  # BUY order offsets

# When the last fill was a BUY
SELL_AFTER_BUY  = [0.007, 0.015]    # SELL order offsets
BUY_AFTER_BUY   = [-0.007, -0.015]  # BUY order offsets (multiplied by consecutive BUY count)

# ============================================================
# URLs
# ============================================================
if USE_TESTNET:
    BASE_URL = "https://testnet.binancefuture.com"
else:
    BASE_URL = "https://fapi.binance.com"

# ============================================================
# Logging
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("grid_bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ============================================================
# Signature / HTTP helpers
# ============================================================
def _sign(params: dict) -> str:
    query = urlencode(params)
    return hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()


def _headers() -> dict:
    return {"X-MBX-APIKEY": API_KEY}


def _get(path: str, params: dict = None, signed: bool = False) -> dict:
    params = params or {}
    if signed:
        params["timestamp"] = int(time.time() * 1000)
        params["signature"] = _sign(params)
    r = requests.get(BASE_URL + path, params=params, headers=_headers(), timeout=10)
    _check(r)
    return r.json()


def _post(path: str, params: dict = None) -> dict:
    params = params or {}
    params["timestamp"] = int(time.time() * 1000)
    params["signature"] = _sign(params)
    r = requests.post(BASE_URL + path, params=params, headers=_headers(), timeout=10)
    _check(r)
    return r.json()


def _delete(path: str, params: dict = None) -> dict:
    params = params or {}
    params["timestamp"] = int(time.time() * 1000)
    params["signature"] = _sign(params)
    r = requests.delete(BASE_URL + path, params=params, headers=_headers(), timeout=10)
    _check(r)
    return r.json()


def _check(r: requests.Response):
    if not r.ok:
        log.error("API error %s: %s", r.status_code, r.text)
        r.raise_for_status()


# ============================================================
# Symbol info (price / quantity precision)
# ============================================================
_symbol_info_cache: dict = {}


def get_symbol_info(symbol: str) -> dict:
    if symbol not in _symbol_info_cache:
        info = _get("/fapi/v1/exchangeInfo")
        for s in info["symbols"]:
            if s["symbol"] == symbol:
                _symbol_info_cache[symbol] = s
                break
    return _symbol_info_cache[symbol]


def get_price_precision(symbol: str) -> int:
    info = get_symbol_info(symbol)
    for f in info["filters"]:
        if f["filterType"] == "PRICE_FILTER":
            tick = float(f["tickSize"])
            return max(0, int(round(-math.log10(tick))))
    return 2


def get_qty_precision(symbol: str) -> int:
    info = get_symbol_info(symbol)
    for f in info["filters"]:
        if f["filterType"] == "LOT_SIZE":
            step = float(f["stepSize"])
            return max(0, int(round(-math.log10(step))))
    return 3


def round_price(price: float) -> str:
    p = get_price_precision(SYMBOL)
    return f"{round(price, p):.{p}f}"


def round_qty(qty: float) -> str:
    p = get_qty_precision(SYMBOL)
    return f"{round(qty, p):.{p}f}"


# ============================================================
# Telegram notification
# ============================================================
def send_telegram(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=5)
    except Exception as e:
        log.warning("Telegram send failed: %s", e)


# ============================================================
# Set leverage
# ============================================================
def set_leverage():
    result = _post("/fapi/v1/leverage", {
        "symbol": SYMBOL,
        "leverage": LEVERAGE,
    })
    log.info("Leverage set: %sx", result.get("leverage"))


# ============================================================
# Get current price
# ============================================================
def get_current_price() -> float:
    data = _get("/fapi/v1/ticker/price", {"symbol": SYMBOL})
    return float(data["price"])


LOOKBACK_DAYS = 7
FETCH_LIMIT = 1000


def _fetch_recent_trades() -> List[dict]:
    """
    Fetch fills for the last LOOKBACK_DAYS days, sorted oldest -> newest.
    Call this once per cycle and pass the result to helper functions
    to avoid redundant API requests.
    """
    since_ms = int(time.time() * 1000) - LOOKBACK_DAYS * 24 * 60 * 60 * 1000

    params = {
        "symbol": SYMBOL,
        "limit": FETCH_LIMIT,
        "startTime": since_ms
    }

    trades = _get("/fapi/v1/userTrades", params, signed=True) or []

    # Sort oldest -> newest
    trades.sort(key=lambda x: x["time"])
    return trades


def _compress_orders(trades: List[dict]) -> List[dict]:
    """
    Collapse multiple fills with the same orderId into a single order entry
    to avoid double-counting partial fills.
    """
    orders = []
    seen = set()

    for t in trades:
        oid = t["orderId"]
        if oid not in seen:
            orders.append({
                "orderId": oid,
                "side": t["side"],
                "price": float(t["price"]),
                "time": t["time"]
            })
            seen.add(oid)

    return orders


def get_last_trade(trades: List[dict]) -> Optional[dict]:
    """
    Return the most recent order-level fill from pre-fetched trades.
    Returns: {"side": "BUY"/"SELL", "price": float}
    """
    orders = _compress_orders(trades)
    if not orders:
        return None

    last = orders[-1]
    return {
        "side": last["side"],
        "price": last["price"],
    }


def get_consecutive_sell_count(trades: List[dict]) -> int:
    """
    Count how many consecutive SELL orders appear at the tail of the trade list.
    Returns at least 1.
    """
    orders = _compress_orders(trades)

    if not orders or orders[-1]["side"] != "SELL":
        return 1

    count = 0
    for o in reversed(orders):
        if o["side"] == "SELL":
            count += 1
        else:
            break

    log.info("Consecutive SELL count: %d", count)
    return max(1, count)


def get_consecutive_buy_count(trades: List[dict]) -> int:
    """
    Count how many consecutive BUY orders appear at the tail of the trade list.
    Returns at least 1.
    """
    orders = _compress_orders(trades)

    if not orders or orders[-1]["side"] != "BUY":
        return 1

    count = 0
    for o in reversed(orders):
        if o["side"] == "BUY":
            count += 1
        else:
            break

    log.info("Consecutive BUY count: %d", count)
    return max(1, count)


# ============================================================
# Open order management
# ============================================================
def get_open_orders() -> list:
    return _get("/fapi/v1/openOrders", {"symbol": SYMBOL}, signed=True)


def cancel_all_orders():
    """
    Cancel all open orders.
    Raises on failure to prevent placing duplicate orders on top of stale ones.
    """
    _delete("/fapi/v1/allOpenOrders", {"symbol": SYMBOL})
    log.info("All open orders cancelled")


def wait_orders_cleared(timeout: int = 10):
    """
    Poll until open orders are empty after a cancel request.
    If orders persist after the first timeout, retry cancel once and poll again.
    Raises RuntimeError if orders still remain after the second attempt,
    aborting grid placement to prevent duplicate orders.
    """
    def _poll(deadline: float) -> bool:
        while time.time() < deadline:
            if not get_open_orders():
                return True
            time.sleep(0.5)
        return False

    if _poll(time.time() + timeout):
        return

    # First timeout — retry cancel once before giving up
    log.warning("Order cancel confirmation timed out (%ds) — retrying cancel", timeout)
    cancel_all_orders()

    if _poll(time.time() + timeout):
        return

    raise RuntimeError(
        "Orders still open after two cancel attempts; "
        "aborting grid placement to avoid duplicate orders."
    )


# ============================================================
# Place individual order
# ============================================================
def place_limit_order(side: str, price: float, qty_usdt: float) -> dict:
    """
    side     : "BUY" or "SELL"
    price    : order price
    qty_usdt : notional value in USDT -> quantity is auto-calculated
               (margin used = qty_usdt / LEVERAGE)
    """
    qty = float(qty_usdt) / price
    params = {
        "symbol"     : SYMBOL,
        "side"       : side,
        "type"       : "LIMIT",
        "timeInForce": "GTC",
        "price"      : round_price(price),
        "quantity"   : round_qty(qty),
    }
    result = _post("/fapi/v1/order", params)
    log.info(
        "  Order placed -> %s | price: %s | qty: %s | orderId: %s",
        side, round_price(price), round_qty(qty), result.get("orderId"),
    )
    return result


# ============================================================
# Place 4 grid orders
# ============================================================
def place_grid_orders(last_side: str, last_price: float,
                      consecutive_sell_count: int = 1,
                      consecutive_buy_count: int = 1):
    """
    last_side             : direction of the last fill ("BUY" / "SELL")
    last_price            : price of the last fill (grid anchor price)
    consecutive_sell_count: consecutive SELL count — multiplied into SELL_AFTER_SELL offsets
    consecutive_buy_count : consecutive BUY count  — multiplied into BUY_AFTER_BUY  offsets
    """
    if last_side == "SELL":
        sell_offsets = [o * consecutive_sell_count for o in SELL_AFTER_SELL]
        buy_offsets  = BUY_AFTER_SELL
        log.info("SELL_AFTER_SELL offsets x %d -> %s",
                 consecutive_sell_count,
                 [f"{o*100:+.2f}%" for o in sell_offsets])
    else:  # BUY
        sell_offsets = SELL_AFTER_BUY
        buy_offsets  = [o * consecutive_buy_count for o in BUY_AFTER_BUY]
        log.info("BUY_AFTER_BUY offsets x %d -> %s",
                 consecutive_buy_count,
                 [f"{o*100:+.2f}%" for o in buy_offsets])

    log.info("== Grid placement start | last_fill=%s | anchor=%.2f ==",
             last_side, last_price)

    for offset in sell_offsets:
        place_limit_order("SELL", last_price * (1 + offset), ORDER_USDT)

    for offset in buy_offsets:
        place_limit_order("BUY",  last_price * (1 + offset), ORDER_USDT)

    log.info("== Grid placement complete (2 SELL + 2 BUY) ==")


# ============================================================
# Main loop
# ============================================================
def run():
    log.info("=" * 55)
    log.info("  Binance Futures Grid Bot Started")
    log.info("  Symbol: %s | Leverage: %sx | Order size: $%s notional",
             SYMBOL, LEVERAGE, ORDER_USDT)
    log.info("  Testnet: %s", USE_TESTNET)
    log.info("=" * 55)

    # Set leverage on startup
    set_leverage()

    while True:
        try:
            open_orders  = get_open_orders()
            order_count  = len(open_orders)
            log.info("Open orders: %d", order_count)

            if order_count != 4:
                log.info("Order count abnormal (%d) -> cancelling all and re-placing", order_count)

                # Fetch trade history once and reuse for all queries this cycle
                trades = _fetch_recent_trades()
                last_trade = get_last_trade(trades)

                if last_trade is None:
                    # No fill history — use current price as anchor (treat as post-SELL)
                    log.warning("No fill history -> using current price as anchor (SELL logic applied)")
                    last_price = get_current_price()
                    last_side  = "SELL"
                else:
                    last_price = last_trade["price"]
                    last_side  = last_trade["side"]
                    log.info("Last fill -> %s @ %.2f", last_side, last_price)

                consecutive_sell_count = get_consecutive_sell_count(trades) if last_side == "SELL" else 1
                consecutive_buy_count  = get_consecutive_buy_count(trades)  if last_side == "BUY"  else 1

                cancel_all_orders()
                wait_orders_cleared()
                place_grid_orders(last_side, last_price, consecutive_sell_count, consecutive_buy_count)
                consec_count = consecutive_sell_count if last_side == "SELL" else consecutive_buy_count
                send_telegram(f"[{SYMBOL}] order completed : {last_price:,.0f}\nContinues {consec_count} {last_side}")

            else:
                log.info("Orders healthy")

        except requests.exceptions.RequestException as e:
            log.error("Network error: %s", e)
        except RuntimeError as e:
            log.error("Grid placement aborted: %s", e)
        except Exception as e:
            log.exception("Unexpected error: %s", e)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
