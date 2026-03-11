#!/bin/bash
# Spustit na RPi po SSH: bash fix_config.sh

set -e

CFG="/opt/whiteboard-agent/config.yaml"
EXAMPLE="/opt/whiteboard-agent/config.example.yaml"

echo "=== Whiteboard Agent – diagnostika configu ==="
echo ""

echo "1. Cesta k configu: /opt/whiteboard-agent/config.yaml"
echo ""

if [ -f "$CFG" ]; then
    echo "2. Config EXISTUJE: $CFG"
    echo ""
    echo "--- Obsah ---"
    cat "$CFG"
    echo ""
    echo "--- live_server sekce ---"
    grep -A5 "live_server" "$CFG" 2>/dev/null || echo "(sekce live_server chybí)"
else
    echo "2. Config NEEXISTUJE: $CFG"
    echo ""
    if [ -f "$EXAMPLE" ]; then
        echo "Kopíruji z config.example.yaml..."
        cp "$EXAMPLE" "$CFG"
        echo "Config vytvořen. Uprav: nano $CFG"
    else
        echo "Chyba: config.example.yaml chybí v /opt/whiteboard-agent/"
        echo "Spusť deploy z vývojového stroje."
        exit 1
    fi
fi

echo ""
echo "3. Soubory v /opt/whiteboard-agent:"
ls -la /opt/whiteboard-agent/*.yaml /opt/whiteboard-agent/*.py 2>/dev/null || true
ls -la /opt/whiteboard-agent/data/ 2>/dev/null || echo "  data/ zatím neexistuje"

echo ""
echo "4. Co běží na portu 8081:"
sudo lsof -i :8081 2>/dev/null || echo "  (nic)"

echo ""
echo "5. Status služby:"
sudo systemctl status whiteboard-agent --no-pager 2>/dev/null || echo "  Služba neexistuje nebo neběží"
