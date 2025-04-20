#!/usr/bin/env python3
# hand_gesture_control_enhanced.py
# ---------------------------------------------------------------------------
# Responsive hand‑gesture slide controller with interactive layout editor
# ---------------------------------------------------------------------------
#!/usr/bin/env python3
# hand_gesture_control_enhanced_rect.py
# ---------------------------------------------------------------------------
# Responsive hand‑gesture slide controller with interactive layout editor
# (CENTER ZONE IS NOW A RECTANGLE, NOT A CIRCLE)
# ---------------------------------------------------------------------------
import cv2, time, numpy as np, json, os, sys, pyautogui, platform
import HandTrackingModule as htm

# ──────────────────────────── constants ─────────────────────────────────────
DEFAULT_CAM_W, DEFAULT_CAM_H = 1280, 720
LAST_CONFIG_FILE             = "last_config.json"
GESTURE_TIMEOUT              = 5        # s
EDGE_HIT_BOX                 = 0.02     # relative hit‑margin for borders

def open_obs_camera(obs_path_linux="/dev/video2",
                    probable_index_windows=1,
                    try_indices=range(2),
                    retry_seconds=0):
    """
    Return an opened cv2.VideoCapture linked to OBS Virtual Camera.
    If nothing is available, release every handle, print a helpful
    message, and sys.exit(1).

    retry_seconds > 0  →  keep polling that many seconds before giving up.
    """
    system = platform.system()

    def bail(msg):
        print(f"❌ {msg}\n"
              "   👉 Launch OBS and press 'Start Virtual Camera', then re‑run.")
        sys.exit(1)

    # -------------- Linux / macOS -----------------------------------------
    if system != "Windows":
        t0 = time.time()
        while True:
            cap = cv2.VideoCapture(obs_path_linux)          # CAP_V4L2 implicit
            if cap.isOpened():
                ok, frame = cap.read()
                if ok and frame is not None and frame.size:   # ✅ real pixels arriving
                    return cap
                cap.release()          # opened but no stream → try again
            else:
                cap.release()          # couldn’t even open fd (rare)

            if time.time() - t0 >= retry_seconds:
                bail(f"Could not get a valid frame from {obs_path_linux}")
            time.sleep(0.5)

    # -------------- Windows -----------------------------------------------
    t0 = time.time()
    while True:
        cap = cv2.VideoCapture(probable_index_windows, cv2.CAP_DSHOW)
        if cap.isOpened():
            return cap
        cap.release()

        # brute‑force other indices, if configured
        for i in try_indices:
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap.isOpened():
                print(f"⚠️  Fallback: opened camera index {i}. "
                      "If this is not the OBS Virtual Camera, stop and choose the correct index.")
                return cap
            cap.release()

        if time.time() - t0 >= retry_seconds:
            bail("No DirectShow device that looks like OBS Virtual Camera was found")
        time.sleep(0.5)


# ────────────────────────── load / save helpers ─────────────────────────────
def load_config(path: str | None):
    """Return (dict | None) with keys center_rect / left_rect / right_rect."""
    cfg = None
    candidate = path if path and os.path.isfile(path) else LAST_CONFIG_FILE
    if os.path.isfile(candidate):
        with open(candidate) as f:
            cfg = json.load(f)

        # ── migrate legacy circle → rect format ───────────────────────────
        if "center_rect" not in cfg and {"center", "radius"}.issubset(cfg):
            cx, cy = cfg["center"]
            r      = cfg["radius"]
            # create a square ROI: top‑left at (cx‑r, cy‑r), side = 2r
            cfg["center_rect"] = [cx - r, cy - r, 2 * r, 2 * r]
            print("ℹ️  Migrated old circle config → rectangle")

    return cfg

def get_layout_dict():
    return {
        "center_rect": center_rect,
        "left_rect":   left_rect,
        "right_rect":  right_rect,
    }

def save_layout(path: str, overwrite=False):
    if not path.endswith(".json"):
        path += ".json"

    if not overwrite and os.path.exists(path):
        stem, ext = os.path.splitext(path)
        n = 1
        while os.path.exists(f"{stem}_{n}{ext}"):
            n += 1
        path = f"{stem}_{n}{ext}"

    with open(path, "w") as f:
        json.dump(get_layout_dict(), f, indent=2)
    with open(LAST_CONFIG_FILE, "w") as f:
        json.dump(get_layout_dict(), f, indent=2)
    print("💾 Layout saved →", path)
    return path

# ────────────────────────── geometry helpers ────────────────────────────────
def abs_pt(rxy, w, h):   return int(rxy[0]*w), int(rxy[1]*h)
def abs_size(rwh, w, h): return int(rwh[0]*w), int(rwh[1]*h)
def inside_rect(x, y, rect):
    rx, ry, rw, rh = rect
    return rx <= x <= rx+rw and ry <= y <= ry+rh
