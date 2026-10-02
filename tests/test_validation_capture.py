import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from posture_track.config import Settings
from posture_track.validation_capture import save_capture
from posture_track.worker import Worker
from posture_track.domain import Result
from posture_track.validation import Trial


class CaptureTests(unittest.TestCase):
    def test_trial_keeps_deviation_range_for_missed_detection(self):
        trial = Trial("head_bend", "bad", 0, "front", 1)
        for now, value in ((6, 3), (8, 7), (10, 11)):
            trial.observe(now, "front", 1, {"head_bend": Result("good", value, 15)})
        report = trial.report()
        self.assertEqual(report["deviation_summary"], {"min": 3, "median": 7, "max": 11})
        self.assertEqual(report["threshold_median"], 15)
        self.assertEqual(report["agreement"], 0)

    def test_lossless_single_frame_and_matching_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frame = np.arange(60, dtype=np.uint8).reshape(4, 5, 3)
            result = save_capture(root, frame, {"observation": {"timestamp": 12}}, {"target": "head_bend"})
            photo = root / result["image"]
            metadata = json.loads((root / result["measurement"]).read_text(encoding="utf-8"))
            self.assertTrue(np.array_equal(frame, cv2.imread(str(photo))))
            self.assertEqual(metadata["image_sha256"], hashlib.sha256(photo.read_bytes()).hexdigest())
            self.assertEqual(metadata["measurement"]["observation"]["timestamp"], 12)
            self.assertEqual(len(list(photo.parent.iterdir())), 2)

    def test_normal_and_release_workers_cannot_enable_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertFalse(Worker(root, Settings()).capture_trials)
            with self.assertRaises(ValueError):
                Worker(root, Settings(), capture_trials=True)
            with self.assertRaises(ValueError):
                Worker(root, Settings(), demo=True, dev=True, capture_trials=True)


if __name__ == "__main__":
    unittest.main()
