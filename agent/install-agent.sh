#!/bin/bash
# Instalace agenta na RPi – spustit po zkopírování složky agent do /opt/whiteboard-agent
# Použití: cd /opt/whiteboard-agent && sudo ./install-agent.sh

set -e

DEST="/opt/whiteboard-agent"
cd "$DEST"

echo "=== Instalace Whiteboard Agent ==="

# Config
if [ ! -f config.yaml ] && [ -f config.example.yaml ]; then
    echo "Vytvářím config.yaml z config.example.yaml..."
    cp config.example.yaml config.yaml
fi

# Cleanup bordel
if [ -f cleanup_agent.sh ]; then
    chmod +x cleanup_agent.sh
    ./cleanup_agent.sh || true
fi

# Systemd služby
echo ""
echo "Instaluji systemd služby..."
cp whiteboard-agent.service /etc/systemd/system/
cp libcamera-v4l2.service /etc/systemd/system/
systemctl daemon-reload

# libcamera-v4l2 – jen pokud binárka existuje (na Debian Trixie může chybět)
if [ -x /usr/bin/libcamera-v4l2 ]; then
    echo "Povoluji libcamera-v4l2 (CSI kamera pro opencv backend)..."
    systemctl enable libcamera-v4l2
    systemctl start libcamera-v4l2 || echo "  (libcamera-v4l2 selhal)"
else
    echo "libcamera-v4l2 binárka chybí – agent použije picamera2 backend (bez v4l2)"
    systemctl disable libcamera-v4l2 2>/dev/null || true
    systemctl stop libcamera-v4l2 2>/dev/null || true
fi

# Agent
echo "Povoluji whiteboard-agent..."
systemctl enable whiteboard-agent
systemctl restart whiteboard-agent

echo ""
echo "Hotovo. Status:"
systemctl status whiteboard-agent --no-pager
echo ""
systemctl status libcamera-v4l2 --no-pager 2>/dev/null || true