def border_hit(x, y, rect, m):
    rx, ry, rw, rh = rect
    on_l = abs(x-rx)      < m and ry-m <= y <= ry+rh+m
    on_r = abs(x-(rx+rw)) < m and ry-m <= y <= ry+rh+m
    on_t = abs(y-ry)      < m and rx-m <= x <= rx+rw+m
    on_b = abs(y-(ry+rh)) < m and rx-m <= x <= rx+rw+m
    return on_l or on_r or on_t or on_b

# ───────────────────────── camera & initial cfg ─────────────────────────────
config_path   = sys.argv[1] if len(sys.argv) > 1 else None
cfg           = load_config(config_path)
current_path  = config_path or LAST_CONFIG_FILE

# Open OBS Virtual Camera
cap = open_obs_camera(retry_seconds=1)

if cfg:
    wCam = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))  or DEFAULT_CAM_W
    hCam = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or DEFAULT_CAM_H
else:
    cap.set(3, DEFAULT_CAM_W); cap.set(4, DEFAULT_CAM_H)
    wCam, hCam = DEFAULT_CAM_W, DEFAULT_CAM_H

# default or loaded geometry (all relative)
if cfg:
    center_rect = tuple(cfg["center_rect"])
    left_rect   = tuple(cfg["left_rect"])
    right_rect  = tuple(cfg["right_rect"])
else:
    center_rect = (0.44, 0.40, 0.12, 0.20)        # x, y, w, h
    left_rect   = (0.10, 0.40, 150/wCam, 150/hCam)
    right_rect  = (0.75, 0.40, 150/wCam, 150/hCam)

# ───────────────────────── runtime state ────────────────────────────────────
detector        = htm.handDetector(maxHands=1, detectionCon=0.8, trackCon=0.7)
index_in_center = False;  start_time = 0

config_mode  = False   # 'c' toggles on, 'p' toggles off
resize_mode  = False   # 'r' toggles inside config_mode
selected_shape = None
mouse_start, initial_geom = None, None

# ─────────────────────── mouse callback (config mode) ───────────────────────
def on_mouse(event, mx, my, flags, _):
    global selected_shape, mouse_start, initial_geom
    global center_rect, left_rect, right_rect

    if not config_mode:
        return

    rx, ry = mx / wCam, my / hCam   # 0‑1 relative

    if event == cv2.EVENT_LBUTTONDOWN:
        mouse_start  = (rx, ry)
        initial_geom = (center_rect, left_rect, right_rect)

        if resize_mode:
            if border_hit(rx, ry, center_rect, EDGE_HIT_BOX):
                selected_shape = "center_r"
            elif border_hit(rx, ry, left_rect, EDGE_HIT_BOX):
                selected_shape = "left_r"
            elif border_hit(rx, ry, right_rect, EDGE_HIT_BOX):
                selected_shape = "right_r"
        else:
            if inside_rect(rx, ry, center_rect):
                selected_shape = "center"
            elif inside_rect(rx, ry, left_rect):
                selected_shape = "left"
            elif inside_rect(rx, ry, right_rect):
                selected_shape = "right"

    elif event == cv2.EVENT_MOUSEMOVE and selected_shape:
        dx, dy = rx - mouse_start[0], ry - mouse_start[1]
        c0, l0, r0 = initial_geom

        # -------- move -----------------------------------------------------
        if selected_shape == "center":
            cx, cy, cw, ch = c0
            center_rect = (np.clip(cx+dx, 0, 1-cw),
                           np.clip(cy+dy, 0, 1-ch), cw, ch)
        elif selected_shape == "left":
            lx, ly, lw, lh = l0
            left_rect = (np.clip(lx+dx, 0, 1-lw),
                         np.clip(ly+dy, 0, 1-lh), lw, lh)
        elif selected_shape == "right":
            rx0, ry0, rw, rh = r0
            right_rect = (np.clip(rx0+dx, 0, 1-rw),
                          np.clip(ry0+dy, 0, 1-rh), rw, rh)

        # -------- resize ---------------------------------------------------
        elif selected_shape == "center_r":
            cx, cy, cw, ch = c0
            center_rect = (cx, cy,
                           np.clip(cw + dx, 0.05, 0.5),
                           np.clip(ch + dy, 0.05, 0.5))
        elif selected_shape == "left_r":
            lx, ly, lw, lh = l0
            left_rect = (lx, ly,
                         np.clip(lw + dx, 0.05, 0.5),
                         np.clip(lh + dy, 0.05, 0.5))
        elif selected_shape == "right_r":
            rx0, ry0, rw, rh = r0
            right_rect = (rx0, ry0,
                          np.clip(rw + dx, 0.05, 0.5),
                          np.clip(rh + dy, 0.05, 0.5))

    elif event == cv2.EVENT_LBUTTONUP:
        selected_shape = mouse_start = initial_geom = None

