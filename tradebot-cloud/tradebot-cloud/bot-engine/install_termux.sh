#!/data/data/com.termux/files/usr/bin/bash
# ============================================================
# Binance Futures Bot - Termux Auto Installer
# Run: bash install_termux.sh
# ============================================================
set -e

echo "================================================"
echo "  Binance Futures Bot - Termux Setup"
echo "================================================"
echo ""

# Step 1: Update Termux packages
echo "[1/6] Termux packages update ho rahe hain..."
pkg update -y && pkg upgrade -y
echo "✅ Packages updated"

# Step 2: Install Python
echo ""
echo "[2/6] Python install ho raha hai..."
pkg install -y python
echo "✅ Python installed: $(python --version)"

# Step 3: Install dependencies
echo ""
echo "[3/6] Bot dependencies install ho rahe hain..."
pip install --upgrade pip
pip install flask flask-socketio simple-websocket python-engineio python-socketio
pip install pandas numpy pyarrow
pip install binance-futures-connector python-binance
pip install requests python-dotenv
echo "✅ Dependencies installed"

# Step 4: Install Termux:API (for opening browser)
echo ""
echo "[4/6] Termux:API tools install ho rahe hain..."
pkg install -y termux-api
echo "✅ Termux:API installed"

# Step 5: Create bot directory
echo ""
echo "[5/6] Bot folder ban raha hai..."
mkdir -p ~/binance-futures-bot
BOT_DIR=~/binance-futures-bot

# Check if bot code already exists
if [ -f "$BOT_DIR/app.py" ]; then
    echo "✅ Bot code already exists at $BOT_DIR"
else
    echo "⚠️ Bot code nahi mila. Please bot ZIP ko extract karo:"
    echo "   1. ZIP file ko Download folder mein rakho"
    echo "   2. Phir yeh command chalao:"
    echo "      cp ~/storage/downloads/binance-futures-bot/* $BOT_DIR/"
    echo ""
    echo "   Ya Git se clone karo (agar GitHub pe hai):"
    echo "      pkg install git"
    echo "      git clone <your-repo-url> $BOT_DIR"
    echo ""
    echo "   Setup complete hone ke baad start_bot.sh chalao."
fi

# Step 6: Create start script
echo ""
echo "[6/6] Start script ban raha hai..."
cat > ~/binance-futures-bot/start_bot.sh << 'STARTEOF'
#!/data/data/com.termux/files/usr/bin/bash
# Start bot and open browser
cd ~/binance-futures-bot

echo "Bot start ho raha hai..."
echo "Browser mein http://localhost:5000 kholo"
echo "Press Ctrl+C to stop"
echo ""

# Start Flask server in background
python app.py &
BOT_PID=$!

# Wait for server to start
sleep 3

# Open browser
termux-open-url http://localhost:5000

# Wait for bot process
wait $BOT_PID
STARTEOF
chmod +x ~/binance-futures-bot/start_bot.sh

# Create home screen shortcut
cat > ~/.shortcuts/start_bot << 'SHORTCUTEOF'
~/binance-futures-bot/start_bot.sh
SHORTCUTEOF
chmod +x ~/.shortcuts/start_bot 2>/dev/null || true

echo ""
echo "================================================"
echo "  ✅ SETUP COMPLETE!"
echo "================================================"
echo ""
echo "Bot start karne ke liye:"
echo "  bash ~/binance-futures-bot/start_bot.sh"
echo ""
echo "Ya Termux:Widget se home screen pe shortcut add karo:"
echo "  1. Home screen pe long press"
echo "  2. Widget > Termux:Widget > Termux Shortcut"
echo "  3. 'start_bot' select karo"
echo ""
echo "Phone pe app jaisa dikhega - 'Add to Home Screen' karo"
echo "browser mein http://localhost:5000 kholne ke baad."
echo ""
