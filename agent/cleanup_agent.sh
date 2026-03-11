#!/bin/bash
# Vyčistí bordel v /opt/whiteboard-agent – spustit na RPi: sudo ./cleanup_agent.sh
# Odstraní náhodně vytvořené soubory (HTTP hlavičky, překlepy) a opraví oprávnění

set -e
cd /opt/whiteboard-agent

echo "=== Čištění /opt/whiteboard-agent ==="

# Odstranit zmetky (HTTP hlavičky, překlepy)
for f in "Accept:" "Authorization:" "Content-Length:" "Content-Type:" "Host:" "POST" "User-Agent:" "'udo systemctl stop whiteboard-agent'"; do
    [ -e "$f" ] && rm -v "$f" || true
done

# Opravit vlastníka na cam (služba běží jako cam)
echo ""
echo "Opravuji vlastníka souborů na cam:cam..."
chown -R cam:cam /opt/whiteboard-agent
chown cam:cam /opt/whiteboard-agent/config.yaml 2>/dev/null || true

echo ""
echo "Hotovo. Zkontroluj: ls -la"
