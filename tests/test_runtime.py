import os
from pathlib import Path
import unittest
from unittest.mock import patch

from posture_track.runtime import default_data_dir, resource_root


class RuntimePathsTests(unittest.TestCase):
    def test_installed_data_survives_bundle_replacement(self):
        with patch('sys.frozen', True, create=True), patch('sys._MEIPASS', 'C:/replacement/_internal', create=True), patch.dict(os.environ, {'LOCALAPPDATA': 'C:/Users/test/AppData/Local'}):
            self.assertEqual(resource_root(), Path('C:/replacement/_internal'))
            self.assertEqual(default_data_dir(), Path('C:/Users/test/AppData/Local/PostureTrack/data'))
            self.assertEqual(default_data_dir(True), Path('C:/Users/test/AppData/Local/PostureTrack/demo'))

    def test_source_run_retains_existing_records(self):
        with patch('sys.frozen', False, create=True):
            self.assertEqual(default_data_dir(), resource_root() / '.data/local')
            self.assertEqual(default_data_dir(True), resource_root() / '.data/demo')

    @unittest.skipUnless(os.name == 'nt', 'Windows mutex test')
    def test_second_process_cannot_acquire_same_instance(self):
        import subprocess
        import sys
        code = 'from posture_track.runtime import acquire_instance; import sys; sys.exit(0 if acquire_instance() else 3)'
        holder = subprocess.Popen([sys.executable, '-c', 'from posture_track.runtime import acquire_instance; import time; print(acquire_instance(), flush=True); time.sleep(20)'], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), 'True')
            self.assertEqual(subprocess.run([sys.executable, '-c', code]).returncode, 3)
        finally:
            holder.terminate()
            holder.wait(timeout=5)
            holder.stdout.close()
        self.assertEqual(subprocess.run([sys.executable, '-c', code]).returncode, 0)
