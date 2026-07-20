#!/bin/bash
# ============================================
# TradeBot Cloud SaaS - One-Click Server Installer
# ============================================
# Yeh script sab kuch install karta hai:
#   - Python 3 + pip
#   - Bot dependencies
#   - Auto-start with PM2 (24/7 chalna ke liye)
#   - Cloudflare tunnel (optional, for public URL)
#
# Usage:
#   chmod +x install.sh
#   ./install.sh
# ============================================

set -e

echo "=========================================="
echo "  TradeBot Cloud SaaS - Installer"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_step() { echo -e "${GREEN}[✓]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
print_err() { echo -e "${RED}[✗]${NC} $1"; }

cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"

# ============================================
# Step 1: Install Python + system deps
# ============================================
echo "Step 1/5: System dependencies install kar rahe hain..."

if command -v apt-get &> /dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3 python3-pip curl > /dev/null 2>&1
    print_step "Python3 + pip installed (Ubuntu/Debian)"
elif command -v yum &> /dev/null; then
    sudo yum install -y -q python3 python3-pip curl > /dev/null 2>&1
    print_step "Python3 + pip installed (CentOS/RHEL)"
elif command -v brew &> /dev/null; then
    brew install python curl > /dev/null 2>&1
    print_step "Python3 installed (macOS)"
else
    print_warn "Could not detect package manager. Assuming Python3 is installed."
fi

# ============================================
# Step 2: Install PM2 (for 24/7 auto-restart)
# ============================================
echo ""
echo "Step 2/5: PM2 install kar rahe hain (24/7 auto-restart ke liye)..."

if ! command -v pm2 &> /dev/null; then
    if ! command -v npm &> /dev/null; then
        if command -v apt-get &> /dev/null; then
            curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash - > /dev/null 2>&1
            sudo apt-get install -y -qq nodejs > /dev/null 2>&1
        elif command -v yum &> /dev/null; then
            curl -fsSL https://rpm.nodesource.com/setup_18.x | sudo bash - > /dev/null 2>&1
            sudo yum install -y -q nodejs > /dev/null 2>&1
        fi
    fi
    sudo npm install -g pm2 > /dev/null 2>&1
    print_step "PM2 installed"
else
    print_step "PM2 already installed"
fi

# ============================================
# Step 3: Install Python bot dependencies
# ============================================
echo ""
echo "Step 3/5: Bot dependencies install kar rahe hain..."

cd "$SCRIPT_DIR/bot-engine"
pip3 install -r requirements.txt --quiet --break-system-packages 2>&1 | tail -3 || {
    pip3 install -r requirements.txt --quiet 2>&1 | tail -3
}
print_step "Bot dependencies installed"

# ============================================
# Step 4: Generate secrets + config
# ============================================
echo ""
echo "Step 4/5: Secrets generate kar rahe hain..."

# Generate strong secrets
JWT_SECRET=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")
ENCRYPTION_KEY=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")

# Create .env file
cat > "$SCRIPT_DIR/.env" << EOF
# TradeBot Cloud SaaS - Environment Variables
# Yeh file automatically generate hui hai. Edit na karein.

FLASK_SECRET=$JWT_SECRET
ENCRYPTION_KEY=$ENCRYPTION_KEY
ADMIN_SECRET=AdminBot@2024!
TRIAL_DAYS=7
PORT=5000
HOST=0.0.0.0
EOF

print_step "Secrets generated (.env file created)"
print_warn "Admin password: AdminBot@2024! (change it later via env var)"

# ============================================
# Step 5: Start with PM2
# ============================================
echo ""
echo "Step 5/5: Server start kar rahe hain (PM2 ke saath)..."

cd "$SCRIPT_DIR"

# Stop existing process if any
pm2 delete tradebot-cloud > /dev/null 2>&1 || true

# Load env vars
export $(cat .env | xargs)

# Start with PM2
pm2 start "python3 app.py" --name tradebot-cloud --cwd "$SCRIPT_DIR" > /dev/null 2>&1
pm2 save > /dev/null 2>&1

# Setup auto-restart on server reboot
pm2 startup > /dev/null 2>&1 || true

print_step "Server started with PM2"

# ============================================
# Done!
# ============================================
echo ""
echo "=========================================="
echo "  ✅ Installation Complete!"
echo "=========================================="
echo ""
echo "Your TradeBot Cloud SaaS is running at:"
SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "  http://localhost:5000"
echo "  http://$SERVER_IP:5000"
echo ""
echo "Admin Panel:"
echo "  http://$SERVER_IP:5000/admin"
echo "  Admin Password: AdminBot@2024!"
echo ""
echo "First user jo signup karega woh ADMIN ban jayega."
echo "Phir admin dusre users ko manage kar sakta hai."
echo ""
echo "Useful PM2 commands:"
echo "  pm2 status                  - Check status"
echo "  pm2 logs tradebot-cloud     - View logs"
echo "  pm2 restart tradebot-cloud  - Restart"
echo "  pm2 stop tradebot-cloud     - Stop"
echo ""
echo "=== Public URL setup (optional) ==="
echo "Cloudflare tunnel chalane ke liye:"
echo "  cloudflared tunnel --url http://localhost:5000"
echo ""
echo "Yeh ek public URL dega jaise: https://random-words.trycloudflare.com"
echo "Users ko yeh URL bhejo, woh browser se login karenge."
echo "=========================================="
