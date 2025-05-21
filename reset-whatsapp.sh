#!/bin/bash
# Script to reset WhatsApp client for relogin or changing phone number

# Display banner
echo "==========================================="
echo "  WhatsApp Client Reset Utility"
echo "==========================================="
echo "This script will help you reset your WhatsApp client"
echo "for relogin or switching to a different phone number."

# Define colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to print colored status messages
print_status() {
    echo -e "${YELLOW}[*]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[+]${NC} $1"
}

print_error() {
    echo -e "${RED}[!]${NC} $1"
}

# Ask for confirmation
echo
echo "WARNING: This will delete your current WhatsApp session,"
echo "and you will need to scan a new QR code to reconnect."
echo
read -p "Do you want to continue? (y/n): " confirm

if [[ $confirm != [yY] && $confirm != [yY][eE][sS] ]]; then
    print_status "Operation cancelled."
    exit 0
fi

# 1. Stop the WhatsApp client service
print_status "Stopping WhatsApp client service..."
sudo systemctl stop whatsapp-client
if [ $? -eq 0 ]; then
    print_success "WhatsApp client service stopped."
else
    print_error "Failed to stop WhatsApp client service."
    exit 1
fi

# 2. Back up the session directory
SESSION_DIR="$HOME/whatsapp-rag/whatsapp-sessions"
BACKUP_DIR="$HOME/whatsapp-rag/whatsapp-sessions-backup-$(date +%Y%m%d_%H%M%S)"

print_status "Backing up session files to $BACKUP_DIR..."
if [ -d "$SESSION_DIR" ]; then
    mkdir -p "$BACKUP_DIR"
    cp -r "$SESSION_DIR"/* "$BACKUP_DIR"/ 2>/dev/null
    print_success "Session files backed up."
else
    print_status "No session directory found. Nothing to back up."
fi

# 3. Delete the session files
print_status "Deleting WhatsApp session files..."
rm -rf "$SESSION_DIR"
mkdir -p "$SESSION_DIR"
print_success "Session files deleted and directory recreated."

# 4. Restart the service
print_status "Restarting WhatsApp client service..."
sudo systemctl restart whatsapp-client
if [ $? -eq 0 ]; then
    print_success "WhatsApp client service restarted."
else
    print_error "Failed to restart WhatsApp client service."
    exit 1
fi

# 5. Show service status and instructions
print_status "Checking service status..."
sudo systemctl status whatsapp-client --no-pager

echo
echo "==========================================="
print_success "Reset completed successfully!"
echo "==========================================="
echo 
echo "To complete the process:"
echo "1. Check the WhatsApp client logs to see the QR code:"
echo "   sudo journalctl -fu whatsapp-client"
echo
echo "2. Scan the QR code with your WhatsApp mobile app:"
echo "   - Open WhatsApp on your phone"
echo "   - Go to Settings > Linked Devices > Link a Device"
echo "   - Scan the QR code displayed in the logs"
echo
echo "If you need to revert back to your previous session, run:"
echo "sudo systemctl stop whatsapp-client"
echo "rm -rf $SESSION_DIR/*"
echo "cp -r $BACKUP_DIR/* $SESSION_DIR/"
echo "sudo systemctl start whatsapp-client"
echo
