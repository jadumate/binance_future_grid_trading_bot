# Binance Futures Grid Trading Bot

An automated grid trading bot for Binance Futures (USDT-M) with Telegram notifications.

## Features

- **Grid trading** on Binance Futures (default: BTCUSDT)
- **Leverage support** (default: 10x)
- **Dynamic grid rebalancing** — automatically cancels and re-places orders when the grid is broken
- **Smart offset logic** — adjusts buy/sell offsets based on the direction of the last filled order
- **Telegram notifications** — get alerts on fills and grid resets
- **Testnet support** — safely test before going live

## How It Works

The bot maintains a 4-order grid (2 BUY + 2 SELL) around the current market price.

- Every 10 seconds it checks open orders
- If the count drops below 4 (a fill occurred), it cancels all remaining orders and re-places the full grid
- Offsets shift depending on whether the last fill was a BUY or SELL, creating an asymmetric grid that adapts to momentum

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

| Parameter       | Default   | Description                          |
|----------------|-----------|--------------------------------------|
| `SYMBOL`        | BTCUSDT   | Futures trading pair                 |
| `LEVERAGE`      | 10        | Leverage multiplier                  |
| `ORDER_USDT`    | 150       | Notional value per order (USDT)      |
| `POLL_INTERVAL` | 10        | Polling interval in seconds          |

## Usage

```bash
# Run in foreground
./run

# Run as background daemon
./run daemon
```

Logs are written to `grid_bot.log` and `bot_eth.log`.

## Disclaimer

This bot trades with real money. Use at your own risk. Always test on Testnet (`USE_TESTNET=true`) before going live. The authors are not responsible for any financial losses.

## License

MIT
