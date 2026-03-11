#!/usr/bin/env python3
import io, os, sys, time, json, shutil, hashlib, datetime as dt
from pathlib import Path
from threading import Thread
from typing import Optional, Tuple

import yaml, requests
import numpy as np
from PIL import Image

try:
    import cv2
except Exception:
    cv2 = None

try:
    import pytesseract
except Exception:
    pytesseract = None


def now_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


def load_cfg():
    cfg_path = os.environ.get("WHITEBOARD_AGENT_CONFIG", "/opt/whiteboard-agent/config.yaml")
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_dirs(cfg):
    for p in [cfg["storage"]["base_dir"], cfg["storage"]["queue_dir"], cfg["storage"]["last_dir"], os.path.dirname(cfg["logging"]["status_file"])]:
        Path(p).mkdir(parents=True, exist_ok=True)


def get_flask_app(cfg):
    """Vrátí Flask app pro web UI + servírování last souborů."""
    live = cfg.get("live_server", {})
    if not live.get("enabled", False):
        return None
    last_dir = Path(cfg["storage"]["last_dir"])
    last_dir.mkdir(parents=True, exist_ok=True)
    from webapp import app, init_app
    init_app(last_dir)
    return app


class Capture:
    def __init__(self, cfg):
        self.cfg = cfg
        backend = str(cfg["capture"].get("backend") or "picamera2").strip().lower()
        if backend not in ("picamera2", "opencv"):
            backend = "opencv"
        self.rotate = int(cfg["capture"].get("rotate", 0) or 0)
        self.width = int(cfg["capture"]["width"])
        self.height = int(cfg["capture"]["height"])

        self.picam2 = None
        self.cap = None
        self.backend = None

        if backend == "picamera2":
            try:
                from picamera2 import Picamera2
                self.picam2 = Picamera2()
                config = self.picam2.create_still_configuration(main={"size": (self.width, self.height)})
                self.picam2.configure(config)
                self.picam2.start()
                time.sleep(1.0)
                self.backend = "picamera2"
            except Exception as e:
                print(f"[cam] picamera2 selhal ({e}), pouzivam opencv", file=sys.stderr)
                backend = "opencv"

        if backend == "opencv":
            if cv2 is None:
                raise RuntimeError("OpenCV not available (install python3-opencv) for opencv backend")
            self.backend = "opencv"
            base_idx = int(cfg["capture"].get("camera_index", 0))
            # Na RPi může být video10, video11... – zkus cestu i index
            dev_dir = Path("/dev")
            video_devs = sorted(
                [f"/dev/{d}" for d in dev_dir.iterdir() if d.name.startswith("video") and d.name[5:].isdigit()],
                key=lambda x: (len(x), x)
            )
            # Přidej indexy pro kompatibilitu
            sources = [f"/dev/video{base_idx}"] if f"/dev/video{base_idx}" in video_devs else []
            sources = sources + [d for d in video_devs if d not in sources][:8]
            if not sources:
                sources = ["/dev/video0", 0, 1, 2]
            resolutions = [(1920, 1080), (self.width, self.height), (1640, 1232), (1280, 720), (640, 480)]
            resolutions = [(w, h) for w, h in resolutions if (w, h) not in ((3280, 2465), (3280, 2464))]
            last_err = None
            for src in sources:
                for w, h in resolutions:
                    try:
                        cap_try = cv2.VideoCapture(src, cv2.CAP_V4L2)
                        cap_try.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                        cap_try.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
                        ok, _ = cap_try.read()
                        if ok:
                            self.cap = cap_try
                            self.width, self.height = w, h
                            print(f"[cam] OpenCV: {src}, {w}x{h}", file=sys.stderr)
                            break
                        cap_try.release()
                    except Exception as e:
                        last_err = e
                if self.cap:
                    break
            if not self.cap or not self.cap.isOpened():
                msg = "Cannot open camera"
                if last_err:
                    msg += f" ({last_err})"
                msg += ". Spusť check_camera.py pro diagnostiku."
                raise RuntimeError(msg)

    def close(self):
        try:
            if self.picam2:
                self.picam2.stop()
        except Exception:
            pass
        try:
            if self.cap:
                self.cap.release()
        except Exception:
            pass

    def _rotate(self, img: Image.Image) -> Image.Image:
        if self.rotate == 90:
            return img.rotate(-90, expand=True)
        if self.rotate == 180:
            return img.rotate(180, expand=True)
        if self.rotate == 270:
            return img.rotate(-270, expand=True)
        return img

    def capture_pil(self) -> Image.Image | None:
        """Vrátí snímek nebo None při selhání."""
        try:
            if self.picam2:
                arr = self.picam2.capture_array()
                img = Image.fromarray(arr)
            else:
                for _ in range(5):
                    ok, frame = self.cap.read()
                    if ok and frame is not None and frame.size > 0:
                        frame = frame[:, :, ::-1]  # BGR->RGB
                        img = Image.fromarray(frame)
                        return self._rotate(img)
                    time.sleep(0.3)
                return None
            return self._rotate(img)
        except Exception:
            return None


