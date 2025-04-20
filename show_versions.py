# save as show_versions.py
import importlib.metadata as md        # Python ≥3.8
import pkg_resources                   # fallback for very old Pythons

pkgs = {
    "opencv-python": "cv2",
    "numpy":          "numpy",
    "PyAutoGUI":      "pyautogui",
    "mediapipe":      "mediapipe",
}

for dist_name, import_name in pkgs.items():
    try:
        # try new API first
        ver = md.version(dist_name)
    except Exception:
        # fallback: setuptools / pkg_resources
        ver = pkg_resources.get_distribution(dist_name).version
    print(f"{dist_name}=={ver}")
