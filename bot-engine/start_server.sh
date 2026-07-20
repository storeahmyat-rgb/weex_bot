#!/bin/bash
# ============================================================
# Start License Server + Tunnel (Linux/Mac)
# ============================================================
cd "$(dirname "$0")"

echo "================================================"
echo " License Server Starting (SaaS Mode)"
echo "================================================"
echo ""

# Step 1: Start Flask license server in background
echo "[1/2] License server starting (port 5001)..."
python3 license_server.py &
SERVER_PID=$!
sleep 3

# Step 2: Start tunnel
echo "[2/2] Starting tunnel..."
echo ""

# Try cloudflared first (free, stable URL)
if command -v cloudflared &> /dev/null; then
    echo "Using Cloudflare Tunnel (free, stable URL)..."
    echo "================================================"
    echo " Server Live!"
    echo "================================================"
    echo ""
    echo " Admin Panel: http://localhost:5001/admin"
    echo " Cloudflare URL: check below"
    echo ""
    echo " Customer .exe mein Cloudflare URL daalna hai"
    echo " (bot/license_client.py mein LICENSE_SERVER_URL)"
    echo ""
    cloudflared tunnel --url http://localhost:5001
# Try ngrok
elif command -v ngrok &> /dev/null; then
    echo "Using Ngrok..."
    echo "================================================"
    echo " Server Live!"
    echo "================================================"
    echo ""
    echo " Admin Panel: http://localhost:5001/admin"
    echo " Ngrok URL: check below"
    echo ""
    ngrok http 5001
else
    echo "[WARNING] Neither cloudflared nor ngrok installed."
    echo ""
    echo "Install one of:"
    echo "  Cloudflare: https://github.com/cloudflare/cloudflared/releases"
    echo "  Ngrok: https://ngrok.com/download"
    echo ""
    echo "Server running on localhost:5001"
    echo "Admin panel: http://localhost:5001/admin"
    echo ""
    echo "Press Ctrl+C to stop"
    wait $SERVER_PID
fi
