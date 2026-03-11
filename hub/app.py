#!/usr/bin/env python3
import os, sys, json, yaml, shutil, datetime as dt, subprocess
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError
from urllib.parse import quote
from flask import Flask, request, abort, send_from_directory, render_template, Response, jsonify

def _cfg_path():
    p = os.environ.get("WHITEBOARD_HUB_CONFIG")
    app_dir = Path(__file__).parent.resolve()
    # Fallback: /etc/whiteboard-hub nemá hub oprávnění – použij /opt/whiteboard-hub/
    if p and "/etc/whiteboard-hub" in p:
        return str(app_dir / "config.yaml")
    if p:
        return p
    # Výchozí: config vedle app.py v /opt/whiteboard-hub/
    return str(app_dir / "config.yaml")

def _ensure_config_exists():
    """Při prvním startu zkopíruje config.example.yaml → config.yaml, pokud config.yaml neexistuje."""
    p = Path(_cfg_path())
    if p.exists():
        return
    example = p.parent / "config.example.yaml"
    if example.exists():
        shutil.copy2(example, p)
        print(f"[hub] Config vytvořen z {example.name}", file=sys.stderr)

def load_cfg():
    _ensure_config_exists()
    p = _cfg_path()
    default = {
        "server": {"host": "0.0.0.0", "port": 8099},
        "auth": {"token": ""},
        "storage": {"base_dir": os.path.join(os.path.dirname(__file__), "data"), "keep_days": 30},
        "live": {"rpi_url": "http://192.168.1.19:8081"},
        "sms": {
            "enabled": True,
            "base_url": "",
            "message": "Změna na tabuli {datetime}: {url}",
            "numbers": [],
            "time_from": None,
            "time_to": None,
            "daily_limit": 0,
            "trigger": "change",
            "send_script": "/opt/sms/send.sh",
        },
    }
    if not os.path.exists(p):
        return default
    with open(p, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    # Fallback: /etc/whiteboard-hub nemá hub oprávnění – použij /opt/whiteboard-hub/
    base_dir = (cfg.get("storage") or {}).get("base_dir") or ""
    if "/etc/whiteboard-hub" in base_dir:
        cfg.setdefault("storage", {})["base_dir"] = str(Path(__file__).parent.resolve() / "data")
    for k, v in default.items():
        if k not in cfg:
            cfg[k] = v
        elif k == "sms" and isinstance(cfg[k], dict):
            for sk, sv in default[k].items():
                if sk not in cfg[k]:
                    cfg[k][sk] = sv
    return cfg

class _QuotedStr(str):
    """Wrapper pro vynucení uvozovek v YAML výstupu (time_from, time_to)."""

def _yaml_quoted_str(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style="'")

def save_cfg(cfg):
    p = Path(_cfg_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    cfg = dict(cfg)
    sms = dict(cfg.get("sms") or {})
    for k in ("time_from", "time_to"):
        v = sms.get(k)
        if v and str(v).strip():
            sms[k] = _QuotedStr(str(v).strip())
    cfg["sms"] = sms
    yaml.add_representer(_QuotedStr, _yaml_quoted_str, Dumper=yaml.SafeDumper)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False, Dumper=yaml.SafeDumper)

def _sms_stats_path(cfg):
    base = Path(cfg["storage"]["base_dir"])
    base.mkdir(parents=True, exist_ok=True)
    return base / "sms_stats.json"

def _load_sms_stats(cfg):
    p = _sms_stats_path(cfg)
    if not p.exists():
        return {"total": 0, "by_date": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"total": 0, "by_date": {}}

def _save_sms_stats(cfg, stats):
    _sms_stats_path(cfg).write_text(json.dumps(stats, ensure_ascii=False), encoding="utf-8")

def _sms_count_today(stats):
    today = dt.datetime.now().strftime("%Y-%m-%d")
    return stats.get("by_date", {}).get(today, 0)

def _increment_sms_counter(cfg):
    stats = _load_sms_stats(cfg)
    stats["total"] = stats.get("total", 0) + 1
    today = dt.datetime.now().strftime("%Y-%m-%d")
    by_date = stats.get("by_date", {})
    by_date[today] = by_date.get(today, 0) + 1
    stats["by_date"] = by_date
    _save_sms_stats(cfg, stats)

app = Flask(__name__, template_folder="templates", static_folder="static")

def format_ts(ts_str):
    """Formátuje ISO timestamp na čitelný český formát."""
    if not ts_str:
        return ""
    try:
        d = dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return d.strftime("%d. %m. %Y %H:%M:%S")
    except (ValueError, TypeError):
        return ts_str

app.jinja_env.filters["format_ts"] = format_ts

def get_version():
    p = Path(__file__).parent / "VERSION"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return "?"

def auth_ok(cfg):
    token = cfg.get("auth", {}).get("token", "")
    if not token:
        return True
    h = request.headers.get("Authorization", "")
    if h.startswith("Bearer "):
        return h.split(" ", 1)[1].strip() == token
    return False

def _parse_time(s):
    """Vrátí (hodiny, minuty) nebo None při chybě."""
    if not s or not s.strip():
        return None
    try:
        parts = s.strip().split(":")
        h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        if 0 <= h <= 23 and 0 <= m <= 59:
            return (h, m)
    except (ValueError, IndexError):
        pass
    return None

def _in_time_range(time_from, time_to):
    """True pokud aktuální čas je v rozsahu time_from–time_to (HH:MM)."""
    t_from = _parse_time(time_from)
    t_to = _parse_time(time_to)
    if t_from is None and t_to is None:
        return True
    now = dt.datetime.now()
    now_min = now.hour * 60 + now.minute
    if t_from is not None:
        from_min = t_from[0] * 60 + t_from[1]
        if t_to is not None:
            to_min = t_to[0] * 60 + t_to[1]
            if from_min <= to_min:
                return from_min <= now_min <= to_min
            return now_min >= from_min or now_min <= to_min
        return now_min >= from_min
    if t_to is not None:
        to_min = t_to[0] * 60 + t_to[1]
        return now_min <= to_min
    return True

def _format_datetime(ts_str):
    """Formátuje ISO timestamp na dd.mm.rrrr hh:mm."""
    if not ts_str:
        return dt.datetime.now().strftime("%d.%m.%Y %H:%M")
    try:
        d = dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return d.strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return dt.datetime.now().strftime("%d.%m.%Y %H:%M")

def _send_sms(cfg, message_tpl, url, datetime_str, skip_checks=False):
    """Společná logika pro odeslání SMS. skip_checks=True = testovací zpráva."""
    sms = cfg.get("sms", {})
    numbers = sms.get("numbers") or []
    if not numbers:
        return False, "sms.numbers je prázdné"
    if not skip_checks and not sms.get("enabled", True):
        return False, "SMS je vypnuto"
    if not skip_checks:
        base_url = (sms.get("base_url") or "").rstrip("/")
        if not base_url:
            return False, "sms.base_url není nastaveno"
        if not _in_time_range(sms.get("time_from"), sms.get("time_to")):
            return False, "mimo povolenou dobu odesílání"
        stats = _load_sms_stats(cfg)
        daily_limit = int(sms.get("daily_limit") or 0)
        numbers = sms.get("numbers") or []
        num_count = len([n for n in numbers if str(n).strip()])
        effective_limit = daily_limit * max(1, num_count) if daily_limit > 0 else 0
        if effective_limit > 0 and _sms_count_today(stats) >= effective_limit:
            return False, f"denní limit {daily_limit}/číslo dosažen"
    text = (message_tpl.replace("{url}", url or "(test)").replace("{datetime}", datetime_str))
    send_script = sms.get("send_script") or ""
    if not send_script or not os.path.isfile(send_script):
        for p in ["/opt/sms_mail/send.sh", "/opt/sms/send.sh"]:
            if os.path.isfile(p):
                send_script = p
                break
    if not send_script or not os.path.isfile(send_script):
        return False, f"send script neexistuje: {send_script or '/opt/sms/send.sh'}"
    errs = []
    for num in numbers:
        num = str(num).strip()
        if not num:
            continue
        if not num.startswith("+"):
            num = "+420" + num.lstrip("0") if num.startswith("0") else "+420" + num
        try:
            r = subprocess.run([send_script, num, text], capture_output=True, timeout=30, text=True)
            if r.returncode != 0:
                errs.append(f"{num}: exit {r.returncode}")
            elif not skip_checks:
                _increment_sms_counter(cfg)
        except Exception as e:
            errs.append(f"{num}: {e}")
    if errs:
        return False, "; ".join(errs)
    return True, "ok"

def send_sms_on_change(cfg, rel, ts=None):
    """Odešle SMS na čísla z configu s odkazem na last_diff."""
    sms = cfg.get("sms", {})
    if not sms.get("enabled", True):
        return
    base_url = (sms.get("base_url") or "").rstrip("/")
    numbers = sms.get("numbers") or []
    message_tpl = sms.get("message") or "Změna na tabuli {datetime}: {url}"
    if not base_url or not numbers:
        if not base_url:
            print("[hub] SMS: sms.base_url není nastaveno, přeskočeno", file=sys.stderr)
        if not numbers:
            print("[hub] SMS: sms.numbers je prázdné, přeskočeno", file=sys.stderr)
        return
    if not _in_time_range(sms.get("time_from"), sms.get("time_to")):
        print("[hub] SMS: mimo povolenou dobu odesílání, přeskočeno", file=sys.stderr)
        return
    stats = _load_sms_stats(cfg)
    daily_limit = int(sms.get("daily_limit") or 0)
    numbers = sms.get("numbers") or []
    num_count = len([n for n in numbers if str(n).strip()])
    effective_limit = daily_limit * max(1, num_count) if daily_limit > 0 else 0
    if effective_limit > 0 and _sms_count_today(stats) >= effective_limit:
        print(f"[hub] SMS: denní limit {daily_limit}/číslo dosažen, přeskočeno", file=sys.stderr)
        return
    trigger = sms.get("trigger") or "change"
    if trigger == "first_today" and _sms_count_today(stats) > 0:
        print("[hub] SMS: trigger=first_today, dnes již odesláno, přeskočeno", file=sys.stderr)
        return
    url = f"{base_url}/last_diff?e={quote(rel)}" if rel else f"{base_url}/last_diff"
    datetime_str = _format_datetime(ts)
    ok, msg = _send_sms(cfg, message_tpl, url, datetime_str, skip_checks=False)
    if not ok:
        print(f"[hub] SMS: {msg}, přeskočeno", file=sys.stderr)
    else:
        print(f"[hub] SMS odeslána", file=sys.stderr)

def store(cfg, meta, frame, diff, frame_before=None):
    base = Path(cfg["storage"]["base_dir"])
    device = meta.get("device_id", "unknown")
    ts = meta.get("ts") or dt.datetime.now().isoformat(timespec="seconds")
    date = ts.split("T")[0]
    tpart = ts.split("T")[1].replace(":", "")
    ev_dir = base / "events" / device / date / tpart
    ev_dir.mkdir(parents=True, exist_ok=True)
    (ev_dir/"meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    frame.save(ev_dir/"frame.jpg")
    diff.save(ev_dir/"diff.png")
    if frame_before is not None:
        frame_before.save(ev_dir/"frame_before.jpg")
    return ev_dir

def cleanup_old_events(cfg):
    """Smaže eventy starší než keep_days."""
    base = Path(cfg["storage"]["base_dir"]) / "events"
    keep_days = int(cfg.get("storage", {}).get("keep_days", 30))
    if keep_days <= 0 or not base.exists():
        return
    cutoff = dt.datetime.now() - dt.timedelta(days=keep_days)
    removed = 0
    for device_dir in base.iterdir():
        if not device_dir.is_dir():
            continue
        for date_dir in list(device_dir.iterdir()):
            if not date_dir.is_dir():
                continue
            try:
                # date_dir je např. 2026-02-18
                d = dt.datetime.strptime(date_dir.name, "%Y-%m-%d")
                if d < cutoff:
                    shutil.rmtree(date_dir, ignore_errors=True)
                    removed += 1
            except ValueError:
                continue
    if removed:
        print(f"[hub] Smazáno {removed} adresářů eventů starších než {keep_days} dní", file=sys.stderr)

def list_recent(cfg, limit=30):
    base = Path(cfg["storage"]["base_dir"]) / "events"
    out = []
    if not base.exists():
        return out
    for meta_path in sorted(base.glob("*/*/*/meta.json"), reverse=True):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            ev_dir = meta_path.parent
            rel = ev_dir.relative_to(Path(cfg["storage"]["base_dir"]))
            out.append({
                "device_id": meta.get("device_id","unknown"),
                "ts": meta.get("ts",""),
                "change_percent": float(meta.get("change_percent",0.0)),
                "ocr_text": meta.get("ocr_text",""),
                "rel": str(rel).replace("\\","/"),
                "has_frame_before": (ev_dir / "frame_before.jpg").exists(),
            })
            if len(out) >= limit:
                break
        except Exception:
            continue
    return out

@app.route("/")
def index():
    cfg = load_cfg()
    Path(cfg["storage"]["base_dir"]).mkdir(parents=True, exist_ok=True)
    keep_days = int(cfg.get("storage", {}).get("keep_days", 30))
    rpi_url = cfg.get("live", {}).get("rpi_url", "http://192.168.1.19:8081").rstrip("/")
    return render_template("index.html", events=list_recent(cfg, 30), limit=30, keep_days=keep_days, version=get_version(), rpi_url=rpi_url)

@app.route("/live")
def live():
    cfg = load_cfg()
    return render_template("live.html", version=get_version())

def _get_event_for_diff(cfg, rel=None):
    """Vrátí (ev, ev_before) pro last_diff. ev_before = předchozí event (fallback když chybí frame_before)."""
    events = list_recent(cfg, limit=1 if rel else 100)
    ev = None
    ev_before = None
    if rel:
        for i, e in enumerate(events):
            if e["rel"] == rel:
                ev = e
                ev_before = events[i + 1] if i + 1 < len(events) else None
                break
    elif events:
        ev = events[0]
        ev_before = events[1] if len(events) > 1 else None
    return ev, ev_before

@app.route("/last_diff")
def last_diff():
    cfg = load_cfg()
    rel = request.args.get("e")
    ev, ev_before = _get_event_for_diff(cfg, rel)
    sms = cfg.get("sms", {})
    time_from = (sms.get("time_from") or "").strip()
    time_to = (sms.get("time_to") or "").strip()
    daily_limit = int(sms.get("daily_limit") or 0)
    time_range = None
    if time_from and time_to:
        time_range = f"{time_from}–{time_to}"
    elif time_from:
        time_range = f"od {time_from}"
    elif time_to:
        time_range = f"do {time_to}"
    num_count = len([n for n in (sms.get("numbers") or []) if str(n).strip()])
    sms_info = {
        "time_range": time_range,
        "daily_limit": daily_limit if daily_limit > 0 else None,
        "daily_limit_per_number": daily_limit if (daily_limit > 0 and num_count > 0) else None,
        "num_count": num_count,
    }
    illumination = _fetch_agent_illumination(cfg)
    return render_template(
        "last_diff.html",
        ev=ev,
        ev_before=ev_before,
        sms_info=sms_info,
        illumination=illumination,
        version=get_version(),
    )

def _event_items_for_last(cfg, limit=30):
    """Vrátí seznam {ev, before_rel, before_file, before_ts} pro stránku last_event."""
    events = list_recent(cfg, limit=limit + 1)
    base = Path(cfg["storage"]["base_dir"])
    items = []
    for i, ev in enumerate(events[:limit]):
        ev_before = events[i + 1] if i + 1 < len(events) else None
        ev_dir = base / ev["rel"]
        if ev["has_frame_before"] and (ev_dir / "frame_before.jpg").exists():
            before_rel = ev["rel"]
            before_file = "frame_before.jpg"
            before_ts = ev_before["ts"] if ev_before else ""
        elif ev_before:
            before_rel = ev_before["rel"]
            before_file = "frame.jpg"
            before_ts = ev_before["ts"]
        else:
            before_rel = None
            before_file = None
            before_ts = ""
        items.append({"ev": ev, "before_rel": before_rel, "before_file": before_file, "before_ts": before_ts})
    return items

@app.route("/settings")
def settings():
    cfg = load_cfg()
    rpi_url = cfg.get("live", {}).get("rpi_url", "http://192.168.1.19:8081").rstrip("/")
    return render_template("settings.html", version=get_version(), rpi_url=rpi_url)

@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    cfg = load_cfg()
    stats = _load_sms_stats(cfg)
    sms = cfg.get("sms", {})
    return jsonify({
        "sms": {
            "enabled": sms.get("enabled", True),
            "base_url": sms.get("base_url") or "",
            "numbers": sms.get("numbers", []),
            "message": sms.get("message", "Změna na tabuli {datetime}: {url}"),
            "time_from": sms.get("time_from") or "",
            "time_to": sms.get("time_to") or "",
            "daily_limit": sms.get("daily_limit") or 0,
            "trigger": sms.get("trigger", "change"),
            "counter": stats.get("total", 0),
        }
    })

@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    try:
        cfg = load_cfg()
        data = request.get_json() or {}
        if "sms" in data and isinstance(data["sms"], dict):
            cfg.setdefault("sms", {}).update(data["sms"])
            save_cfg(cfg)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/settings/sms/reset", methods=["POST"])
def api_sms_reset():
    cfg = load_cfg()
    _save_sms_stats(cfg, {"total": 0, "by_date": {}})
    return jsonify({"ok": True})

@app.route("/api/settings/sms/test", methods=["POST"])
def api_sms_test():
    """Odešle testovací SMS na všechna nakonfigurovaná čísla."""
    cfg = load_cfg()
    sms = cfg.get("sms", {})
    message_tpl = sms.get("message") or "Změna na tabuli {datetime}: {url}"
    base_url = (sms.get("base_url") or "").rstrip("/")
    url = f"{base_url}/last_diff" if base_url else "(test)"
    datetime_str = _format_datetime(None)
    ok, msg = _send_sms(cfg, message_tpl, url, datetime_str, skip_checks=True)
    if ok:
        return jsonify({"ok": True, "message": "Testovací SMS odeslána."})
    return jsonify({"ok": False, "error": msg}), 400

@app.route("/last_event")
def last_event():
    cfg = load_cfg()
    Path(cfg["storage"]["base_dir"]).mkdir(parents=True, exist_ok=True)
    return render_template("last_event.html", event_items=_event_items_for_last(cfg, 30), version=get_version())

@app.route("/api/events/count")
def api_events_count():
    cfg = load_cfg()
    events = list_recent(cfg, 1000)
    return {"count": len(events)}

def _rpi_url(cfg):
    return cfg.get("live", {}).get("rpi_url", "").rstrip("/")

def _fetch_agent_illumination(cfg):
    """Stáhne z agenta aktuální jas a min. osvětlení. Vrátí dict nebo None při chybě."""
    rpi_url = _rpi_url(cfg)
    if not rpi_url:
        return None
    brightness = None
    min_brightness = None
    try:
        with urlopen(f"{rpi_url}/api/status", timeout=3) as r:
            data = json.loads(r.read().decode("utf-8"))
            brightness = data.get("brightness")
    except Exception:
        pass
    try:
        with urlopen(f"{rpi_url}/api/config", timeout=3) as r:
            data = json.loads(r.read().decode("utf-8"))
            min_brightness = (data.get("processing") or {}).get("min_brightness")
    except Exception:
        pass
    if brightness is None and min_brightness is None:
        return None
    return {"brightness": brightness, "min_brightness": min_brightness}

@app.route("/api/live/frame")
def api_live_frame():
    """Proxy last.jpg z RPi – hub je jediný vstupní bod."""
    cfg = load_cfg()
    rpi_url = _rpi_url(cfg)
    if not rpi_url:
        abort(503, "live.rpi_url not configured")
    try:
        with urlopen(f"{rpi_url}/last.jpg", timeout=5) as r:
            data = r.read()
        return Response(data, mimetype="image/jpeg")
    except (URLError, OSError):
        abort(502, "RPi unreachable")

@app.route("/api/live/diff")
def api_live_diff():
    """Proxy last_diff.png z RPi."""
    cfg = load_cfg()
    rpi_url = _rpi_url(cfg)
    if not rpi_url:
        abort(503, "live.rpi_url not configured")
    try:
        with urlopen(f"{rpi_url}/last_diff.png", timeout=5) as r:
            data = r.read()
        return Response(data, mimetype="image/png")
    except (URLError, OSError):
        abort(502, "RPi unreachable")

@app.route("/api/live/ocr")
def api_live_ocr():
    """Proxy OCR text z RPi (last_ocr.txt)."""
    cfg = load_cfg()
    rpi_url = _rpi_url(cfg)
    if not rpi_url:
        return {"text": "", "error": "rpi_url not configured"}
    try:
        with urlopen(f"{rpi_url}/last_ocr.txt", timeout=3) as r:
            text = r.read().decode("utf-8", errors="replace")
        return {"text": text.strip()}
    except (URLError, OSError) as e:
        return {"text": "", "error": str(e)}

@app.route("/file/<path:relpath>/<path:filename>")
def file(relpath, filename):
    cfg = load_cfg()
    base = Path(cfg["storage"]["base_dir"]).resolve()
    d = (base / relpath).resolve()
    if not str(d).startswith(str(base)):
        abort(403)
    return send_from_directory(d, filename, as_attachment=False)

@app.route("/api/whiteboard/event", methods=["POST"])
def ingest():
    cfg = load_cfg()
    if not auth_ok(cfg):
        abort(401)

    frame = request.files.get("frame")
    diff = request.files.get("diff")
    frame_before = request.files.get("frame_before")
    if frame is None or diff is None:
        abort(400, "missing frame/diff")

    device_id = request.form.get("device_id","unknown")
    ts = request.form.get("ts") or dt.datetime.now().isoformat(timespec="seconds")
    change_percent = float(request.form.get("change_percent","0") or 0)
    ocr_text = request.form.get("ocr_text","")

    meta = {
        "device_id": device_id,
        "ts": ts,
        "change_percent": change_percent,
        "ocr_text": ocr_text,
        "ip": request.remote_addr,
    }
    ev_dir = store(cfg, meta, frame, diff, frame_before)
    rel = ev_dir.relative_to(Path(cfg["storage"]["base_dir"]))
    send_sms_on_change(cfg, str(rel).replace("\\", "/"), ts=ts)
    return {"ok": True, "stored": str(ev_dir)}, 200

def main():
    cfg = load_cfg()
    host = cfg["server"].get("host","0.0.0.0")
    port = int(cfg["server"].get("port",8099))
    Path(cfg["storage"]["base_dir"]).mkdir(parents=True, exist_ok=True)
    cleanup_old_events(cfg)
    app.run(host=host, port=port)

if __name__ == "__main__":
    main()
