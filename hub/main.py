#!/usr/bin/env python3
import os, time, json, shutil, hashlib, datetime as dt
from pathlib import Path

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
    cfg_path = os.environ.get("WHITEBOARD_AGENT_CONFIG", "/etc/whiteboard-agent/config.yaml")
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_dirs(cfg):
    for p in [cfg["storage"]["base_dir"], cfg["storage"]["queue_dir"], cfg["storage"]["last_dir"], os.path.dirname(cfg["logging"]["status_file"])]:
        Path(p).mkdir(parents=True, exist_ok=True)


class Capture:
    def __init__(self, cfg):
        self.cfg = cfg
        self.backend = cfg["capture"]["backend"]
        self.rotate = int(cfg["capture"].get("rotate", 0) or 0)
        self.width = int(cfg["capture"]["width"])
        self.height = int(cfg["capture"]["height"])

        self.picam2 = None
        self.cap = None

        if self.backend == "picamera2":
            from picamera2 import Picamera2
            self.picam2 = Picamera2()
            config = self.picam2.create_still_configuration(main={"size": (self.width, self.height)})
            self.picam2.configure(config)
            self.picam2.start()
            time.sleep(1.0)
        elif self.backend == "opencv":
            if cv2 is None:
                raise RuntimeError("OpenCV not available (install python3-opencv) for opencv backend")
            idx = int(cfg["capture"].get("camera_index", 0))
            self.cap = cv2.VideoCapture(idx)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            if not self.cap.isOpened():
                raise RuntimeError("Cannot open USB camera")
        else:
            raise ValueError("capture.backend must be picamera2|opencv")

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

    def capture_pil(self) -> Image.Image:
        if self.picam2:
            arr = self.picam2.capture_array()
            img = Image.fromarray(arr)
        else:
            ok, frame = self.cap.read()
            if not ok:
                raise RuntimeError("Failed to read frame")
            frame = frame[:, :, ::-1]  # BGR->RGB
            img = Image.fromarray(frame)
        return self._rotate(img)


def write_status(cfg, payload):
    p = cfg["logging"]["status_file"]
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, p)


def clahe(gray: np.ndarray) -> np.ndarray:
    if cv2 is None:
        g = gray.astype(np.float32)
        g = (g - g.min()) / max(1e-6, (g.max() - g.min()))
        return (g * 255).astype(np.uint8)
    c = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
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


def change_metric(prev: np.ndarray, cur: np.ndarray):
    if cv2 is not None:
        a = cv2.GaussianBlur(prev, (5, 5), 0)
        b = cv2.GaussianBlur(cur, (5, 5), 0)
        d = cv2.absdiff(a, b)
        _, th = cv2.threshold(d, 25, 255, cv2.THRESH_BINARY)
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    else:
        d = np.abs(prev.astype(np.int16) - cur.astype(np.int16)).astype(np.uint8)
        th = (d > 25).astype(np.uint8) * 255
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
        return ""
    lang = cfg["ocr"].get("lang", "ces")
    psm = int(cfg["ocr"].get("psm", 6))
    oem = int(cfg["ocr"].get("oem", 1))
    try:
        txt = pytesseract.image_to_string(gray_roi, lang=lang, config=f"--oem {oem} --psm {psm}")
        return txt.strip()
    except Exception:
        return ""


def save_jpeg(img: Image.Image, path: Path, quality=90):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=int(quality), optimize=True)


