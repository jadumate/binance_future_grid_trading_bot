# Binance Futures Grid Trading Bot

An automated grid trading bot for Binance Futures (USDT-M) with Telegram notifications.

## Features

- **Grid trading** on Binance Futures (default: BTCUSDT)
- **Leverage support** (default: 10x)
- **Dynamic grid rebalancing** — automatically cancels and re-places orders when the grid is broken
- **Consecutive fill scaling** — buy/sell offsets multiply based on how many consecutive fills occurred in the same direction
- **Asymmetric offset logic** — grid anchors and spreads shift based on the direction of the last filled order
- **Telegram notifications** — get alerts on fills, grid resets, and consecutive fill counts
- **Hourly OHLC data collection** — automatically records 1-hour BTC candles to a local SQLite database (`bitcoin1h.db`)
- **Testnet support** — safely test before going live

## How It Works

The bot maintains a 4-order grid (2 BUY + 2 SELL) anchored to the price of the last filled order.

- Every 10 seconds it checks open orders
- If the count drops below 4 (a fill occurred), it cancels all remaining orders and re-places the full grid
- Offsets shift depending on whether the last fill was a BUY or SELL
- Consecutive fills in the same direction scale the offsets to widen the grid and reduce over-trading
- Price data is sampled every poll cycle to build 1-hour OHLC candles stored in `bitcoin1h.db`

### Grid Offset Logic

| Last Fill | SELL offsets            | BUY offsets              |
|-----------|-------------------------|--------------------------|
| SELL      | `+0.7% × N, +1.5% × N` | `−0.7%, −1.5%`           |
| BUY       | `+0.7%, +1.5%`          | `−0.7% × N, −1.5% × N`  |

`N` = consecutive fill count in that direction (minimum 1).

## Requirements

- Python 3.8+
- Binance Futures account (or Testnet)
- Telegram bot token + chat ID (optional, for notifications)

## Installation

```bash
# Clone the repo
git clone https://github.com/jadumate/binance_future_grid_trading_bot.git
cd binance_future_grid_trading_bot

# Install dependencies
pip install requests python-dotenv

# Copy the env template and fill in your credentials
cp env .env
nano .env
```

## Configuration

Edit `.env` with your credentials:

```env
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret

TELEGRAM_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# true = testnet, false = live
USE_TESTNET=false
```

Edit the top of `binance_future_bot.py` to adjust trading parameters:

| Parameter       | Default   | Description                              |
|-----------------|-----------|------------------------------------------|
| `SYMBOL`        | BTCUSDT   | Futures trading pair                     |
| `LEVERAGE`      | 10        | Leverage multiplier                      |
| `ORDER_USDT`    | 150       | Notional value per order (USDT)          |
| `POLL_INTERVAL` | 10        | Polling interval in seconds              |
| `SELL_AFTER_SELL` | [0.007, 0.015] | SELL offsets after a SELL fill  |
| `BUY_AFTER_SELL`  | [-0.007, -0.015] | BUY offsets after a SELL fill |
| `SELL_AFTER_BUY`  | [0.007, 0.015]   | SELL offsets after a BUY fill |
| `BUY_AFTER_BUY`   | [-0.007, -0.015] | BUY offsets after a BUY fill  |

## Usage

```bash
# Run in foreground
./run

# Run as background daemon
./run daemon
```

Logs are written to `grid_bot.log`.
Hourly OHLC candles are saved to `bitcoin1h.db` (SQLite).

## Telegram Notification Format

```
[BTCUSDT] order completed : 85,000
Continues 3 SELL
```

The message shows the anchor price and how many consecutive fills occurred in the same direction.

## Database Schema

```sql
CREATE TABLE btc_1h (
    datetime TEXT PRIMARY KEY,  -- e.g. 2026030916 (YYYYMMDDHH, UTC)
    start    REAL,
    high     REAL,
    low      REAL,
    end      REAL
);
```

## Disclaimer

This bot trades with real money. Use at your own risk. Always test on Testnet (`USE_TESTNET=true`) before going live. The authors are not responsible for any financial losses.

## License

MIT
