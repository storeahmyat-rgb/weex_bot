#!/bin/bash
# ============================================
# TradeBot SaaS - Linux/Mac Launcher
# ============================================
# Yeh file bot ko start karti hai.
# Pehli baar install ke liye: ./install.sh chalao.
# ============================================

cd "$(dirname "$0")"

echo "================================"
echo " TradeBot SaaS - Starting"
echo "================================"

# Activate venv if exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Check dependencies
python3 -c "import flask, flask_socketio, pandas, numpy" 2>/dev/null || python -c "import flask, flask_socketio, pandas, numpy" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Installing dependencies..."
    pip3 install -r requirements.txt 2>/dev/null || pip install -r requirements.txt
fi

# Load admin password from file (if exists)
if [ -f ".admin_password.txt" ]; then
    export ADMIN_SECRET=$(cat .admin_password.txt | tr -d '[:space:]')
fi

# Start the bot
echo ""
echo "Bot URL:        http://localhost:5000"
echo "Admin Panel:    http://localhost:5000/admin"
if [ -n "$ADMIN_SECRET" ]; then
    echo "Admin Password: $ADMIN_SECRET"
else
    echo "Admin Password: AdminBot@2024! (default)"
fi
echo ""
echo "Press Ctrl+C to stop"
echo "================================"
echo ""

# Open browser after 3 seconds (if possible)
(sleep 3 && (xdg-open http://localhost:5000 2>/dev/null || open http://localhost:5000 2>/dev/null) &)

# Start bot
python3 app.py 2>/dev/null || python app.py
