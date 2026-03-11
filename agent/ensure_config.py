#!/usr/bin/env python3
"""Zajistí, že config má live_server.enabled: true. Spustit na RPi po instalaci."""
import os
import sys

cfg_path = os.environ.get("WHITEBOARD_AGENT_CONFIG", "/opt/whiteboard-agent/config.yaml")

try:
    import yaml
except ImportError:
    print("yaml chybí", file=sys.stderr)
    sys.exit(1)

if not os.path.exists(cfg_path):
    print(f"Config neexistuje: {cfg_path}", file=sys.stderr)
    sys.exit(1)

with open(cfg_path, "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

live = cfg.setdefault("live_server", {})
changed = False
if live.get("enabled") is not True:
    live["enabled"] = True
    changed = True
if live.get("port") is None:
    live["port"] = 8081
    changed = True
if live.get("bind") is None:
    live["bind"] = "0.0.0.0"
    changed = True

if changed:
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print("Config upraven: live_server.enabled=true")
else:
    print("Config OK")
