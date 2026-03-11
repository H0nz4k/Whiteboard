#!/bin/bash
# Spustit na zařízení po deploy – překopíruje z /tmp do /opt a restartuje službu
# Použití: sudo ./install.sh [agent|hub]

set -e

case "${1:-}" in
    agent)
        TEMP="/tmp/whiteboard-agent-deploy"
        DEST="/opt/whiteboard-agent"
        SVC="whiteboard-agent"
        ;;
    hub)
        TEMP="/tmp/whiteboard-hub-deploy"
        DEST="/opt/whiteboard-hub"
        SVC="whiteboard-hub"
        ;;
    *)
        echo "Použití: sudo $0 agent|hub"
        exit 1
        ;;
esac

if [ ! -d "$TEMP" ]; then
    echo "Chyba: $TEMP neexistuje. Nejdřív spusť deploy.sh z vývojového stroje."
    exit 1
fi

echo "Kopíruji $TEMP -> $DEST ..."
rsync -a "$TEMP/" "$DEST/"

echo "Restartuji $SVC ..."
systemctl restart "$SVC"

echo "Hotovo. Status:"
systemctl status "$SVC" --no-pager
