import json
import tempfile
import unittest
from pathlib import Path

from posture_track.config import Settings


class SensitivitySettingsTests(unittest.TestCase):
    def test_default_migration_and_saved_choice(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'
            self.assertEqual(Settings.load(path).posture_sensitivity,'standard')
            path.write_text(json.dumps({'performance':'High'}),encoding='utf-8')
            self.assertEqual(Settings.load(path).posture_sensitivity,'standard')
            Settings(posture_sensitivity='sensitive').save(path)
            self.assertEqual(Settings.load(path).posture_sensitivity,'sensitive')
            path.write_text(json.dumps({'posture_sensitivity':['invalid']}),encoding='utf-8')
            self.assertEqual(Settings.load(path).posture_sensitivity,'standard')
