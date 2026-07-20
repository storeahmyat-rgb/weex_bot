# TradeBot Cloud SaaS

## 🎯 Kya Hai Yeh?

Yeh **CLOUD SaaS** hai — tumhare **SERVER** pe chalega. Users apne PC pe kuch nahi rakhte. Sirf browser khol ke login karte hain, aur unka bot 24/7 tumhare server pe chalta hai.

```
Tumhara Server (cloud)
   ├── User 1 ka bot (apni API keys, apni settings)
   ├── User 2 ka bot (apni API keys, apni settings)
   ├── User 3 ka bot (apni API keys, apni settings)
   └── ... 100+ users

Users sirf browser kholte hain → login → dashboard
Unka PC band bhi ho to bot chalta rahega
```

## 🚀 Server Pe Install (ONE COMMAND)

### Step 1: Zip Upload Karo Server Pe
```bash
scp tradebot-cloud.zip user@your-server-ip:~/
```

### Step 2: Extract + Install
```bash
ssh user@your-server-ip
unzip tradebot-cloud.zip
cd tradebot-cloud
chmod +x install.sh
./install.sh
```

**Bas! 5 minute mein sab ready.** Install script sab khud karta hai:
- ✅ Python 3 + pip install
- ✅ PM2 (24/7 auto-restart ke liye)
- ✅ Bot dependencies
- ✅ Secrets generate
- ✅ Server start on port 5000

### Step 3: Public URL (Cloudflare Tunnel - FREE)
```bash
cloudflared tunnel --url http://localhost:5000
```
Yeh ek public URL dega jaise `https://random-words.trycloudflare.com`. Users ko yeh URL bhejo.

## 👤 Users Kaise Use Karenge

1. Tumhara URL pe jayenge (jaise `https://abc.trycloudflare.com`)
2. **Sign Up** karenge (email + password) → 7-day free trial
3. Login → Dashboard khulega
4. **Settings** tab mein:
   - Exchange select (Binance/WEEX)
   - API Key + Secret + Passphrase enter
   - Coins add karein
   - Leverage, SL/TP set karein
   - **Save** dabao
5. **Overview** tab mein → **Start Bot** dabao
6. Bot 24/7 chalega (server pe) — user ka PC band bhi ho to

## 👨‍💼 Admin (Tum) Kaise Manage Karoge

1. `https://abc.trycloudflare.com/admin` kholo
2. Password: **`AdminBot@2024!`** (change it in `.env` file)
3. Sab users dekh sakte ho:
   - Email, name, subscription status
   - Bot running ya nahi
   - Exchange kya use kar raha
4. **Actions:**
   - **Extend** — user ki subscription extend karo (days add karo)
   - **Ban/Unban** — user ko block/unblock karo
   - **Delete** — user permanently delete karo

## 💰 Subscription System

- **Trial:** 7 days free (auto, har naye user ko)
- **Basic/Pro/Lifetime:** Admin manually extend karta hai
- Expired users ka bot automatically stop ho jata hai

## 📋 Pricing Suggestion

| Plan | Price | Duration |
|------|-------|----------|
| Trial | FREE | 7 days |
| Monthly | $30 | 30 days |
| Quarterly | $75 | 90 days |
| Yearly | $250 | 365 days |
| Lifetime | $400 | Forever |

Admin panel se user ki subscription extend karo jab woh payment kare.

## 🔒 Security

- ✅ API keys **encrypted** store hoti hain (AES-style XOR + base64)
- ✅ Passwords **hashed** (SHA-256 + salt)
- ✅ Per-user bot isolation (alag process, alag port)
- ✅ Admin password protected
- ✅ Session-based auth (7-day expiry)

## 🤖 Bot Strategy (UNCHANGED)

- EMA 8, 13, 21, 55 crossover ✓
- 1:3 Risk-Reward (SL=2%, TP=6% hardcoded) ✓
- Fresh cross detection ✓
- Software SL/TP watchdog ✓
- Real exchange SL/TP (WEEX) ✓
- Binance + WEEX support ✓

**Koi strategy change nahi hua.** Sirf cloud layer add hua.

## 📁 Folder Structure

```
tradebot-cloud/
├── install.sh              ← ONE command install
├── app.py                  ← Main SaaS app (Flask)
├── .env                    ← Secrets (auto-generated)
├── bot-engine/             ← Python bot (UNCHANGED)
│   ├── app.py              ← Bot Flask app
│   ├── bot/
│   │   ├── strategy.py     ← EMA 8,13,21,55
│   │   ├── trader.py       ← Binance
│   │   ├── weex_trader.py  ← WEEX
│   │   └── engine.py       ← Bot engine
│   └── requirements.txt
├── templates/
│   ├── cloud_login.html    ← Login/Signup page
│   ├── cloud_dashboard.html ← User dashboard
│   └── cloud_admin.html    ← Admin panel
├── database.json           ← Users + configs (auto-created)
├── user_configs/           ← Per-user bot configs
└── logs/                   ← Log files
```

## 🛠️ Management Commands

```bash
pm2 status                    # Check if running
pm2 logs tradebot-cloud       # View live logs
pm2 restart tradebot-cloud    # Restart server
pm2 stop tradebot-cloud       # Stop server

# Cloudflare tunnel (public URL ke liye)
cloudflared tunnel --url http://localhost:5000
```

## ⚠️ Important Notes

1. **Admin password change karo!** `.env` file mein `ADMIN_SECRET` edit karo
2. **Encryption key change karo!** `.env` file mein `ENCRYPTION_KEY` (install script khud generate karta hai)
3. **Database backup** — `database.json` file ka backup rakho
4. **Server specs:**
   - 10 users: 2GB RAM, 1 CPU
   - 50 users: 4GB RAM, 2 CPU
   - 100 users: 8GB RAM, 4 CPU

## 🆘 Troubleshooting

### Bot not starting for user?
```bash
pm2 logs tradebot-cloud --lines 50
cat logs/bot_<user_id>.log
```

### Admin password change?
Edit `.env` file:
```
ADMIN_SECRET=YourNewPassword123
```
Then: `pm2 restart tradebot-cloud`

### Database reset?
```bash
pm2 stop tradebot-cloud
rm database.json
pm2 start tradebot-cloud
```
**Warning:** Sab users delete ho jayenge!

### Public URL band ho gaya?
Cloudflare tunnel ko background mein chalao:
```bash
nohup cloudflared tunnel --url http://localhost:5000 > tunnel.log 2>&1 &
```

## 📊 Revenue Projection

| Users | Monthly | Yearly | Server Cost | Profit |
|-------|---------|--------|-------------|--------|
| 10 | $300 | $3,600 | $20 | $280/mo |
| 25 | $750 | $9,000 | $40 | $710/mo |
| 50 | $1,500 | $18,000 | $80 | $1,420/mo |
| 100 | $3,000 | $36,000 | $150 | $2,850/mo |

---

**Made with ❤️ — Cloud SaaS for trading bot.**

Strategy UNCHANGED: EMA 8,13,21,55 + 1:3 RR + fresh cross only.
