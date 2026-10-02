"""Explicit development-time downloads. Never imported by the app."""
from pathlib import Path
import hashlib
import json
import urllib.request

ROOT = Path(__file__).resolve().parent.parent / "models"
ASSETS = {
    "pose_landmarker_lite.task": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
    "pose_landmarker_full.task": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task",
    "face_landmarker.task": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    "hand_landmarker.task": "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
}


def main():
    ROOT.mkdir(exist_ok=True)
    manifest = {}
    for name, url in ASSETS.items():
        target = ROOT / name
        if not target.exists():
            temporary = target.with_suffix(".part")
            with urllib.request.urlopen(url, timeout=90) as response:
                with temporary.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
            temporary.replace(target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        manifest[name] = {"sha256": digest, "bytes": target.stat().st_size, "source": url}
        print(f"{name}: {target.stat().st_size:,} bytes, SHA256 {digest}")
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
