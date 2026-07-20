#!/bin/bash
# ============================================
# TradeBot SaaS - One-Click Installer (Linux/Mac)
# ============================================
# Yeh script sab kuch install karta hai:
#   - Python check/install
#   - Bot dependencies
#   - Bot start
#
# Usage:
#   chmod +x install.sh
#   ./install.sh
# ============================================

set -e

echo "=========================================="
echo "  TradeBot SaaS - Linux/Mac Installer"
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

# Get script directory
cd "$(dirname "$0")"

# ============================================
# Step 1: Check Python
# ============================================
echo "Step 1/4: Python check kar rahe hain..."

if command -v python3 &> /dev/null; then
    PYVER=$(python3 --version 2>&1 | awk '{print $2}')
    print_step "Python $PYVER mila"
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYVER=$(python --version 2>&1 | awk '{print $2}')
    print_step "Python $PYVER mila"
    PYTHON=python
else
    print_warn "Python nahi mila. Install kar rahe hain..."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update -qq
        sudo apt-get install -y -qq python3 python3-pip
        PYTHON=python3
    elif command -v yum &> /dev/null; then
        sudo yum install -y -q python3 python3-pip
        PYTHON=python3
    elif command -v brew &> /dev/null; then
        brew install python
        PYTHON=python3
    else
        print_err "Python install nahi ho saka. Manually install karo:"
        echo "  Ubuntu/Debian: sudo apt install python3 python3-pip"
        echo "  CentOS/RHEL:  sudo yum install python3 python3-pip"
        echo "  Mac:           brew install python"
        exit 1
    fi
    print_step "Python installed"
fi

# ============================================
# Step 2: Install bot dependencies
# ============================================
echo ""
echo "Step 2/4: Bot dependencies install kar rahe hain..."
echo "  (Yeh 2-5 minute lag sakta hai, please wait...)"

$PYTHON -m pip install -r requirements.txt --quiet 2>&1 | tail -3 || {
    print_warn "Kuch packages install nahi hue. Trying with --user..."
    $PYTHON -m pip install --user -r requirements.txt --quiet 2>&1 | tail -3
}
print_step "Dependencies installed"

# ============================================
# Step 3: Admin password
# ============================================
echo ""
echo "Step 3/4: Admin password set kar rahe hain..."

if [ ! -f ".admin_password.txt" ]; then
    echo "AdminBot@2024!" > .admin_password.txt
    print_step "Default admin password set: AdminBot@2024!"
    print_warn "Change karne ke liye .admin_password.txt edit karo"
else
    print_step "Admin password already exists"
fi

# Set environment variable
export ADMIN_SECRET=$(cat .admin_password.txt 2>/dev/null || echo "AdminBot@2024!")

# ============================================
# Step 4: Start bot
# ============================================
echo ""
echo "Step 4/4: Bot start kar rahe hain..."
echo ""
echo "=========================================="
echo "  Installation Complete!"
echo "=========================================="
echo ""
echo "  Bot URL:        http://localhost:5000"
echo "  Admin Panel:    http://localhost:5000/admin"
echo "  Admin Password: $ADMIN_SECRET"
echo ""
echo "  Browser automatically open hoga 3 seconds mein..."
echo ""
echo "  Bot band karne ke liye: Ctrl+C"
echo "=========================================="
echo ""

# Open browser (if possible)
sleep 3
if command -v xdg-open &> /dev/null; then
    xdg-open http://localhost:5000 2>/dev/null &
elif command -v open &> /dev/null; then
    open http://localhost:5000 2>/dev/null &
fi

# Start bot
exec $PYTHON app.py
