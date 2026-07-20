# 📱 Mobile App Setup Guide (Termux + PWA)

Is guide se aap apne phone pe bot ko **native app jaisa** chala sakte ho.

## 📋 Requirements
- Android phone (Android 7+)
- 500MB free storage
- Internet connection

---

## Step 1: Termux Install Karo

### F-Droid se (Recommended):
1. Browser mein https://f-droid.org kholo
2. F-Droid app download karo aur install karo
3. F-Droid mein "Termux" search karo
4. Install karo

### Play Store se (NOT recommended - outdated):
Play Store ka Termux outdated hai. F-Droid se install karo.

---

## Step 2: Bot Code Transfer Karo

### Option A: Git se (agar GitHub pe hai)
```bash
pkg install git
git clone https://github.com/yourusername/binance-futures-bot.git ~/binance-futures-bot
```

### Option B: Phone pe copy karo
1. Bot ZIP file ko phone ke Download folder mein rakho
2. Termux mein type karo:
```bash
termux-setup-storage
cp ~/storage/downloads/binance-futures-bot.zip ~/
cd ~ && unzip binance-futures-bot.zip
```

---

## Step 3: Auto-Install Script Chalao

Termux kholo aur type karo:
```bash
cd ~/binance-futures-bot
bash install_termux.sh
```

Yeh automatically:
- ✅ Python install karega
- ✅ Saari dependencies install karega
- ✅ Termux:API install karega
- ✅ Start script banayega

**Time:** 5-10 minutes lagenge (internet speed pe depend)

---

## Step 4: Bot Start Karo

```bash
bash ~/binance-futures-bot/start_bot.sh
```

Yeh:
1. Flask server start karega (background mein)
2. Browser automatically kholega `http://localhost:5000`
3. Bot UI dikhega

---

## Step 5: App Jaisa Install Karo (PWA)

1. Browser (Chrome) mein `http://localhost:5000` kholo
2. Menu (⋮) dabao
3. **"Add to Home screen"** ya **"Install app"** select karo
4. Name: "Trading Bot" rakho
5. **Add** dabao

Ab phone ke home screen pe **Trading Bot** icon aayega. Tap karo → directly app khulega (browser UI nahi dikhega).

---

## Step 6: Home Screen Shortcut (Termux Widget)

Bot ko ek tap se start karne ke liye:

1. **Termux:Widget** F-Droid se install karo
2. Home screen pe long press
3. Widget > Termux:Widget > Termux Shortcut
4. "start_bot" select karo
5. Shortcut home screen pe aa jaayega

Ab sirf icon tap karo → Termux mein bot start + browser khulega.

---

## 📱 User Flow (Customer ke liye)

```
1. Customer phone pe bot ZIP receive karta hai
2. Termux install karta hai (F-Droid se)
3. Termux kholke: bash install_termux.sh
4. 5-10 min wait
5. bash start_bot.sh
6. Browser mein app khulta hai
7. "Add to Home Screen" → App icon ban jaata hai
8. Ab sirf icon tap karo → Bot start + App khule
```

---

## 🔧 Troubleshooting

### Q: "python: command not found"
```bash
pkg install python
```

### Q: "pip: command not found"
```bash
pkg install python
pip install --upgrade pip
```

### Q: "Port 5000 already in use"
```bash
pkill -f "python app.py"
bash ~/binance-futures-bot/start_bot.sh
```

### Q: Bot start nahi ho raha
```bash
cd ~/binance-futures-bot
python app.py
```
Error dekho aur fix karo.

### Q: Browser nahi khulta
```bash
pkg install termux-api
termux-open-url http://localhost:5000
```

### Q: Phone restart ke baad bot band ho gaya
```bash
bash ~/binance-futures-bot/start_bot.sh
```

---

## ⚠️ Important Notes

1. **Termux ko battery optimization se exclude karo** - Settings > Battery > Termux > No restrictions
2. **Phone restart pe bot band hoga** - manually start karna padega
3. **Internet zaroori hai** - WEEX/Binance API ke liye
4. **Storage** - 500MB free rakho (Python + dependencies)
5. **Termux:Boot** (optional) - phone start hone pe automatically bot start karne ke liye

---

## 🚀 Quick Summary

| Step | Command |
|------|---------|
| Install | `bash install_termux.sh` |
| Start | `bash start_bot.sh` |
| Stop | Ctrl+C (Termux mein) |
| App icon | Browser > Menu > Add to Home Screen |
