"""No camera: initialize all local models and infer a blank image offline."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from posture_track.privacy import enforce_local_only

enforce_local_only()
import numpy as np
from posture_track.config import ROOT
from posture_track.vision import LocalModels

with_output = LocalModels(ROOT / "models")
try:
    with_output.ensure(hands=True)
    result = with_output.detect(np.zeros((480, 640, 3), dtype=np.uint8), 1.0)
    assert result.view == "unknown"
    assert not result.pose and not result.face and not result.hands
    with_output.ensure(hands=False)
    assert "hands" not in with_output.models
    print("PASS: local Pose/Face/Hand initialized; blank image remains unknown; disabled hand model closed")
finally:
    with_output.close()
