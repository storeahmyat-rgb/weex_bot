# SaaS License Server Setup Guide

## 📋 Overview

Yeh system 2 parts pe based hai:

1. **Admin Server (Aapka Laptop)** - License keys manage karta hai
2. **Customer .exe** - Admin server se license validate karta hai

```
Customer .exe → Internet → Ngrok/Cloudflare → Aapka Laptop (License Server)
```

---

## 🚀 Admin Setup (Ek Baar)

### Step 1: Ngrok Install (Free)
1. https://ngrok.com pe jao → Sign up (free)
2. Download ngrok for Windows
3. ZIP extract karo
4. Command prompt kholo:
   ```
   ngrok config add-authtoken YOUR_TOKEN
   ```

### Alternative: Cloudflare Tunnel (Free, Stable URL)
1. https://github.com/cloudflare/cloudflared/releases/latest
2. `cloudflared-windows-amd64.exe` download karo
3. `cloudflared.exe` naam se save karo

### Step 2: License Server Start
```
start_server.bat
```

Yeh 2 cheezein start karega:
1. Flask license server (port 5001)
2. Ngrok/Cloudflare tunnel → Public URL

### Step 3: URL Note Karo
Ngrok/Cloudflare console mein ek URL dikhega:
```
https://abc123.ngrok.io
```
Yeh URL note karo - customer .exe mein yeh daalna hai.

### Step 4: Admin Panel Kholo
```
http://localhost:5001/admin
```
Password: `AdminBot@2024!Secure`

Yahan se license keys banate ho.

---

## 📦 Customer .exe Setup

### Step 1: URL Set Karo
`bot/license_client.py` mein ya `.license_server_url` file mein:
```
https://abc123.ngrok.io
```

Ya environment variable set karo:
```
set LICENSE_SERVER_URL=https://abc123.ngrok.io
```

Ya `.license_server_url` file banao aur URL likho:
```
echo https://abc123.ngrok.io > .license_server_url
```

### Step 2: .exe Build Karo
```
build_exe.bat
```

### Step 3: Customer Ko Dena Hai
1. `BinanceFuturesBot.exe` file
2. `.license_server_url` file (URL wali)
3. Ya dono ko ek ZIP mein bhejo

Customer .exe chalayega → License key maangega → Admin server se validate hoga.

---

## 📋 Customer Flow

```
1. Customer: .exe run karta hai
2. Bot: License key maangega
3. Customer: Aapse contact karta hai (WhatsApp/Telegram)
4. Aap: Admin panel se key banate ho (30 days)
5. Aap: Key customer ko bhejte ho
6. Customer: Key daalta hai
7. .exe: Aapke server (ngrok URL) pe check karta hai
8. Server: "Valid ✅" → Bot unlock
9. Server: "Invalid ❌" → Bot block
10. Customer: Apni API keys daalta hai → Trading start
```

---

## ⚠️ Important Notes

1. **Laptop on rakhna** - server ke liye aapka laptop on rakhna padega
2. **Internet zaroori** - aapka + customer dono ka
3. **Ngrok URL** restart pe change ho sakta hai (free tier)
4. **Cloudflare** stable URL deta hai (free)
5. **Admin password** change karo (`license_server.py` mein)
6. ** licenses_server.json** ka backup rakho

---

## 🔧 Troubleshooting

### Q: Customer ko "License server timeout" error
- Aapka laptop on hai?
- Ngrok/Cloudflare chal raha hai?
- URL sahi hai `.license_server_url` mein?

### Q: Ngrok URL change ho gaya restart pe
- Cloudflare use karo (stable URL)
- Ya ngrok paid ($8/mo) le lo

### Q: Customer ka .exe license accept nahi kar raha
- Key sahi hai?
- Key expire to nahi hui?
- Key revoke to nahi hui?
- HW ID match kar raha hai? (ek key = ek PC)

---

## 💰 Business Model

| Plan | Price | Duration |
|------|-------|----------|
| Trial | Free | 1 day |
| Weekly | 500 PKR | 7 days |
| Monthly | 1,500 PKR | 30 days |
| Quarterly | 4,000 PKR | 90 days |
| Lifetime | 25,000 PKR | Forever |

Aap admin panel se key banate ho → customer ko bechte ho → customer .exe se validate karta hai.