cv2.namedWindow("Hand Gesture Control", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Hand Gesture Control", wCam, hCam)
cv2.setMouseCallback("Hand Gesture Control", on_mouse)

# ───────────────────────────── main loop ────────────────────────────────────
while True:
    ok, img = cap.read()
    if not ok:
        print("❌ No se pudo leer el frame de la cámara")
        break
    img = cv2.flip(img, 1)            # mirror
    h, w = img.shape[:2]
    


    c_abs = (*abs_pt(center_rect, w, h), *abs_size(center_rect[2:], w, h))
    l_abs = (*abs_pt(left_rect,   w, h), *abs_size(left_rect[2:],   w, h))
    r_abs = (*abs_pt(right_rect,  w, h), *abs_size(right_rect[2:],  w, h))

    if not config_mode:   # -------- tracking ------------------------------
        img = detector.findHands(img)
        lm  = detector.findPosition(img, draw=True)

        for rect, color in [(c_abs, (255,255,0)), (l_abs, (0,255,0)), (r_abs, (0,0,255))]:
            cv2.rectangle(img, rect[:2], (rect[0]+rect[2], rect[1]+rect[3]), color, 2)

        if lm:
            # ===== NUEVO BLOQUE: evaluar dedos =====
            index_up  = lm[8][2]  < lm[6][2]
            middle_up = lm[12][2] < lm[10][2]
            ring_up   = lm[16][2] < lm[14][2]
            pinky_up  = lm[20][2] < lm[18][2]

            only_index_up = index_up and not (middle_up or ring_up or pinky_up)

            x, y = lm[8][1:3]          # punta del índice

            # ---------- lógica central -------------
            if only_index_up and inside_rect(x, y, c_abs) and not index_in_center:
                index_in_center, start_time = True, time.time()
                print("🟡 índice en CENTRO — gesto armado")

            if index_in_center:
                if not only_index_up:
                    # se cerró la mano o se levantó otro dedo → cancelar
                    print("🚫 gesto cancelado (mano abierta o varios dedos)")
                    index_in_center = False

                elif time.time() - start_time > GESTURE_TIMEOUT:
                    print("⌛ timeout"); index_in_center = False

                elif inside_rect(x, y, l_abs):
                    pyautogui.press("left");  print("⬅️  SLIDE LEFT");  index_in_center = False

                elif inside_rect(x, y, r_abs):
                    pyautogui.press("right"); print("➡️  SLIDE RIGHT"); index_in_center = False

    else:                 # -------- config overlay ------------------------
        for rect, color in [(c_abs, (255,255,0)), (l_abs, (0,255,0)), (r_abs, (0,0,255))]:
            cv2.rectangle(img, rect[:2], (rect[0]+rect[2], rect[1]+rect[3]), color, 2)

        mode = "RESIZE" if resize_mode else "MOVE"
        txt  = ("CONFIG ("+mode+") "
                + ("drag borders | c: pan | " if resize_mode
                   else "drag to pan | r: resize | ")
                + "p: save as | o: overwrite | q: quit")
        cv2.putText(img, txt, (20, 40), cv2.FONT_HERSHEY_SIMPLEX,
                    1.2, (0,0,0), 3, cv2.LINE_AA)

    cv2.imshow("Hand Gesture Control", img)

    k = cv2.waitKey(1) & 0xFF
    if   k == ord('q'):
        break
    elif k == ord('c') and not config_mode:
        config_mode, resize_mode = True, False
        print("🛠  CONFIG‑MOVE mode – drag to pan, 'r' to resize, 'p'/'o' to save")
    elif k == ord('c') and config_mode and resize_mode:
        resize_mode = False; print("🛠  Back to CONFIG‑MOVE mode – drag to pan")
    elif k == ord('r') and config_mode and not resize_mode:
        resize_mode = True;  print("✏️  CONFIG‑RESIZE mode – drag borders, 'c' to pan")
    elif k == ord('p') and config_mode:
        name = input("Name this layout: ").strip() or "layout"
        current_path = save_layout(name, overwrite=False)
        config_mode = resize_mode = False
        print("✅ Saved as", current_path, "– tracking resumed")
    elif k == ord('o') and config_mode:
        current_path = save_layout(current_path, overwrite=True)
        config_mode = resize_mode = False
        print("💾 Layout overwritten – tracking resumed")

cap.release(); cv2.destroyAllWindows()
