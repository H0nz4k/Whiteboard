#!/usr/bin/env python3
"""Diagnostika kamery – spustit na RPi: ./venv/bin/python check_camera.py"""
import sys

print("=== Whiteboard Agent – kontrola kamery ===\n")

# 1. /dev/video*
import os
videos = sorted([d for d in os.listdir("/dev") if d.startswith("video")])
if videos:
    print(f"1. /dev/video*: {', '.join('/dev/' + v for v in videos)}")
else:
    print("1. /dev/video*: ŽÁDNÉ ZAŘÍZENÍ")
    print("   -> Kamera není viditelná. Zkontroluj:")
    print("   - raspi-config -> Interface Options -> Camera -> Enable")
    print("   - Pro libcamera: libcamera-hello --list-cameras")
    print("   - Pro CSI: možná potřebuješ libcamera-v4l2 (viz README)")

# 2. Skupina video
import grp
try:
    video_gid = grp.getgrnam("video").gr_gid
    in_video = video_gid in os.getgroups()
    print(f"\n2. Skupina 'video': {'ano' if in_video else 'NE – přidej: sudo usermod -aG video $USER'}")
except KeyError:
    print("\n2. Skupina 'video': neexistuje")

# 3. OpenCV – zkus každé /dev/video* přímo cestou
print("\n3. OpenCV (zkouším každé /dev/video*):")
try:
    import cv2
    print(f"   cv2 OK, verze {cv2.__version__}")
    for dev in sorted(videos, key=lambda x: (len(x), x)):
        path = f"/dev/{dev}"
        cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
        ok = cap.isOpened()
        if ok:
            ret, frame = cap.read()
            ok = ret and frame is not None and frame.size > 0
        cap.release()
        status = "OK" if ok else "selhal"
        print(f"   {path}: {status}")
except ImportError as e:
    print(f"   CHYBA: {e}")
    print("   -> pip install opencv-python-headless")

# 4. libcamera (RPi)
print("\n4. libcamera (RPi):")
r = os.system("libcamera-hello --list-cameras 2>/dev/null")
if r == 0:
    print("   libcamera-hello funguje")
else:
    print("   libcamera-hello neběží nebo není nainstalován")

print("\n=== Konec ===")
