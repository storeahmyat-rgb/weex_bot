# Binance Futures Trading Bot - EMA Strategy

Ek complete Python-based Binance USDT-M Futures trading bot with web UI.

## Strategy: Quad EMA Crossover (8, 13, 21, 55)

Yeh bot **4 Exponential Moving Averages** use karta hai:

| Indicator | Period | Color  |
|-----------|--------|--------|
| EMA       | 8      | Blue   |
| EMA       | 13     | Orange |
| EMA       | 21     | Purple |
| EMA       | 55     | Red    |

### Rules
- **LONG (BUY)**: Jab EMA 55 baaki sabhi EMAs (8, 13, 21) ko cross karke sabse **neeche** (bottom) chali jaaye.
- **SHORT (SELL)**: Jab EMA 55 baaki sabhi EMAs (8, 13, 21) ko cross karke sabse **upar** (top) chali jaaye.
- **Exit**: Position tab tak hold hoti hai jab tak opposite signal na aa jaaye.
- **Recommended Timeframe**: 4h, Daily, Weekly (higher TF = zyada reliable).

---

## Features

- Web UI (http://localhost:5000) - mobile + desktop responsive
- 100x+ leverage support (1-125x)
- Testnet aur Mainnet dono support
- Real-time price chart with 4 EMA overlays
- Live position, PnL, balance display
- Activity logs (real-time)
- Manual position close button
- Long only / Short only / Both modes
- Auto-save configuration
- Quick leverage buttons (5x, 10x, 20x, 50x, 100x, 125x)

---

## Installation (5 Steps)

### Step 1: Python Install Karein
Python 3.9+ chahiye. Download from https://python.org

Check karein:
```bash
python --version
```

### Step 2: Project Folder Mein Jaayein
```bash
cd binance-futures-bot
```

### Step 3: Virtual Environment Banaayein (recommended)
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux / Mac
python3 -m venv venv
source venv/bin/activate
```

### Step 4: Dependencies Install Karein
```bash
pip install -r requirements.txt
```

### Step 5: Bot Start Karein
```bash
# Windows
run.bat

# Linux / Mac
chmod +x run.sh
./run.sh
```

Browser mein khol: **http://localhost:5000**

---

## Binance API Keys Kaise Lein

### Testnet (Recommended for testing - FREE)
1. Jaayein: https://testnet.binancefuture.com
2. Login karein (Binance account se)
3. Top right pe "API Key" button click karein
4. API Key aur Secret copy karein
5. Bot UI mein paste karein, Testnet select karein

### Mainnet (Real money - careful!)
1. Jaayein: https://www.binance.com
2. Account -> API Management
3. "Create API" click karein
4. **Permissions**: Enable Futures, Disable Withdrawals
5. IP restriction ON karein (recommended)
6. API Key + Secret copy karein
7. Bot UI mein paste karein, Mainnet select karein

---

## UI Usage

1. **Settings panel** mein API Key, Secret, Symbol, Timeframe, Leverage, Amount daalein.
2. **Save** button dabayein.
3. **START BOT** dabayein - bot ab background mein strategy run karega.
4. **Activity Logs** mein har action dikhega.
5. **Live Indicators** panel mein EMAs aur current signal dikhega.
6. **Open Position** panel mein current position aur PnL dikhega.
7. STOP BOT dabane se bot ruk jaayega (position close nahi hoti).
8. **Close Position** button se manual close kar sakte hain.

---

## Configuration Options

| Field      | Default  | Description                                  |
|------------|----------|----------------------------------------------|
| api_key    | (empty)  | Binance Futures API key                      |
| api_secret | (empty)  | Binance Futures API secret                   |
| testnet    | true     | Testnet (safe) ya Mainnet (real money)       |
| symbol     | BTCUSDT  | Trading pair                                 |
| timeframe  | 1d       | 1m, 5m, 15m, 1h, 4h, 1d, 1w                 |
| leverage   | 10       | 1-125x                                       |
| amount     | 100      | USDT position size                           |
| mode       | both     | long / short / both                          |

---

## Project Structure

```
binance-futures-bot/
├── app.py                  # Flask web app (main entry point)
├── requirements.txt        # Python dependencies
├── config.json             # Auto-saved user configuration
├── run.sh / run.bat        # Quick start scripts
├── bot/                    # Trading logic package
│   ├── __init__.py
│   ├── indicators.py       # EMA, SMA, RSI, ATR calculations
│   ├── strategy.py         # Quad EMA crossover strategy
│   ├── trader.py           # Binance Futures API wrapper
│   └── engine.py           # Background trading engine
├── templates/
│   └── dashboard.html      # Web UI
├── static/
│   ├── css/style.css       # Dark trading theme
│   └── js/app.js           # Frontend logic (Socket.IO + chart)
├── logs/                   # Bot logs (auto-created)
└── README.md
```

---

## Strategy Logic (Code Reference)

```python
# BUY signal: EMA55 is the LOWEST of all four EMAs
if e55 < e8 and e55 < e13 and e55 < e21:
    signal = BUY   # go LONG

# SELL signal: EMA55 is the HIGHEST of all four EMAs
elif e55 > e8 and e55 > e13 and e55 > e21:
    signal = SELL  # go SHORT

else:
    signal = HOLD  # no action
```

---

## Troubleshooting

**Q: Bot start nahi ho raha?**
- API key/secret sahi daalein.
- Testnet pe account banayein: https://testnet.binancefuture.com
- Internet connection check karein.

**Q: "Insufficient margin" error?**
- Amount kam karein ya leverage badhaayein.
- Testnet pe balance recharge karein.

**Q: "Leverage not changed" error?**
- Yeh normal hai - Binance bolta hai leverage pehle se same hai. Ignore karein.

**Q: Chart update nahi ho raha?**
- Bot running ho, fir 30 second wait karein.

**Q: Python package install error?**
- `pip install --upgrade pip` chalayein.
- Python 3.9+ zaroori hai.

---

## Safety Warnings

- **Pehle TESTNET par test karein** - kabhi bhi real paise se shuru mat karein.
- Yeh bot educational purpose ke liye hai. Trading mein loss ka risk hai.
- Always start with small amounts.
- Bot ko chhod kar mat jaayein jab real money use kar rahe ho.
- Author kisi bhi loss ka zimmedaar nahi hai.

---

## License

MIT - Free to use, modify, distribute.

---

## Support

Issues ya questions ke liye logs/ folder mein `bot.log` check karein.