def write_status(cfg, payload):
    p = cfg["logging"]["status_file"]
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, p)


def apply_brightness_contrast(rgb: np.ndarray, cfg) -> np.ndarray:
    """Jas a kontrast: 100 = bez změny, 0–200."""
    b = float(cfg["capture"].get("brightness", 100)) / 100.0
    c = float(cfg["capture"].get("contrast", 100)) / 100.0
    if abs(b - 1.0) < 0.01 and abs(c - 1.0) < 0.01:
        return rgb
    arr = rgb.astype(np.float32)
    arr = arr * b
    arr = (arr - 128) * c + 128
    return np.clip(arr, 0, 255).astype(np.uint8)


def clahe(gray: np.ndarray, cfg) -> np.ndarray:
    limit = float(cfg["processing"].get("clahe_clip_limit", 2.0))
    if cv2 is None:
        g = gray.astype(np.float32)
        g = (g - g.min()) / max(1e-6, (g.max() - g.min()))
        return (g * 255).astype(np.uint8)
    c = cv2.createCLAHE(clipLimit=limit, tileGridSize=(8, 8))
    return c.apply(gray)


def perspective(gray: np.ndarray, cfg) -> np.ndarray:
    if not cfg["processing"].get("perspective_enabled", False) or cv2 is None:
        return gray
    corners = np.array(cfg["processing"]["perspective_corners"], dtype=np.float32)
    out_w, out_h = cfg["processing"]["perspective_output_size"]
    dst = np.array([[0, 0], [out_w-1, 0], [out_w-1, out_h-1], [0, out_h-1]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(gray, M, (out_w, out_h))


def crop(gray: np.ndarray, roi: dict) -> np.ndarray:
    x, y, w, h = int(roi["x"]), int(roi["y"]), int(roi["w"]), int(roi["h"])
    return gray[y:y+h, x:x+w]


def normalize_brightness(cur: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """Škáluje cur tak, aby měl podobný průměrný jas jako ref. Snižuje falešné detekce při stmívání/rozednívání."""
    m_ref = float(np.mean(ref))
    m_cur = float(np.mean(cur))
    if m_cur < 1:
        return cur
    scale = m_ref / m_cur
    # Při extrémním rozdílu (scale mimo 0.7–1.4) použij aditivní normalizaci – zabraňuje saturaci
    if scale > 1.4 or scale < 0.7:
        offset = m_ref - m_cur
        return np.clip((cur.astype(np.float32) + offset).astype(np.uint8), 0, 255)
    return np.clip((cur.astype(np.float32) * scale).astype(np.uint8), 0, 255)


def brightness_change_ratio(cur: np.ndarray, ref: np.ndarray) -> float:
    """Relativní rozdíl průměrného jasu (0 = stejné, 0.5 = 50 % rozdíl)."""
    m_ref = float(np.mean(ref))
    m_cur = float(np.mean(cur))
    if m_ref < 1:
        return 0.0
    return abs(m_cur - m_ref) / m_ref


def load_last_saved(cfg) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Načte last_saved.jpg. Vrátí (gray_roi, rgb_roi) pro porovnání, nebo None."""
    path = Path(cfg["storage"]["last_dir"]) / "last_saved.jpg"
    if not path.exists():
        return None
    try:
        img = Image.open(path)
        rgb = np.array(img)
        if cv2 is not None:
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        else:
            gray = (0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]).astype(np.uint8)
        gray = clahe(gray, cfg)
        return gray, rgb
    except Exception:
        return None


def binarize(gray: np.ndarray, cfg) -> np.ndarray:
    """Adaptive thresholding for robust text detection."""
    if cv2 is None:
        return (gray > 128).astype(np.uint8) * 255
    
    # Default values if not in config
    block_size = int(cfg["processing"].get("adaptive_block_size", 21))
    if block_size % 2 == 0: block_size += 1
    c = float(cfg["processing"].get("adaptive_c", 10))
    
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block_size, c)


def change_metric(prev: np.ndarray, cur: np.ndarray, cfg):
    """Porovná dva snímky. Podporuje 'adaptive' (robustní) a 'legacy' (pixel diff)."""
    mode = cfg["processing"].get("detection_mode", "legacy")
    
    if mode == "adaptive" and cv2 is not None:
        # 1. Blur to remove high-frequency noise (grain)
        # Low light produces grain that looks like pixel changes. Stronger blur helps.
        prev_blur = cv2.GaussianBlur(prev, (5, 5), 0)
        cur_blur = cv2.GaussianBlur(cur, (5, 5), 0)

        # 2. Binarize both images (robust against lighting)
        bin_prev = binarize(prev_blur, cfg)
        bin_cur = binarize(cur_blur, cfg)

        # 3. XOR to find differences
        diff = cv2.bitwise_xor(bin_prev, bin_cur)

        # 4. Remove noise (small specks)
        kernel = np.ones((3, 3), np.uint8)
        diff = cv2.morphologyEx(diff, cv2.MORPH_OPEN, kernel)
        
        # 5. Contour filtering - only count changes that look like "strokes"
        # Noise is usually scattered small dots. Writing is connected lines.
        contours, _ = cv2.findContours(diff, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        mask_cleaned = np.zeros_like(diff)
        min_area = 15 # Minimum area for a "stroke" segment
        for c in contours:
            if cv2.contourArea(c) > min_area:
                cv2.drawContours(mask_cleaned, [c], -1, 255, -1)

        pct = float(np.count_nonzero(mask_cleaned)) / float(diff.size) * 100.0
        return pct, mask_cleaned
        
    else:
        # Legacy mode (sensitive to light)
        pixel_threshold = int(cfg["processing"].get("pixel_threshold", 30))
        if cv2 is not None:
            a = cv2.GaussianBlur(prev, (5, 5), 0)
            b = cv2.GaussianBlur(cur, (5, 5), 0)
            d = cv2.absdiff(a, b)
            _, th = cv2.threshold(d, pixel_threshold, 255, cv2.THRESH_BINARY)
            th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        else:
            d = np.abs(prev.astype(np.int16) - cur.astype(np.int16)).astype(np.uint8)
            th = (d > pixel_threshold).astype(np.uint8) * 255
        pct = float(np.count_nonzero(th)) / float(th.size) * 100.0
        return pct, th


def overlay(rgb: np.ndarray, mask: np.ndarray) -> Image.Image:
    out = rgb.copy()
    m = mask > 0
    out[m, 0] = 255
    out[m, 1] = (out[m, 1] * 0.4).astype(np.uint8)
    out[m, 2] = (out[m, 2] * 0.4).astype(np.uint8)
    return Image.fromarray(out)


def ocr(gray_roi: np.ndarray, cfg) -> str:
    if not cfg["ocr"].get("enabled", True) or pytesseract is None:
        if cfg["ocr"].get("enabled", True) and pytesseract is None:
            print("[ocr] pytesseract není nainstalován", file=sys.stderr)
        return ""
    lang = cfg["ocr"].get("lang", "ces")
    psm = int(cfg["ocr"].get("psm", 6))
    oem = int(cfg["ocr"].get("oem", 1))
    # Předzpracování: otsu | adaptive | none
    preprocess = cfg["ocr"].get("preprocess", "otsu")
    img_for_ocr = gray_roi
    if cv2 is not None and gray_roi.size > 0:
        if preprocess == "otsu":
            _, img_for_ocr = cv2.threshold(gray_roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        elif preprocess == "adaptive":
            img_for_ocr = cv2.adaptiveThreshold(gray_roi, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    # Tesseract potřebuje min. ~300px – zvětšení pomáhá
    min_side = cfg["ocr"].get("min_side", 300)
    h, w = img_for_ocr.shape[:2]
    if min(w, h) < min_side and cv2 is not None:
        scale = min_side / min(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        img_for_ocr = cv2.resize(img_for_ocr, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    try:
        txt = pytesseract.image_to_string(img_for_ocr, lang=lang, config=f"--oem {oem} --psm {psm}")
        result = txt.strip()
        if not result:
            print("[ocr] Prázdný výstup – zkontroluj ROI (x,y,w,h) zda obsahuje text", file=sys.stderr)
        return result
    except Exception as e:
        print(f"[ocr] Chyba: {e}", file=sys.stderr)
        return ""


def save_jpeg(img: Image.Image, path: Path, quality=90):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=int(quality), optimize=True)


def img_to_jpeg_bytes(img: Image.Image, quality=85) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=int(quality), optimize=True)
    return buf.getvalue()


def _push_stream_frame(img_roi):
    """Aktualizuje MJPEG stream. Volá se při každém zachyceném snímku."""
    try:
        from webapp import update_stream_frame
        update_stream_frame(img_to_jpeg_bytes(img_roi, 85))
    except Exception:
        pass


def save_png(img: Image.Image, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG", optimize=True)


def send(cfg, meta, frame_path: Path, diff_path: Path, frame_before_path: Path = None) -> bool:
    url = cfg["hub"]["url"]
    token = cfg["hub"].get("token", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    files = {
        "frame": ("frame.jpg", open(frame_path, "rb"), "image/jpeg"),
        "diff": ("diff.png", open(diff_path, "rb"), "image/png"),
    }
    if frame_before_path and frame_before_path.exists():
        files["frame_before"] = ("frame_before.jpg", open(frame_before_path, "rb"), "image/jpeg")
    data = {
        "device_id": meta["device_id"],
        "ts": meta["ts"],
        "change_percent": f"{meta['change_percent']:.4f}",
        "ocr_text": meta.get("ocr_text", ""),
    }
    try:
        r = requests.post(url, data=data, files=files, headers=headers, timeout=15)
        ok = r.status_code // 100 == 2
        if not ok:
            print(f"[cam] Hub odmítl: {r.status_code} {r.text[:200]}", file=sys.stderr)
        return ok
    except Exception as e:
        print(f"[cam] Hub nedostupný: {e}", file=sys.stderr)
        return False
    finally:
        for f in files.values():
            try: f[1].close()
            except Exception: pass


def enqueue(cfg, meta, frame_path: Path, diff_path: Path, frame_before_path: Path = None):
    qdir = Path(cfg["storage"]["queue_dir"])
    qdir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1((meta["ts"] + meta["device_id"]).encode()).hexdigest()[:12]
    b = qdir / f"{meta['ts'].replace(':','').replace('-','').replace('T','_')}_{key}"
    b.mkdir(parents=True, exist_ok=True)
    (b/"meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    shutil.copy2(frame_path, b/"frame.jpg")
    shutil.copy2(diff_path, b/"diff.png")
    if frame_before_path and frame_before_path.exists():
        shutil.copy2(frame_before_path, b/"frame_before.jpg")


def flush_queue(cfg):
    qdir = Path(cfg["storage"]["queue_dir"])
    if not qdir.exists():
        return
    for b in sorted(qdir.glob("*")):
        if not b.is_dir():
            continue
        try:
            meta = json.loads((b/"meta.json").read_text(encoding="utf-8"))
            fb = b / "frame_before.jpg"
            ok = send(cfg, meta, b/"frame.jpg", b/"diff.png", fb if fb.exists() else None)
            if ok:
                shutil.rmtree(b, ignore_errors=True)
            else:
                break
        except Exception:
            continue


def cleanup(cfg):
    keep_days = int(cfg["storage"].get("keep_local_days", 7))
    if keep_days <= 0:
        return
    cutoff = dt.datetime.now() - dt.timedelta(days=keep_days)
    root = Path(cfg["storage"]["base_dir"]) / "events"
    if not root.exists():
        return
    for p in root.rglob("*"):
        try:
            if dt.datetime.fromtimestamp(p.stat().st_mtime) < cutoff:
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)
        except Exception:
            pass


def camera_loop():
    """Smyčka kamery – běží v threadu, nikdy nepadá. Flask zůstává hlavní proces."""
    cap = None
    fail_count = 0
    prev = None
    hits = 0
    last_event = 0.0
    last_live_save = 0.0
    last_dark_log = 0.0
    ref_frame = None
    ref_rgb_roi = None
    prev_rgb_roi = None
    wait_stable = False
    stable_count = 0
    status = {}

    cfg = {}
    while True:
        try:
            cfg = load_cfg()
            ensure_dirs(cfg)
            if cap is None:
                cap = Capture(cfg)
                fail_count = 0
                status = {"ts": now_iso(), "device_id": cfg["device_id"], "state": "running"}
                write_status(cfg, status)
        except Exception as e:
            print(f"[cam] Init: {e}", file=sys.stderr)
            fail_count += 1
            time.sleep(min(30, 5 * fail_count))
            continue

        t0 = time.time()
        try:
            flush_queue(cfg)
            cfg = load_cfg()
            img = cap.capture_pil()
            if img is None:
                fail_count += 1
                if fail_count > 10:
                    print(f"[cam] Opakované selhání, restartuji kameru...", file=sys.stderr)
                    cap.close()
                    cap = None
                    fail_count = 0
                time.sleep(2)
                continue
            fail_count = 0
            rgb = np.array(img)
            rgb = apply_brightness_contrast(rgb, cfg)

            roi = cfg["processing"]["roi"]
            rgb_roi = crop(rgb, roi)
            img_roi = Image.fromarray(rgb_roi)

            if cv2 is not None:
                gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            else:
                gray = (0.299*rgb[:,:,0] + 0.587*rgb[:,:,1] + 0.114*rgb[:,:,2]).astype(np.uint8)

            gray = perspective(gray, cfg)
            gray = clahe(gray, cfg)
            g_roi = crop(gray, roi)

            # Min. osvětlení – při nedostatečném světle nic neposílat
            brightness = float(np.mean(g_roi))
            min_bright = cfg.get("processing", {}).get("min_brightness")
            if min_bright is not None and brightness < float(min_bright):
                if time.time() - last_dark_log >= 60:
                    print(f"[cam] Nedostatečné osvětlení (brightness={brightness:.0f} < {min_bright})", file=sys.stderr)
                    last_dark_log = time.time()
                status.update({
                    "ts": now_iso(),
                    "brightness": round(brightness, 1),
                    "state": "low_light",
                    "block_reason": "nedostatečné osvětlení",
                    "analysis": {"min_brightness": min_bright, "brightness_ok": False},
                })
                write_status(cfg, status)
                try:
                    save_jpeg(img_roi, Path(cfg["storage"]["last_dir"]) / "last.jpg", quality=85)
                    _push_stream_frame(img_roi)
                except Exception:
                    pass
                try:
                    interval = float(cfg.get("processing", {}).get("interval_seconds", 3))
                except Exception:
                    interval = 3
                remaining = max(0.5, interval - (time.time() - t0))
                while remaining > 1.0 and cap is not None:
                    time.sleep(1.0)
                    remaining -= 1.0
                    try:
                        img = cap.capture_pil()
                        if img is not None:
                            rgb = np.array(img)
                            rgb = apply_brightness_contrast(rgb, cfg)
                            roi = cfg["processing"]["roi"]
                            rgb_roi = crop(rgb, roi)
                            img_roi = Image.fromarray(rgb_roi)
                            save_jpeg(img_roi, Path(cfg["storage"]["last_dir"]) / "last.jpg", quality=85)
                            _push_stream_frame(img_roi)
                    except Exception:
                        pass
                time.sleep(remaining)
                continue

            pct = 0.0
            mask_roi = None
            illum_inv = cfg.get("processing", {}).get("illumination_invariant", True)
            mode = cfg["processing"].get("detection_mode", "legacy")
            
            # Porovnání last_saved vs current
            last_saved_data = load_last_saved(cfg)
            last_saved_gray = last_saved_data[0] if last_saved_data and last_saved_data[0].shape == g_roi.shape else None
            last_saved_rgb = last_saved_data[1] if last_saved_data and last_saved_data[0].shape == g_roi.shape else None
            ref_for_diff = last_saved_gray if last_saved_gray is not None else prev
            
            if ref_for_diff is not None and ref_for_diff.shape == g_roi.shape:
                cur_compare = normalize_brightness(g_roi, ref_for_diff) if (illum_inv and mode == "legacy") else g_roi
                pct, mask_roi = change_metric(ref_for_diff, cur_compare, cfg)

            # pct_motion = prev vs current – pro ustálení
            pct_motion = 0.0
            if prev is not None and prev.shape == g_roi.shape:
                cur_motion = normalize_brightness(g_roi, prev) if (illum_inv and mode == "legacy") else g_roi
                pct_motion, _ = change_metric(prev, cur_motion, cfg)

            thr = float(cfg["processing"]["change_threshold_percent"])
            if pct >= thr:
                if hits == 0:
                    ref_frame = last_saved_gray.copy() if last_saved_gray is not None else (prev.copy() if prev is not None else g_roi.copy())
                    ref_rgb_roi = last_saved_rgb.copy() if last_saved_rgb is not None else (prev_rgb_roi.copy() if prev_rgb_roi is not None else rgb_roi.copy())
                hits += 1
            else:
                hits = 0
            prev = g_roi.copy()
            prev_rgb_roi = rgb_roi.copy()

            if time.time() - last_live_save >= 1.0:
                last_dir = Path(cfg["storage"]["last_dir"])
                try:
                    save_jpeg(img_roi, last_dir / "last.jpg", quality=85)
                    _push_stream_frame(img_roi)
                except Exception as e:
                    print(f"[last] last.jpg: {e}", file=sys.stderr)
                try:
                    if mask_roi is not None:
                        save_png(overlay(rgb_roi, mask_roi), last_dir / "last_diff.png")
                    else:
                        save_png(img_roi, last_dir / "last_diff.png")
                except Exception as e:
                    print(f"[last] last_diff.png: {e}", file=sys.stderr)
                try:
                    ocr_txt = ocr(g_roi, cfg)
                    (last_dir / "last_ocr.txt").write_text(ocr_txt, encoding="utf-8", errors="ignore")
                    if cv2 is not None and cfg["ocr"].get("debug_save_input", False):
                        _, bin_img = cv2.threshold(g_roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                        Image.fromarray(bin_img).save(last_dir / "last_ocr_input.png")
                except Exception as e:
                    print(f"[last] last_ocr.txt: {e}", file=sys.stderr)
                last_live_save = time.time()

            need = int(cfg["processing"]["consecutive_hits"])
            cooldown = int(cfg["processing"]["cooldown_seconds"])
            stab_enabled = cfg.get("processing", {}).get("stabilization_enabled", True)
            stab_frames = int(cfg.get("processing", {}).get("stabilization_frames", 3))
            
            # Brightness check logic (only for legacy mode mostly)
            max_bright = float(cfg.get("processing", {}).get("max_brightness_change_percent", 35)) / 100.0
            
            def check_brightness(curr, ref):
                if mode == "adaptive": return True # Adaptive mode ignores brightness shifts
                if ref is None: return True
                return brightness_change_ratio(curr, ref) <= max_bright

            event_mask = None
            pct_event = pct
            skipped_brightness = False
            
            should_send = False
            
            # Logic:
            # 1. Hits >= Need
            # 2. Cooldown passed
            # 3. Stabilization (optional)
            
            if hits >= need and (time.time() - last_event) >= cooldown and mask_roi is not None:
                # Basic conditions met. Now check stabilization.
                if stab_enabled:
                    if wait_stable:
                        # Waiting for motion to stop
                        if pct_motion < thr:
                            stable_count += 1
                        else:
                            stable_count = 0
                        
                        if stable_count >= stab_frames:
                            # Stable now. Check against ref_frame (start of event)
                            if ref_frame is not None and ref_frame.shape == g_roi.shape:
                                cur_compare = normalize_brightness(g_roi, ref_frame) if (illum_inv and mode == "legacy") else g_roi
                                pct_ref, mask_ref = change_metric(ref_frame, cur_compare, cfg)
                                
                                if pct_ref >= thr:
                                    if check_brightness(g_roi, ref_frame):
                                        should_send = True
                                        event_mask = mask_ref
                                        pct_event = pct_ref
                                    else:
                                        skipped_brightness = True
                                else:
                                    # Change disappeared during stabilization (false alarm)
                                    hits = 0
                            
                            wait_stable = False
                            stable_count = 0
                            ref_frame = None
                    else:
                        # Start stabilization
                        wait_stable = True
                        stable_count = 0
                else:
                    # No stabilization, send immediately
                    if check_brightness(g_roi, ref_frame):
                        should_send = True
                        event_mask = mask_roi
                    else:
                        skipped_brightness = True

            block_reason = None
            if wait_stable:
                status["stabilization"] = f"čeká na ustálení ({stable_count}/{stab_frames})"
                block_reason = f"ustálení {stable_count}/{stab_frames}"
            else:
                status.pop("stabilization", None)
                if not should_send:
                    if skipped_brightness:
                        block_reason = "rozdíl jasu (jen osvětlení)"
                    elif hits < need:
                        block_reason = f"hitů {hits}/{need}"
                    elif (time.time() - last_event) < cooldown:
                        block_reason = f"cooldown {int(cooldown - (time.time() - last_event))}s"

            if block_reason:
                status["block_reason"] = block_reason
            else:
                status.pop("block_reason", None)
                
            cooldown_remaining = max(0, cooldown - (time.time() - last_event))
            
            analysis = {
                "mode": mode,
                "min_brightness": min_bright,
                "change_threshold": thr,
                "pct": round(float(pct), 2),
                "pct_ok": pct >= thr,
                "hits": hits,
                "need": need,
                "cooldown_remaining": round(cooldown_remaining, 1),
                "wait_stable": wait_stable,
                "stable_count": stable_count,
                "stab_frames": stab_frames,
            }
            status.update({
                "ts": now_iso(),
                "state": "running",
                "brightness": round(float(np.mean(g_roi)), 1),
                "last_change_percent": float(pct),
                "hits": hits,
                "analysis": analysis,
            })
            write_status(cfg, status)

            if should_send and event_mask is not None:
                ov = overlay(rgb_roi, event_mask)
                save_png(ov, Path(cfg["storage"]["last_dir"]) / "last_diff.png")
                date = dt.datetime.now().strftime("%Y-%m-%d")
                stamp = dt.datetime.now().strftime("%H%M%S")
                ev_dir = Path(cfg["storage"]["base_dir"]) / "events" / date / stamp
                ev_dir.mkdir(parents=True, exist_ok=True)
                frame_path = ev_dir / "frame.jpg"
                frame_before_path = ev_dir / "frame_before.jpg"
                diff_path = ev_dir / "diff.png"
                if ref_rgb_roi is not None:
                    save_jpeg(Image.fromarray(ref_rgb_roi), frame_before_path, quality=int(cfg["capture"].get("jpeg_quality", 90)))
                save_jpeg(img_roi, frame_path, quality=int(cfg["capture"].get("jpeg_quality", 90)))
                shutil.copy2(frame_path, Path(cfg["storage"]["last_dir"]) / "last_saved.jpg")
                save_png(ov, diff_path)
                ocr_text = ocr(g_roi, cfg)
                (Path(cfg["storage"]["last_dir"]) / "last_ocr.txt").write_text(ocr_text, encoding="utf-8", errors="ignore")
                save_jpeg(img_roi, Path(cfg["storage"]["last_dir"]) / "last.jpg", quality=85)
                _push_stream_frame(img_roi)
                save_png(ov, Path(cfg["storage"]["last_dir"]) / "last_diff.png")
                meta = {"device_id": cfg["device_id"], "ts": now_iso(), "change_percent": float(pct_event), "ocr_text": ocr_text}
                fb = frame_before_path if frame_before_path.exists() else None
                ok = send(cfg, meta, frame_path, diff_path, fb)
                if not ok:
                    enqueue(cfg, meta, frame_path, diff_path, fb)
                status["last_event"] = meta
                write_status(cfg, status)
                hits = 0
                ref_rgb_roi = None
                last_event = time.time()

            cleanup(cfg)
        except Exception as e:
            print(f"[cam] {e}", file=sys.stderr)
            time.sleep(2)

        try:
            interval = float(cfg.get("processing", {}).get("interval_seconds", 3))
        except Exception:
            interval = 3
        remaining = max(0.5, interval - (time.time() - t0))
        # Během čekání zachytávat každou sekundu pro live náhled (last.jpg)
        while remaining > 1.0 and cap is not None:
            time.sleep(1.0)
            remaining -= 1.0
            try:
                img = cap.capture_pil()
                if img is not None:
                    rgb = np.array(img)
                    rgb = apply_brightness_contrast(rgb, cfg)
                    roi = cfg["processing"]["roi"]
                    rgb_roi = crop(rgb, roi)
                    img_roi = Image.fromarray(rgb_roi)
                    save_jpeg(img_roi, Path(cfg["storage"]["last_dir"]) / "last.jpg", quality=85)
                    _push_stream_frame(img_roi)
            except Exception:
                pass
        time.sleep(remaining)


def main():
    cfg = load_cfg()
    ensure_dirs(cfg)

    # Kamera v pozadí – nikdy nepadá
    cam_thread = Thread(target=camera_loop, daemon=True)
    cam_thread.start()

    # Flask hlavní – vždy běží, servíruje data
    app = get_flask_app(cfg)
    if app:
        live = cfg.get("live_server", {})
        port = int(live.get("port", 8081))
        bind = live.get("bind", "0.0.0.0")
        print(f"[web] http://{bind}:{port}/  |  last.jpg, last_diff.png, last_ocr.txt", file=sys.stderr)
        app.run(host=bind, port=port, threaded=True, use_reloader=False)
    else:
        # Bez webu – jen kamera
        cam_thread.join()


if __name__ == "__main__":
    main()