def save_png(img: Image.Image, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG", optimize=True)


def send(cfg, meta, frame_path: Path, diff_path: Path) -> bool:
    url = cfg["hub"]["url"]
    token = cfg["hub"].get("token", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    files = {
        "frame": ("frame.jpg", open(frame_path, "rb"), "image/jpeg"),
        "diff": ("diff.png", open(diff_path, "rb"), "image/png"),
    }
    data = {
        "device_id": meta["device_id"],
        "ts": meta["ts"],
        "change_percent": f"{meta['change_percent']:.4f}",
        "ocr_text": meta.get("ocr_text", ""),
    }
    try:
        r = requests.post(url, data=data, files=files, headers=headers, timeout=15)
        return r.status_code // 100 == 2
    except Exception:
        return False
    finally:
        for f in files.values():
            try: f[1].close()
            except Exception: pass


def enqueue(cfg, meta, frame_path: Path, diff_path: Path):
    qdir = Path(cfg["storage"]["queue_dir"])
    qdir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1((meta["ts"] + meta["device_id"]).encode()).hexdigest()[:12]
    b = qdir / f"{meta['ts'].replace(':','').replace('-','').replace('T','_')}_{key}"
    b.mkdir(parents=True, exist_ok=True)
    (b/"meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    shutil.copy2(frame_path, b/"frame.jpg")
    shutil.copy2(diff_path, b/"diff.png")


def flush_queue(cfg):
    qdir = Path(cfg["storage"]["queue_dir"])
    if not qdir.exists():
        return
    for b in sorted(qdir.glob("*")):
        if not b.is_dir():
            continue
        try:
            meta = json.loads((b/"meta.json").read_text(encoding="utf-8"))
            ok = send(cfg, meta, b/"frame.jpg", b/"diff.png")
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


def main():
    cfg = load_cfg()
    ensure_dirs(cfg)
    cap = Capture(cfg)

    prev = None
    hits = 0
    last_event = 0.0
    last_live_save = 0.0

    status = {"ts": now_iso(), "device_id": cfg["device_id"], "state": "running"}
    write_status(cfg, status)

    try:
        while True:
            t0 = time.time()
            flush_queue(cfg)

            img = cap.capture_pil()
            rgb = np.array(img)

            # ROI-only (jen tabule) pro live náhled / last.jpg
            roi = cfg["processing"]["roi"]
            rgb_roi = crop(rgb, roi)
            img_roi = Image.fromarray(rgb_roi)

            if cv2 is not None:
                gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            else:
                gray = (0.299*rgb[:,:,0] + 0.587*rgb[:,:,1] + 0.114*rgb[:,:,2]).astype(np.uint8)

            gray = perspective(gray, cfg)
            gray = clahe(gray)

            roi = cfg["processing"]["roi"]
            g_roi = crop(gray, roi)

            pct = 0.0
            mask_roi = None
            if prev is not None and prev.shape == g_roi.shape:
                pct, mask_roi = change_metric(prev, g_roi)
            prev = g_roi.copy()

            # Live náhled – last.jpg + last_diff.png (vždy, aby diff existoval i bez změny)
            if time.time() - last_live_save >= 1.0:
                try:
                    last_dir = Path(cfg["storage"]["last_dir"])
                    save_jpeg(img_roi, last_dir / "last.jpg", quality=85)
                    if mask_roi is not None:
                        save_png(overlay(rgb_roi, mask_roi), last_dir / "last_diff.png")
                    else:
                        # placeholder – prázdná maska = frame bez overlay
                        empty_mask = np.zeros(g_roi.shape, dtype=np.uint8)
                        save_png(overlay(rgb_roi, empty_mask), last_dir / "last_diff.png")
                    last_live_save = time.time()
                except Exception:
                    pass

            thr = float(cfg["processing"]["change_threshold_percent"])
            need = int(cfg["processing"]["consecutive_hits"])
            cooldown = int(cfg["processing"]["cooldown_seconds"])

            if pct >= thr:
                hits += 1
            else:
                hits = 0

            status.update({"ts": now_iso(), "last_change_percent": float(pct), "hits": hits})
            write_status(cfg, status)

            if hits >= need and (time.time() - last_event) >= cooldown and mask_roi is not None:
                # ROI-only overlay (jen tabule)
                ov = overlay(rgb_roi, mask_roi)
                # last_diff.png musí být stejné ROI jako last.jpg
                save_png(ov, Path(cfg["storage"]["last_dir"]) / "last_diff.png")

                date = dt.datetime.now().strftime("%Y-%m-%d")
                stamp = dt.datetime.now().strftime("%H%M%S")
                ev_dir = Path(cfg["storage"]["base_dir"]) / "events" / date / stamp
                ev_dir.mkdir(parents=True, exist_ok=True)

                frame_path = ev_dir / "frame.jpg"
                diff_path = ev_dir / "diff.png"
                save_jpeg(img_roi, frame_path, quality=int(cfg["capture"].get("jpeg_quality", 90)))
                save_png(ov, diff_path)

                ocr_text = ocr(g_roi, cfg)
                (Path(cfg["storage"]["last_dir"]) / "last_ocr.txt").write_text(ocr_text, encoding="utf-8", errors="ignore")
                save_jpeg(img_roi, Path(cfg["storage"]["last_dir"]) / "last.jpg", quality=85)
                save_png(ov, Path(cfg["storage"]["last_dir"]) / "last_diff.png")

                meta = {"device_id": cfg["device_id"], "ts": now_iso(), "change_percent": float(pct), "ocr_text": ocr_text}
                ok = send(cfg, meta, frame_path, diff_path)
                if not ok:
                    enqueue(cfg, meta, frame_path, diff_path)

                status["last_event"] = meta
                write_status(cfg, status)

                hits = 0
                last_event = time.time()

            cleanup(cfg)

            interval = float(cfg["processing"]["interval_seconds"])
            time.sleep(max(0.0, interval - (time.time()-t0)))

    finally:
        cap.close()


if __name__ == "__main__":
    main()
