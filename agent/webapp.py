#!/usr/bin/env python3
"""Web UI pro nastavení agenta – kamera, OCR, detekce změn. Běží na RPi (192.168.1.19)."""
import io
import json
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml
from flask import Flask, request, jsonify, send_from_directory, render_template_string, Response

# MJPEG stream – sdílený buffer pro živý přenos
_stream_frame = None
_stream_lock = threading.Lock()
_last_stream_update = 0.0  # čas poslední aktualizace z main.py


def update_stream_frame(jpeg_bytes: bytes):
    """Aktualizuje frame pro MJPEG stream. Volá se z main.py."""
    global _stream_frame, _last_stream_update
    if jpeg_bytes:
        with _stream_lock:
            _stream_frame = jpeg_bytes
            _last_stream_update = time.time()


def get_stream_frame():
    with _stream_lock:
        return _stream_frame


def get_last_stream_update():
    with _stream_lock:
        return _last_stream_update

CFG_PATH = os.environ.get("WHITEBOARD_AGENT_CONFIG", "/opt/whiteboard-agent/config.yaml")

app = Flask(__name__)


def get_version():
    p = Path(__file__).parent / "VERSION"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return "?"


def load_cfg():
    with open(CFG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_cfg(cfg):
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


INDEX_HTML = '''
<!DOCTYPE html>
<html lang="cs">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Whiteboard Agent – Nastavení</title>
  <style>
    :root { --bg:#1a1a20; --surface:#252530; --border:#3a3a45; --text:#e8e8ed; --muted:#888; --accent:#3b82f6; --ok:#22c55e; --block:#ef4444; --warn:#f59e0b; }
    * { box-sizing: border-box; }
    body { font-family: system-ui, sans-serif; margin: 0; padding: 16px; background: var(--bg); color: var(--text); font-size: 18px; }
    h1 { font-size: 1.6rem; margin: 0 0 4px 0; }
    .sub { color: var(--muted); font-size: 1.1rem; margin-bottom: 16px; }
    .main { max-width: 1800px; margin: 0 auto; }
    .top-row { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 24px; }
    @media (max-width: 1200px) { .top-row { grid-template-columns: 1fr; } }
    .previews-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; min-width: 0; align-items: start; }
    .previews-row .preview-section { margin-bottom: 0; display: flex; flex-direction: column; min-height: 0; }
    .previews-row .preview-section .preview-meta { min-height: 40px; font-size: 1.05rem; color: var(--muted); margin-bottom: 6px; font-variant-numeric: tabular-nums; }
    .previews-row .preview-section .preview-img-wrap { min-height: 140px; background: #111; border-radius: 8px; border: 1px solid var(--border); overflow: hidden; position: relative; display: flex; align-items: center; justify-content: center; }
    .previews-row .preview-section .preview-img-wrap img { max-height: 180px; width: 100%; object-fit: contain; display: block; }
    .previews-row .preview-section h3 { font-size: 1.15rem; margin: 0 0 6px 0; }
    .analysis-col { min-width: 0; }
    .settings-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }
    @media (max-width: 1400px) { .settings-grid { grid-template-columns: repeat(2, 1fr); } }
    @media (max-width: 900px) { .settings-grid { grid-template-columns: 1fr; } }
    .card {
      break-inside: avoid; margin-bottom: 16px;
      background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
      padding: 16px; min-width: 0; overflow: hidden;
    }
    .card h2 { font-size: 1.2rem; margin: 0 0 12px 0; color: var(--accent); padding-bottom: 8px; border-bottom: 1px solid var(--border); }
    .analysis-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
    .analysis-card h2 { font-size: 1.25rem; margin: 0 0 12px 0; color: var(--accent); }
    .analysis-row { display: flex; align-items: center; justify-content: space-between; padding: 6px 0; font-size: 1.15rem; border-bottom: 1px solid var(--border); }
    .analysis-row:last-child { border-bottom: none; }
    .analysis-row.ok .val { color: var(--ok); }
    .analysis-row.block .val { color: var(--block); font-weight: 600; }
    .analysis-row .val { font-variant-numeric: tabular-nums; }
    .analysis-list { list-style: none; margin: 0; padding: 0; }
    .analysis-list li { padding: 8px 0; font-size: 1.2rem; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .analysis-list li:last-child { border-bottom: none; }
    .analysis-list li.ok { color: var(--ok); }
    .analysis-list li.block { color: var(--block); }
    .analysis-list .bullet { flex-shrink: 0; font-weight: 700; width: 1.3em; font-size: 1.25rem; }
    .analysis-list .detail { color: var(--muted); font-size: 1.15rem; margin-left: auto; }
    .preview-img { width: 100%; max-height: 280px; object-fit: contain; border-radius: 8px; border: 1px solid var(--border); background: #111; display: block; }
    .preview-section { margin-bottom: 16px; }
    .preview-section h3 { font-size: 1.15rem; color: var(--muted); margin: 0 0 8px 0; }
    .row { display: flex; gap: 10px; align-items: center; flex-wrap: nowrap; }
    .row label { flex: 0 0 170px; font-size: 1.15rem; line-height: 1.3; }
    .row .input-wrap { flex: 1; min-width: 0; }
    .setting-block { padding-bottom: 12px; margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.12); }
    .setting-block:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
    .setting-block .setting-label { font-size: 1.15rem; font-weight: 600; margin-bottom: 6px; display: block; }
    .setting-block .setting-input { margin-bottom: 4px; font-size: 1.1rem; }
    .setting-block .setting-hint { font-size: 1.05rem; color: var(--muted); line-height: 1.3; }
    input[type="number"], input[type="text"], select {
      padding: 6px 10px; border-radius: 6px; border: 1px solid var(--border);
      background: var(--bg); color: var(--text); font-size: 1rem; width: 100%; max-width: 120px;
    }
    select { max-width: 180px; }
    input[type="range"] { width: 100px; flex-shrink: 0; }
    .val { color: var(--muted); font-size: 1.1rem; flex: 0 0 32px; }
    button {
      padding: 8px 18px; border-radius: 6px; border: none;
      background: var(--accent); color: white; font-weight: 600; cursor: pointer; font-size: 1rem;
    }
    button:hover { opacity: 0.9; }
    .btn-small { padding: 4px 10px; font-size: 0.95rem; }
    .preview-wrap {
      background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
      padding: 16px; position: sticky; top: 16px; min-width: 0;
    }
    .preview-wrap h2 { font-size: 1.2rem; margin: 0 0 10px 0; color: var(--accent); padding-bottom: 8px; border-bottom: 1px solid var(--border); }
    .preview { width: 100%; max-height: 300px; object-fit: contain; border-radius: 8px; border: 1px solid var(--border); background: #111; display: block; }
    .msg { padding: 8px 12px; border-radius: 6px; font-size: 1.1rem; display: inline-block; margin-left: 8px; }
    .msg.ok { background: #0d3d0d; }
    .msg.err { background: #4d1a1a; }
    .preview-box { position: relative; min-height: 160px; background: #111; border-radius: 8px; overflow: hidden; }
    .preview-box img { display: block; width: 100%; }
    .preview-box.has-error img { display: none; }
    .preview-fallback { display: none; position: absolute; inset: 0; flex-direction: column; align-items: center; justify-content: center; color: var(--muted); font-size: 1.1rem; padding: 16px; text-align: center; }
    .preview-box.has-error .preview-fallback { display: flex; }
    .hint { font-size: 1.05rem; color: var(--muted); margin-top: 4px; margin-left: 0; line-height: 1.3; }
    .version { color: var(--muted); font-weight: 400; font-size: 1.1rem; }
    .save-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 16px; break-inside: avoid; }
    .roi-grid { display: grid; grid-template-columns: auto minmax(60px, 90px) auto minmax(60px, 90px); gap: 8px 16px; align-items: center; }
    .roi-grid input { max-width: none; }
    @media (max-width: 400px) { .roi-grid { grid-template-columns: auto 1fr; } }
    .block-hint summary:hover { color: var(--text); }
  </style>
</head>
<body>
  <h1>Whiteboard Agent – Nastavení <span class="version">v{{ version }}</span></h1>
  <p class="sub">Kamera na RPi – úpravy se projeví ihned (bez restartu)</p>

  <div class="main">
  <div class="top-row">
    <div class="previews-row">
      <div class="preview-section">
        <div style="display:flex; align-items:center; gap:10px; margin-bottom:6px;">
          <h3 style="margin:0;">Live</h3>
          <button type="button" id="make-last-btn" class="btn-small" title="Uložit aktuální náhled jako referenční snímek (Last) pro porovnání">Make last</button>
        </div>
        <div class="preview-meta" id="live-meta">-</div>
        <div id="preview-box" class="preview-img-wrap preview-box">
          <img id="preview" src="/stream" alt="live" onerror="this.onerror=null; this.src='/last.jpg?t='+Date.now(); this.title='Stream nedostupný';">
          <div class="preview-fallback">Čekám na snímek…</div>
        </div>
        <div id="ts-preview" style="font-size:1.05rem; color:var(--muted); margin-top:4px;">-</div>
      </div>
      <div class="preview-section">
        <h3>Last (event)</h3>
        <div class="preview-meta" id="last-meta">-</div>
        <div id="last-saved-wrap" class="preview-img-wrap">
          <img id="last-saved-img" src="" alt="last saved" style="display:none;">
          <div id="last-saved-fallback" style="display:flex; position:absolute; inset:0; align-items:center; justify-content:center; color:var(--muted); font-size:1.1rem;">Žádný event</div>
        </div>
        <div id="ts-saved-preview" style="font-size:1.05rem; color:var(--muted); margin-top:4px;">-</div>
      </div>
      <div class="preview-section">
        <h3>Diff</h3>
        <div class="preview-meta" id="diff-meta">-</div>
        <div id="diff-wrap" class="preview-img-wrap">
          <img id="diff-img" src="/last_diff.png" alt="diff">
          <div id="diff-fallback" style="display:none; position:absolute; inset:0; align-items:center; justify-content:center; color:var(--muted); font-size:1.1rem;">Žádný diff</div>
        </div>
        <div id="ts-diff-preview" style="font-size:1.05rem; color:var(--muted); margin-top:4px;">-</div>
      </div>
    </div>
    <div class="analysis-col">
      <div class="analysis-card">
        <h2>Analýza – co musí být splněno</h2>
        <p id="preview-status" style="margin:0 0 10px 0; font-size:1.05rem; color:var(--muted);">Obnovení každé 1.5 s</p>
        <div id="analysis-list"></div>
        <details class="block-hint" style="margin-top:10px;">
          <summary style="cursor:pointer; font-size:1.05rem; color:var(--muted);">Co znamená blokace eventu?</summary>
          <ul style="margin:6px 0 0 0; padding-left:18px; font-size:1.05rem; color:var(--muted); line-height:1.5;">
            <li><strong>hitů 0/2</strong> – žádná změna → event se neposílá</li>
            <li><strong>hitů 2/2</strong> – dva snímky nad prahem → event se odešle</li>
            <li><strong>ustálení</strong> – čeká na snímky bez změny</li>
            <li><strong>cooldown</strong> – min. pauza mezi eventy</li>
            <li><strong>rozdíl jasu před/po</strong> – porovná průměrný jas aktuálního snímku s referenčním (Last). Pokud je rozdíl &gt; 35 %, systém předpokládá, že jde jen o změnu osvětlení (kdo rozsvítil/zhasl), ne o obsah tabule – event se neposílá.</li>
          </ul>
        </details>
      </div>
    </div>
  </div>

  <div class="settings-grid">
  <div class="card">
    <h2>Kamera / Obraz</h2>
    <div class="setting-block">
      <span class="setting-label">Rozlišení</span>
      <div class="setting-input"><select id="resolution" style="width:100%; max-width:180px">
        <option value="1920x1080">1920×1080 (Full HD)</option>
        <option value="1640x1232">1640×1232</option>
        <option value="1280x720">1280×720 (HD)</option>
        <option value="640x480">640×480 (VGA)</option>
        <option value="3280x2464">3280×2464 (RPi HQ max)</option>
      </select></div>
      <div class="setting-hint">Šířka × výška snímku. Vyžaduje restart agenta.</div>
    </div>
    <div class="setting-block">
      <span class="setting-label">Jas</span>
      <div class="setting-input"><input type="range" id="brightness" min="50" max="150" value="100" style="width:120px"> <span class="val" id="brightnessVal">100</span></div>
      <div class="setting-hint">50–200, 100 = bez změny. Jasnost snímku.</div>
    </div>
    <div class="setting-block">
      <span class="setting-label">Kontrast</span>
      <div class="setting-input"><input type="range" id="contrast" min="50" max="150" value="100" style="width:120px"> <span class="val" id="contrastVal">100</span></div>
      <div class="setting-hint">50–200, 100 = bez změny.</div>
    </div>
    
    <details style="margin-top:12px; border-top:1px solid var(--border); padding-top:12px;">
      <summary style="cursor:pointer; color:var(--accent); font-weight:600; margin-bottom:12px;">Pokročilé nastavení obrazu...</summary>
      <div class="setting-block">
        <span class="setting-label">CLAHE limit</span>
        <div class="setting-input"><input type="number" id="clahe_clip_limit" min="1" max="4" step="0.1" style="width:80px" value="2" placeholder="2"></div>
        <div class="setting-hint">Zvýšení lokálního kontrastu. Default 2.</div>
      </div>
      <div class="setting-block">
        <span class="setting-label">JPEG kvalita</span>
        <div class="setting-input"><input type="number" id="jpeg_quality" min="50" max="100" style="width:80px" value="90" placeholder="90"></div>
        <div class="setting-hint">Komprese. Default 90.</div>
      </div>
    </details>
  </div>

  <div class="card">
    <h2>Detekce změn</h2>
    <div class="setting-block">
      <span class="setting-label">Režim detekce</span>
      <div class="setting-input"><select id="detection_mode" style="width:100%; max-width:160px" onchange="updateVisibility()">
        <option value="adaptive">Adaptivní (doporučeno)</option>
        <option value="legacy">Klasický (starý)</option>
      </select></div>
      <div class="setting-hint">Adaptivní ignoruje stíny. Klasický porovnává pixely.</div>
    </div>
    
    <div class="setting-block" id="row_adaptive_c">
      <span class="setting-label">Citlivost (C)</span>
      <div class="setting-input"><input type="number" id="adaptive_c" min="1" max="50" style="width:60px" value="10" placeholder="10"></div>
      <div class="setting-hint">Pro adaptivní režim. Vyšší = méně šumu (ignoruje slabé písmo). Default 10.</div>
    </div>

    <div class="setting-block" id="row_pixel_threshold">
      <span class="setting-label">Práh pixelů</span>
      <div class="setting-input"><input type="number" id="pixel_threshold" min="5" max="80" style="width:60px" value="30" placeholder="30"></div>
      <div class="setting-hint">Pro klasický režim. Rozdíl pixelů > toto = změna. Default 30.</div>
    </div>

    <div class="setting-block">
      <span class="setting-label">Práh změny (%)</span>
      <div class="setting-input"><input type="number" id="change_threshold_percent" min="0.1" max="5" step="0.05" style="width:80px" value="0.35" placeholder="0.35"></div>
      <div class="setting-hint">Kolik % plochy se musí změnit pro detekci. Default 0.35.</div>
    </div>
    
    <div class="setting-block">
      <span class="setting-label">Min. osvětlení</span>
      <div class="setting-input"><input type="number" id="min_brightness" min="0" max="255" step="5" style="width:70px" placeholder="vypnuto"> <span id="current_brightness" style="font-weight:600; color:var(--accent); font-variant-numeric:tabular-nums;">-</span></div>
      <div class="setting-hint">Při nižším jasu neodesílá (noc).</div>
    </div>

    <details style="margin-top:12px; border-top:1px solid var(--border); padding-top:12px;">
      <summary style="cursor:pointer; color:var(--accent); font-weight:600; margin-bottom:12px;">Pokročilé nastavení detekce...</summary>
      
      <div class="setting-block">
        <span class="setting-label">Po sobě jdoucích hitů</span>
        <div class="setting-input"><input type="number" id="consecutive_hits" min="1" max="5" style="width:60px" value="2" placeholder="2"></div>
        <div class="setting-hint">Ochrana proti zábleskům. Default 2.</div>
      </div>
      <div class="setting-block">
        <span class="setting-label">Cooldown (s)</span>
        <div class="setting-input"><input type="number" id="cooldown_seconds" min="5" max="120" style="width:60px" value="20" placeholder="20"></div>
        <div class="setting-hint">Pauza mezi eventy. Default 20.</div>
      </div>
      <div class="setting-block">
        <span class="setting-label">Interval snímání (s)</span>
        <div class="setting-input"><input type="number" id="interval_seconds" min="1" max="10" step="0.5" style="width:80px" value="3" placeholder="3"></div>
        <div class="setting-hint">Jak často kamera fotí. Default 3.</div>
      </div>
      <div class="setting-block">
        <span class="setting-label">Ustálení obrazu</span>
        <div class="setting-input"><input type="checkbox" id="stabilization_enabled" checked></div>
        <div class="setting-hint">Čekat, až se obraz přestane hýbat (např. odchod osoby).</div>
      </div>
      <div class="setting-block">
        <span class="setting-label">Stabilních snímků</span>
        <div class="setting-input"><input type="number" id="stabilization_frames" min="2" max="10" style="width:60px" value="3" placeholder="3"></div>
      </div>
      <div class="setting-block">
        <span class="setting-label">Rychlý práh (%)</span>
        <div class="setting-input"><input type="number" id="fast_change_threshold_percent" min="0.3" max="5" step="0.1" style="width:70px" value="1.5" placeholder="1.5"></div>
        <div class="setting-hint">Při velké změně odeslat hned (přeskočit ustálení).</div>
      </div>
    </details>
  </div>

  <div class="card">
    <h2>OCR</h2>
    <div class="setting-block">
      <span class="setting-label">Zapnuto</span>
      <div class="setting-input"><input type="checkbox" id="ocr_enabled" checked></div>
      <div class="setting-hint">Optické rozpoznávání textu z tabule.</div>
    </div>
    <div class="setting-block">
      <span class="setting-label">Jazyk</span>
      <div class="setting-input"><select id="ocr_lang" style="width:100%; max-width:140px">
        <option value="ces">čeština</option>
        <option value="eng">angličtina</option>
        <option value="ces+eng">ces+eng</option>
      </select></div>
      <div class="setting-hint">Jazyk OCR (Tesseract).</div>
    </div>
    <div class="setting-block">
      <span class="setting-label">PSM</span>
      <div class="setting-input"><select id="ocr_psm" style="width:100%; max-width:180px">
        <option value="3">3 – automaticky</option>
        <option value="4">4 – jeden sloupec</option>
        <option value="6" selected>6 – blok textu</option>
        <option value="13">13 – jeden řádek</option>
      </select></div>
      <div class="setting-hint">Režim segmentace. Pro seznamy zkus 4 (sloupec) nebo 3 (automaticky).</div>
    </div>
    <div class="setting-block">
      <span class="setting-label">Předzpracování</span>
      <div class="setting-input"><select id="ocr_preprocess" style="width:100%; max-width:160px">
        <option value="otsu" selected>Otsu (binarizace)</option>
        <option value="adaptive">Adaptivní práh</option>
        <option value="none">Žádné (surový obrázek)</option>
      </select></div>
      <div class="setting-hint">Otsu = černý text na bílém. Žádné = pro ruční písmo.</div>
    </div>
    <div class="setting-block">
      <span class="setting-label">Debug vstup OCR</span>
      <div class="setting-input"><input type="checkbox" id="ocr_debug_save_input"></div>
      <div class="setting-hint">Uloží last_ocr_input.png – obrázek posílaný do Tesseractu.</div>
    </div>
  </div>

  <div class="card">
    <h2>ROI (oblast tabule)</h2>
    <div class="setting-block">
      <span class="setting-label">Obdélník vykrojený ze snímku</span>
      <div class="setting-hint" style="margin-bottom:8px;">Jen tato oblast se analyzuje a OCR.</div>
    </div>
    <div class="setting-block">
      <span class="setting-label">x, y (levý/horní okraj)</span>
      <div class="setting-input" style="display:flex; gap:8px; flex-wrap:wrap;">
        <input type="number" id="roi_x" title="Pixel od levého okraje" value="150" placeholder="150" style="width:70px">
        <input type="number" id="roi_y" title="Pixel od horního okraje" value="80" placeholder="80" style="width:70px">
      </div>
      <div class="setting-hint">Posun od levého a horního okraje snímku v pixelech.</div>
    </div>
    <div class="setting-block">
      <span class="setting-label">w, h (šířka, výška)</span>
      <div class="setting-input" style="display:flex; gap:8px; flex-wrap:wrap;">
        <input type="number" id="roi_w" title="Šířka oblasti" value="1300" placeholder="1300" style="width:70px">
        <input type="number" id="roi_h" title="Výška oblasti" value="900" placeholder="900" style="width:70px">
      </div>
      <div class="setting-hint">Rozměry vykrojené oblasti v pixelech.</div>
    </div>
  </div>
  <div class="card">
    <h2>Poslední soubory</h2>
    <table style="width:100%; border-collapse: collapse; font-size: 1.1rem;">
      <tr><th style="text-align:left; padding:4px 0;">Soubor</th><th style="text-align:left;">Čas</th></tr>
      <tr><td><a href="/last.jpg">last.jpg</a></td><td id="ts_last">-</td></tr>
      <tr><td><a href="/last_saved.jpg">last_saved.jpg</a></td><td id="ts_saved">-</td></tr>
      <tr><td><a href="/last_diff.png">last_diff.png</a></td><td id="ts_diff">-</td></tr>
      <tr><td><a href="/last_ocr.txt">last_ocr.txt</a></td><td id="ts_ocr">-</td></tr>
      <tr><td><a href="/last_ocr_input.png">last_ocr_input.png</a> <span style="color:var(--muted);font-size:0.9em">(debug)</span></td><td>-</td></tr>
    </table>
  </div>
  </div>

  <div class="save-row" style="margin-top:24px;">
    <button onclick="saveConfig()">Uložit nastavení</button>
    <span id="msg"></span>
  </div>
  <details class="block-hint" style="margin-top:16px;">
    <summary style="cursor:pointer; font-size:1.05rem; color:var(--muted);">Debug – ověření výstupu kamery</summary>
    <pre id="debug-output" style="margin:8px 0 0 0; padding:8px; background:#111; border-radius:6px; font-size:0.95rem; overflow-x:auto;">-</pre>
  </details>

  <script>
    let cfg = {};
    const RESOLUTIONS = {"1920x1080":[1920,1080],"1640x1232":[1640,1232],"1280x720":[1280,720],"640x480":[640,480],"3280x2464":[3280,2464]};
    function updateVisibility() {
      const mode = document.getElementById("detection_mode").value;
      const rowC = document.getElementById("row_adaptive_c");
      const rowP = document.getElementById("row_pixel_threshold");
      if (mode === "adaptive") {
        rowC.style.display = "block";
        rowP.style.display = "none";
      } else {
        rowC.style.display = "none";
        rowP.style.display = "block";
      }
    }
    
    function updateVisibility() {
      const mode = document.getElementById("detection_mode").value;
      const rowC = document.getElementById("row_adaptive_c");
      const rowP = document.getElementById("row_pixel_threshold");
      if (mode === "adaptive") {
        rowC.style.display = "block";
        rowP.style.display = "none";
      } else {
        rowC.style.display = "none";
        rowP.style.display = "block";
      }
    }
    
    async function load() {
      const r = await fetch("/api/config");
      cfg = await r.json();
      if (!r.ok || cfg.error) {
        const msg = document.getElementById("msg");
        msg.className = "msg err";
        msg.textContent = " Config se nepodařilo načíst: " + (cfg.error || r.status) + ". Zkontroluj /api/debug (config_path, config_ok).";
        return;
      }
      const w = (cfg.capture && cfg.capture.width) || 1920, h = (cfg.capture && cfg.capture.height) || 1080;
      let resKey = Object.keys(RESOLUTIONS).find(k => RESOLUTIONS[k][0]===w && RESOLUTIONS[k][1]===h);
      if (!resKey) {
        resKey = w + "x" + h;
        RESOLUTIONS[resKey] = [w, h];
        const sel = document.getElementById("resolution");
        if (!sel.querySelector('option[value="' + resKey + '"]')) {
          const opt = document.createElement("option");
          opt.value = resKey;
          opt.textContent = w + "×" + h + " (vlastní)";
          sel.appendChild(opt);
        }
      }
      document.getElementById("resolution").value = resKey;
      document.getElementById("brightness").value = cfg.capture?.brightness ?? 100;
      document.getElementById("brightnessVal").textContent = cfg.capture?.brightness ?? 100;
      document.getElementById("contrast").value = cfg.capture?.contrast ?? 100;
      document.getElementById("contrastVal").textContent = cfg.capture?.contrast ?? 100;
      document.getElementById("clahe_clip_limit").value = (cfg.processing && cfg.processing.clahe_clip_limit) || 2;
      document.getElementById("jpeg_quality").value = (cfg.capture && cfg.capture.jpeg_quality) || 90;
      document.getElementById("change_threshold_percent").value = (cfg.processing && cfg.processing.change_threshold_percent) || 0.35;
      document.getElementById("detection_mode").value = (cfg.processing && cfg.processing.detection_mode) || "adaptive";
      document.getElementById("adaptive_c").value = (cfg.processing && cfg.processing.adaptive_c) || 10;
      document.getElementById("pixel_threshold").value = (cfg.processing && cfg.processing.pixel_threshold) || 30;
      document.getElementById("consecutive_hits").value = (cfg.processing && cfg.processing.consecutive_hits) || 2;
      document.getElementById("cooldown_seconds").value = (cfg.processing && cfg.processing.cooldown_seconds) || 20;
      document.getElementById("interval_seconds").value = (cfg.processing && cfg.processing.interval_seconds) || 3;
      const mb = cfg.processing ? cfg.processing.min_brightness : undefined;
      document.getElementById("min_brightness").value = (mb != null && mb !== "") ? mb : "";
      document.getElementById("stabilization_enabled").checked = cfg.processing?.stabilization_enabled !== false;
      document.getElementById("stabilization_frames").value = (cfg.processing && cfg.processing.stabilization_frames) || 3;
      document.getElementById("fast_change_threshold_percent").value = (cfg.processing && cfg.processing.fast_change_threshold_percent) || 1.5;
      document.getElementById("ocr_enabled").checked = !(cfg.ocr && cfg.ocr.enabled === false);
      document.getElementById("ocr_lang").value = (cfg.ocr && cfg.ocr.lang) || "ces";
      document.getElementById("ocr_psm").value = String((cfg.ocr && cfg.ocr.psm) || 6);
      document.getElementById("ocr_preprocess").value = (cfg.ocr && cfg.ocr.preprocess) || "otsu";
      document.getElementById("ocr_debug_save_input").checked = cfg.ocr?.debug_save_input === true;
      const roi = cfg.processing?.roi || {};
      document.getElementById("roi_x").value = roi.x ?? 150;
      document.getElementById("roi_y").value = roi.y ?? 80;
      document.getElementById("roi_w").value = roi.w ?? 1300;
      document.getElementById("roi_h").value = roi.h ?? 900;
      
      updateVisibility();
    }
    document.getElementById("brightness").oninput = e => {
      document.getElementById("brightnessVal").textContent = e.target.value;
    };
    document.getElementById("contrast").oninput = e => {
      document.getElementById("contrastVal").textContent = e.target.value;
    };
    document.getElementById("make-last-btn").onclick = async function() {
      const btn = this;
      btn.disabled = true;
      try {
        const r = await fetch("/api/make_last", { method: "POST" });
        const d = await r.json();
        if (d.ok) {
          await refreshFileInfo();
          document.getElementById("diff-img").src = "/last_diff.png?t=" + Date.now();
          const msg = document.getElementById("msg");
          msg.className = "msg ok";
          msg.textContent = " Last uložen – aktuální náhled je nyní referenční snímek.";
          msg.style.display = "inline-block";
        } else {
          const msg = document.getElementById("msg");
          msg.className = "msg err";
          msg.textContent = " " + (d.error || "Chyba");
          msg.style.display = "inline-block";
        }
      } catch (e) {
        const msg = document.getElementById("msg");
        msg.className = "msg err";
        msg.textContent = " Chyba: " + (e.message || String(e));
        msg.style.display = "inline-block";
      }
      btn.disabled = false;
    };
    async function saveConfig() {
      const resVal = document.getElementById("resolution").value;
      const wh = RESOLUTIONS[resVal] || [1920, 1080];
      const width = wh[0], height = wh[1];
      const roi = {
        x: parseInt(document.getElementById("roi_x").value) || 150,
        y: parseInt(document.getElementById("roi_y").value) || 80,
        w: parseInt(document.getElementById("roi_w").value) || 1300,
        h: parseInt(document.getElementById("roi_h").value) || 900,
      };
      const minBVal = document.getElementById("min_brightness").value.trim();
      const body = {
        capture: Object.assign({}, cfg.capture, {
          width: width, height: height,
          brightness: parseInt(document.getElementById("brightness").value) || 100,
          contrast: parseInt(document.getElementById("contrast").value) || 100,
          jpeg_quality: parseInt(document.getElementById("jpeg_quality").value) || 90,
        }),
        processing: Object.assign({}, cfg.processing, {
          roi: roi,
          clahe_clip_limit: parseFloat(document.getElementById("clahe_clip_limit").value) || 2,
          change_threshold_percent: parseFloat(document.getElementById("change_threshold_percent").value) || 0.35,
          detection_mode: document.getElementById("detection_mode").value,
          adaptive_c: parseInt(document.getElementById("adaptive_c").value) || 10,
          pixel_threshold: parseInt(document.getElementById("pixel_threshold").value) || 30,
          consecutive_hits: parseInt(document.getElementById("consecutive_hits").value) || 2,
          cooldown_seconds: parseInt(document.getElementById("cooldown_seconds").value) || 20,
          interval_seconds: parseFloat(document.getElementById("interval_seconds").value) || 3,
          min_brightness: minBVal === "" ? null : parseInt(minBVal, 10),
          stabilization_enabled: document.getElementById("stabilization_enabled").checked,
          stabilization_frames: parseInt(document.getElementById("stabilization_frames").value) || 3,
          fast_change_threshold_percent: parseFloat(document.getElementById("fast_change_threshold_percent").value) || 1.5,
        }),
        ocr: Object.assign({}, cfg.ocr, {
          enabled: document.getElementById("ocr_enabled").checked,
          lang: document.getElementById("ocr_lang").value,
          psm: parseInt(document.getElementById("ocr_psm").value) || 6,
          preprocess: document.getElementById("ocr_preprocess").value || "otsu",
          debug_save_input: document.getElementById("ocr_debug_save_input").checked,
        }),
      };
      const msg = document.getElementById("msg");
      try {
        const r = await fetch("/api/config", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body) });
        var d = {};
        try { d = await r.json(); } catch (_) {}
        if (r.ok) {
          msg.className = "msg ok";
          var resChanged = (cfg.capture && (cfg.capture.width !== width || cfg.capture.height !== height));
          msg.textContent = resChanged ? " Uloženo. Změna rozlišení vyžaduje restart agenta." : " Uloženo. Změny se projeví při dalším snímku.";
        } else {
          msg.className = "msg err";
          msg.textContent = " Chyba: " + (d.error || r.status);
        }
      } catch (e) {
        msg.className = "msg err";
        msg.textContent = " Chyba při ukládání: " + (e.message || String(e));
      }
      msg.style.display = "inline-block";
      try { msg.scrollIntoView({ behavior: "smooth", block: "nearest" }); } catch (_) {}
    }
    async function refreshFileInfo() {
      try {
        const r = await fetch("/api/files");
        const d = await r.json();
        const map = { "last.jpg": "last", "last_saved.jpg": "saved", "last_diff.png": "diff", "last_ocr.txt": "ocr" };
        for (const [k, v] of Object.entries(d)) {
          const id = map[k];
          if (id) document.getElementById("ts_" + id).textContent = v || "-";
        }
        const age = d["_last_jpg_age"];
        const stale = age != null && age > 120;
        document.getElementById("ts-preview").textContent = d["last.jpg"] ? "Datum a čas snímku: " + d["last.jpg"] + (stale ? " STARÝ" : "") : "-";
        if (stale && document.getElementById("ts-preview-warn")) {
          document.getElementById("ts-preview-warn").style.display = "block";
          document.getElementById("ts-preview-warn").textContent = "Snímek je starší než 2 min – kamera neběží. Na RPi: sudo systemctl restart libcamera-v4l2 whiteboard-agent";
        } else if (document.getElementById("ts-preview-warn")) {
          document.getElementById("ts-preview-warn").style.display = "none";
        }
        document.getElementById("ts-saved-preview").textContent = d["last_saved.jpg"] ? "Datum a čas: " + d["last_saved.jpg"] : "-";
        document.getElementById("ts-diff-preview").textContent = d["last_diff.png"] ? "Datum a čas: " + d["last_diff.png"] : "-";
        var lastMeta = document.getElementById("last-meta");
        var diffMeta = document.getElementById("diff-meta");
        if (lastMeta) lastMeta.textContent = d["last_saved.jpg"] || "-";
        if (diffMeta) diffMeta.textContent = d["last_diff.png"] || "-";
        const lastSavedImg = document.getElementById("last-saved-img");
        const lastSavedFallback = document.getElementById("last-saved-fallback");
        if (d["last_saved.jpg"]) {
          lastSavedImg.src = "/last_saved.jpg?t=" + Date.now();
          lastSavedImg.style.display = "";
          lastSavedFallback.style.display = "none";
        } else {
          lastSavedImg.src = "";
          lastSavedImg.style.display = "none";
          lastSavedFallback.style.display = "flex";
        }
      } catch (_) {}
    }
    function renderAnalysis(d) {
      const list = document.getElementById("analysis-list");
      const curEl = document.getElementById("current_brightness");
      const liveMetaEl = document.getElementById("live-meta");
      const hasData = d && d.brightness != null;
      const a = (d && d.analysis) || {};
      const minB = (a.min_brightness != null) ? a.min_brightness : (cfg.processing ? cfg.processing.min_brightness : null);
      const brightText = hasData ? (minB != null ? "Aktuální jas: " + d.brightness + " / min. " + minB : "Aktuální jas: " + d.brightness) : "-";
      curEl.textContent = brightText;
      window._lastBrightnessText = hasData ? ("Jas: " + d.brightness + (minB != null ? " (min. " + minB + ")" : "")) : "Jas: -";
      if (liveMetaEl) liveMetaEl.textContent = (window._lastLiveTime || "-") + " | " + window._lastBrightnessText;
      const items = [];
      const item = (label, detail, ok) => {
        const cls = ok === false ? "block" : (ok === true ? "ok" : "");
        const bullet = ok === true ? "\u2713" : (ok === false ? "\u2717" : "\u00B7");
        const det = detail != null && detail !== "" ? detail : "";
        return '<li class="' + cls + '"><span class="bullet">' + bullet + '</span><span style="flex:1">' + label + '</span><span class="detail">' + det + '</span></li>';
      };
      if (hasData) {
        if (d.state === "low_light") {
          items.push(item("1. Min. osvětlení", d.brightness + " &lt; " + minB + " (nedostatečné)", false));
          items.push(item("2. Změna pixelů", "- (čeká na osvětlení)", ""));
          items.push(item("3. Po sobě jdoucí hitů", "-", ""));
          items.push(item("4. Ustálení", "-", ""));
          items.push(item("5. Cooldown", "-", ""));
          items.push(item("6. Rozdíl jasu před/po", "-", ""));
          items.push(item("7. Vytvoření eventu", "blokuje: nedostatečné osvětlení", false));
        } else {
          if (minB != null) {
            const brightOk = a.brightness_ok !== false;
            items.push(item("1. Min. osvětlení", d.brightness + " >= " + minB, brightOk));
          } else {
            items.push(item("1. Min. osvětlení", "vypnuto", true));
          }
          if (a.pct != null) {
            items.push(item("2. Změna pixelů", a.pct + "% >= práh " + a.change_threshold + "%", a.pct_ok));
          } else {
            items.push(item("2. Změna pixelů", "-", ""));
          }
          if (a.hits != null) {
            items.push(item("3. Po sobě jdoucí hitů", a.hits + "/" + a.need, a.hits_ok ? true : ""));
          } else {
            items.push(item("3. Po sobě jdoucí hitů", "-", ""));
          }
          if (a.wait_stable) {
            items.push(item("4. Ustálení", a.stable_count + "/" + a.stab_frames + " stabilních snímků", false));
          } else {
            items.push(item("4. Ustálení", "splněno", true));
          }
          if (a.cooldown_remaining != null) {
            items.push(item("5. Cooldown", a.cooldown_ok ? "uplynul" : (a.cooldown_remaining + " s zbývá"), a.cooldown_ok ? true : ""));
          } else {
            items.push(item("5. Cooldown", "-", ""));
          }
          if (a.brightness_ratio != null) {
            items.push(item("6. Rozdíl jasu před/po", a.brightness_ratio + "% <= max " + a.max_brightness_percent + "%", a.brightness_ok));
          } else {
            items.push(item("6. Rozdíl jasu před/po", "-", ""));
          }
          var allOk = !a.wait_stable && a.hits_ok !== false && a.pct_ok !== false && a.cooldown_ok !== false && (a.brightness_ok !== false || !minB);
          if (d.block_reason) {
            items.push(item("7. Vytvoření eventu", "blokuje: " + d.block_reason, false));
          } else if (allOk) {
            items.push(item("7. Vytvoření eventu", "event se odešle", true));
          } else {
            items.push(item("7. Vytvoření eventu", "čeká na splnění podmínek", ""));
          }
        }
      } else {
        items.push(item("1. Min. osvětlení", "-", ""));
        items.push(item("2. Změna pixelů", "-", ""));
        items.push(item("3. Po sobě jdoucí hitů", "-", ""));
        items.push(item("4. Ustálení", "-", ""));
        items.push(item("5. Cooldown", "-", ""));
        items.push(item("6. Rozdíl jasu před/po", "-", ""));
        items.push(item("7. Vytvoření eventu", "-", ""));
        items.push(item("Stav", "Kamera neběží? Na RPi: sudo systemctl restart whiteboard-agent", false));
      }
      list.innerHTML = "<ul class='analysis-list'>" + items.join("") + "</ul>";
    }
    async function refreshStatus() {
      try {
        const r = await fetch("/api/status");
        const d = await r.json();
        renderAnalysis(d);
        document.getElementById("diff-img").src = "/last_diff.png?t=" + Date.now();
      } catch (_) {}
    }
    const diffImg = document.getElementById("diff-img");
    const diffFallback = document.getElementById("diff-fallback");
    diffImg.onerror = () => { diffImg.style.display = "none"; diffFallback.style.display = "flex"; };
    diffImg.onload = () => { diffImg.style.display = "block"; diffFallback.style.display = "none"; };
    const lastSavedImg = document.getElementById("last-saved-img");
    const lastSavedFallback = document.getElementById("last-saved-fallback");
    lastSavedImg.onerror = () => { lastSavedImg.style.display = "none"; lastSavedFallback.style.display = "flex"; };
    lastSavedImg.onload = () => { lastSavedImg.style.display = ""; lastSavedFallback.style.display = "none"; };
    const preview = document.getElementById("preview");
    const previewBox = document.getElementById("preview-box");
    const statusEl = document.getElementById("preview-status");
    preview.onerror = () => {
      previewBox.classList.add("has-error");
      statusEl.textContent = "Žádný snímek – kamera možná neběží";
    };
    preview.onload = () => {
      previewBox.classList.remove("has-error");
      statusEl.textContent = "Živý přenos z kamery";
    };
    async function refreshDebug() {
      try {
        const r = await fetch("/api/debug");
        const d = await r.json();
        const pre = document.getElementById("debug-output");
        if (pre) {
          const lines = [
            "config_path: " + (d.config_path || "-"),
            "config_ok: " + (d.config_ok === true ? "ano" : (d.config_ok === false ? "ne - " + (d.config_error || "") : "-")),
            "stream_updated_ago: " + (d.stream_updated_ago != null ? d.stream_updated_ago + " s" : "nikdy"),
            "last_jpg_age: " + (d.last_jpg_age != null ? d.last_jpg_age + " s" : "-"),
            "last_jpg_time: " + (d.last_jpg_time || "-"),
            "stream_active: " + (d.stream_active ? "ano" : "ne"),
            "hint: " + (d.hint || "-"),
          ];
          pre.textContent = lines.join("\\n");
        }
      } catch (_) {}
    }
    function updateLiveDateTime() {
      const now = new Date();
      const pad = n => String(n).padStart(2, "0");
      const t = pad(now.getDate()) + "." + pad(now.getMonth()+1) + "." + now.getFullYear() + " " + pad(now.getHours()) + ":" + pad(now.getMinutes()) + ":" + pad(now.getSeconds());
      window._lastLiveTime = t;
      const liveMeta = document.getElementById("live-meta");
      if (liveMeta) liveMeta.textContent = t + " | " + (window._lastBrightnessText || "Jas: -");
    }
    setInterval(updateLiveDateTime, 1000);
    updateLiveDateTime();
    setInterval(() => {
      refreshFileInfo();
      refreshStatus();
      refreshDebug();
    }, 1500);
    load().then(() => { refreshFileInfo(); refreshStatus(); refreshDebug(); });
  </script>
</body>
</html>
'''


@app.route("/")
def index():
    return render_template_string(INDEX_HTML, version=get_version())


@app.route("/api/files")
def api_files():
    """Vrátí datum/čas poslední úpravy souborů v last_dir."""
    import time
    last_dir = app.config.get("LAST_DIR")
    if not last_dir:
        return jsonify({"last.jpg": None, "last_saved.jpg": None, "last_diff.png": None, "last_ocr.txt": None})
    out = {}
    now = time.time()
    for name in ("last.jpg", "last_saved.jpg", "last_diff.png", "last_ocr.txt"):
        p = Path(last_dir) / name
        if p.exists():
            mtime = p.stat().st_mtime
            t = datetime.fromtimestamp(mtime)
            out[name] = t.strftime("%d.%m.%Y %H:%M:%S")
            if name == "last.jpg":
                out["_last_jpg_age"] = int(now - mtime)
        else:
            out[name] = None
    return jsonify(out)


@app.route("/api/make_last", methods=["POST"])
def api_make_last():
    """Zkopíruje aktuální last.jpg jako last_saved.jpg – referenční snímek pro porovnání."""
    last_dir = app.config.get("LAST_DIR")
    if not last_dir:
        return jsonify({"ok": False, "error": "last_dir není nastaven"}), 500
    src = Path(last_dir) / "last.jpg"
    dst = Path(last_dir) / "last_saved.jpg"
    if not src.exists():
        return jsonify({"ok": False, "error": "last.jpg neexistuje – počkej na snímek z kamery"}), 400
    try:
        shutil.copy2(src, dst)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/status")
def api_status():
    """Vrátí status.json (brightness, state, …) pro zobrazení v UI."""
    try:
        cfg = load_cfg()
        p = Path(cfg.get("logging", {}).get("status_file", "/opt/whiteboard-agent/data/status.json"))
        if p.exists():
            return jsonify(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        pass
    return jsonify({})


@app.route("/api/debug")
def api_debug():
    """Debug výstup pro ověření stavu kamery a Live streamu."""
    last_dir = app.config.get("LAST_DIR")
    now = time.time()
    out = {"ok": True}

    # Config – cesta a zda se načte
    out["config_path"] = CFG_PATH
    try:
        load_cfg()
        out["config_ok"] = True
    except Exception as e:
        out["config_ok"] = False
        out["config_error"] = str(e)

    # Stream buffer – kdy naposledy main.py poslal frame
    t = get_last_stream_update()
    out["stream_updated_ago"] = round(now - t, 1) if t > 0 else None
    out["stream_active"] = t > 0 and (now - t) < 15

    # last.jpg z disku
    if last_dir:
        p = Path(last_dir) / "last.jpg"
        if p.exists():
            mtime = p.stat().st_mtime
            out["last_jpg_age"] = round(now - mtime, 1)
            out["last_jpg_time"] = datetime.fromtimestamp(mtime).strftime("%H:%M:%S")
        else:
            out["last_jpg_age"] = None
            out["last_jpg_time"] = None
    else:
        out["last_jpg_age"] = None
        out["last_jpg_time"] = None

    # Diagnostika
    if out["stream_updated_ago"] is None or out["stream_updated_ago"] > 30:
        out["hint"] = "Kamera nesnímá. Na RPi: journalctl -u whiteboard-agent -n 30"
    elif out["stream_updated_ago"] > 10:
        out["hint"] = "Stream se aktualizuje pomalu – zkontroluj interval_seconds v config"
    else:
        out["hint"] = "OK – kamera snímá"

    return jsonify(out)


@app.route("/api/config", methods=["GET"])
def api_config_get():
    try:
        cfg = load_cfg()
        return jsonify(cfg)
    except Exception as e:
        return jsonify({"error": str(e), "config_path": CFG_PATH}), 500


@app.route("/api/config", methods=["POST"])
def api_config_post():
    try:
        cfg = load_cfg()
        data = request.get_json() or {}
        for key in ("capture", "processing", "ocr"):
            if key in data and isinstance(data[key], dict):
                cfg.setdefault(key, {}).update(data[key])
        # Ověř backend
        b = str(cfg.get("capture", {}).get("backend", "")).strip().lower()
        if b and b not in ("picamera2", "opencv"):
            cfg.setdefault("capture", {})["backend"] = "opencv"
        save_cfg(cfg)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _stream_frame_bytes():
    """Vrátí aktuální frame nebo načte last.jpg z disku jako fallback."""
    frame = get_stream_frame()
    if frame:
        return frame
    last_dir = app.config.get("LAST_DIR")
    if last_dir:
        p = Path(last_dir) / "last.jpg"
        if p.exists():
            try:
                return p.read_bytes()
            except Exception:
                pass
    return None


@app.route("/stream")
@app.route("/live")
def stream_mjpeg():
    """MJPEG živý přenos – <img src='/stream'> zobrazí živý záběr z kamery."""
    def generate():
        boundary = b"frame"
        while True:
            frame = _stream_frame_bytes()
            if frame:
                yield b"--" + boundary + b"\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(0.1)
    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


def init_app(last_dir: Path):
    """Registruje routy pro last.jpg, last_diff.png, last_ocr.txt."""
    app.config["LAST_DIR"] = last_dir

    @app.route("/last.jpg")
    @app.route("/last_saved.jpg")
    @app.route("/last_diff.png")
    @app.route("/last_ocr.txt")
    @app.route("/last_ocr_input.png")
    def serve_last():
        r = send_from_directory(app.config["LAST_DIR"], request.path.strip("/"))
        r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        r.headers["Pragma"] = "no-cache"
        r.headers["Expires"] = "0"
        return r
