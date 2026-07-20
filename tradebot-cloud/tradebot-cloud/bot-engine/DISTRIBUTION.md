# Binance Futures Bot - Distribution Guide

Is document mein aap seekhenge:
1. Apna admin password kaise set karein
2. .exe file kaise banayein
3. Customers ko kaise distribute karein
4. License keys kaise manage karein

---

## Step 1: Admin Password Set Karein (ZAROORI)

`bot/secret.py` file kholo aur yeh line dhundo:

```python
_ADMIN_PASSWORD_DEFAULT = "AdminBot@2024!Secure"
```

Apna strong password daalo, e.g.:
```python
_ADMIN_PASSWORD_DEFAULT = "MySecretAdmin2024!@#"
```

**Zaroori:** Yeh password admin panel (`/admin`) ko protect karta hai. Strong rakho!

---

## Step 2: .exe File Banao

### Windows Pe:

1. Python 3.9+ install karo (https://python.org)
2. Bot folder mein jao
3. `build_exe.bat` file double-click karo
4. 5-10 minute wait karo
5. `dist\BinanceFuturesBot.exe` file ban jayegi

### Build Process Kya Karta Hai:

1. ✅ PyInstaller install karta hai
2. ✅ PyArmor install karta hai (code obfuscation ke liye)
3. ✅ App dependencies install karta hai
4. ✅ Sensitive code ko obfuscate karta hai (admin password hidden)
5. ✅ Single .exe file banata hai (~150MB)
6. ✅ Cleanup karta hai

---

## Step 3: Customer Ko Kya Dena Hai

### Customer Package:
```
BinanceFuturesBot.exe  (sirf yeh file!)
```

**Source code MAT do!** Sirf .exe file do. Source code mein admin password hai.

### Customer Ko Instructions:

```
BinanceFuturesBot.exe ko double-click karein
↓
Firewall "Allow access" dabayein
↓
Browser khol ke http://localhost:5000 jayein
↓
Login page khulega - License key maangega
↓
Aapse li hui License key daalein
↓
Bot dashboard khul jayega
↓
Apni Binance API keys configure karein
↓
Trading start!
```

---

## Step 4: License Keys Manage Karne

### Admin Panel Kholo:
1. Bot start karo (`BinanceFuturesBot.exe`)
2. Browser mein `http://localhost:5000/admin` kholo
3. Apna admin password daalo

### Naya Customer Ko License Dena:

1. Admin panel mein "➕ Naya License Key Banao" section
2. Plan select karo:
   - 1 Day (Trial)
   - 7 Days
   - 30 Days (1 Month) - most common
   - 90 Days (3 Months)
   - 180 Days (6 Months)
   - 365 Days (1 Year)
   - Lifetime
3. Note field mein customer ka naam/phone daalo (optional)
4. "Create Key" dabao
5. Key copy ho jayegi (format: `TRDBOT-XXXX-XXXX-XXXX-XXXX`)
6. Yeh key customer ko bhej do

### Customer Renew Karna:

1. Admin panel mein "⏰ License Extend Karo" section
2. Customer ki key daalo
3. Extra days daalo (e.g. 30)
4. "Extend" dabao
5. Customer ki license extend ho jayegi

### Customer Block Karna (Refund/Dispute):

1. Admin panel mein keys table mein us customer ki row dhundo
2. "Revoke" button dabao
3. Customer ka access turant block ho jayega

---

## Security Features

### 1. Code Obfuscation (PyArmor)
- Admin password encrypted hai
- License logic encrypted hai
- Users source code dekh nahi sakte

### 2. Encrypted License Database
- `licenses.dat` file AES-256 se encrypted hai
- Users isay edit nahi kar sakte
- Fake license add nahi kar sakte

### 3. Hardware ID Lock
- Ek license sirf ek PC pe chalti hai
- Customer dusre PC pe try kare to block
- PC change karna hai to admin se contact

### 4. Anti-Tamper Detection
- Bot detect karta hai agar files modify ki gayin
- Debugger attach hone pe warning
- Encrypted file tamper hone pe block

### 5. Admin Password Protection
- Admin panel password protected
- Password obfuscated code mein
- Bina password ke admin access nahi

---

## Common Issues

### Q: .exe build fail ho raha hai?
**A:**
- Python 3.9+ check karo
- Antivirus temporarily disable karo
- `pip install pyinstaller pyarmor` manually chalao
- `pyinstaller binance_bot.spec --noconfirm` manually chalao

### Q: Customer bol raha hai "license invalid"?
**A:**
- Admin panel se check karo key exists karti hai ya nahi
- Check karo revoked to nahi
- Check karo expired to nahi
- Customer ka HW ID change nahi hua (PC change)

### Q: Customer ne PC change kar li?
**A:**
- Pehli key revoke karo
- Nayi key banao (ya extend karo)
- Customer ko nayi key bhej do

### Q: Customer license share kar raha hai dusron ke saath?
**A:**
- Hardware ID lock se ek license ek PC pe
- Agar phir bhi issue, key revoke kar do
- Naya customer ko nayi key bech do

### Q: Admin password bhool gaya?
**A:**
- `bot/secret.py` kholo (agar source code hai)
- Naya password set karo
- .exe rebuild karo
- Customers ko nayi .exe do (licenses preserve rahenge)

---

## Pricing Suggestions

| Plan | Price (PKR) | Days |
|------|-------------|------|
| Trial | Free | 1 |
| Weekly | 500 | 7 |
| Monthly | 1,500 | 30 |
| Quarterly | 4,000 | 90 |
| Half-Year | 7,000 | 180 |
| Yearly | 12,000 | 365 |
| Lifetime | 25,000 | 9999 |

*Yeh sirf suggestions hain - apne hisaab se adjust karo.*

---

## Important Notes

1. **Source code kabhi share mat karo** - sirf .exe file do
2. **Admin password strong rakho** - 12+ characters
3. **licenses.dat ka backup rakho** - yeh aapke paise hain
4. **Build se pehle secret.py change karo** - default password nahi
5. **Customer support ke liye note field use karo** - naam/phone likho
6. **Regular backups lo** - licenses.dat aur config.json

---

## Quick Reference

| Kya Karna Hai | Kaise |
|---------------|-------|
| Admin panel | http://localhost:5000/admin |
| Bot dashboard | http://localhost:5000 |
| Default admin pass | `AdminBot@2024!Secure` (CHANGE IT!) |
| Build .exe | Run `build_exe.bat` |
| Customer ko dena | Sirf `BinanceFuturesBot.exe` |
| License generate | Admin panel → Create Key |
| License block | Admin panel → Revoke |
| License extend | Admin panel → Extend |

Bas! Ab aap commercial-ready ho. License becho, paise kamao! 💰
