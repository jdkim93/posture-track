import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from posture_track.domain import Baseline,Profiles,Observation
from posture_track.monitor_setup import MonitorLayout
from posture_track.displays import popup_positions
from posture_track.worker import Worker
from posture_track.config import Settings


class MonitorTests(unittest.TestCase):
    def test_same_direction_screens_are_independent_and_nearest_is_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            profiles=Profiles(Path(directory)/'profiles.json')
            profiles.save(Baseline('front',{'view_yaw':0,'view_pitch':0},{},camera_signature='cam'))
            for identity,yaw in (('left',-30),('further-left',-50)):
                profiles.save(Baseline('oblique_left',{'view_yaw':yaw,'view_pitch':0},{},camera_signature='cam',profile_id=identity,label=identity))
            profiles=Profiles(profiles.path)
            self.assertEqual(set(profiles.items),{'front','left','further-left'})
            for yaw,expected in ((-31,'left'),(-49,'further-left')):
                selected=profiles.select(Observation(0,'oblique_left',{'view_yaw':yaw,'view_pitch':0}),'cam')
                self.assertEqual(selected.profile_id,expected)
            self.assertEqual(profiles.select(Observation(0,'oblique_left',{'view_yaw':-90}),'cam').profile_id,'further-left')
            self.assertIsNone(profiles.select(Observation(0,'oblique_left',{'view_yaw':-30}),'another-camera'))

    def test_vertical_screens_and_boundary_angles(self):
        with tempfile.TemporaryDirectory() as directory:
            profiles=Profiles(Path(directory)/'profiles.json')
            for identity,pitch in (('upper',-15),('lower',15)):
                profiles.save(Baseline('front',{'view_yaw':23,'view_pitch':pitch},{},camera_signature='cam',profile_id=identity))
            observation=Observation(0,'oblique_right',{'view_yaw':26,'view_pitch':14})
            self.assertEqual(profiles.select(observation,'cam').profile_id,'lower')
            observation.metrics['view_pitch']=-14
            self.assertEqual(profiles.select(observation,'cam').profile_id,'upper')
            observation.view='side_right'
            self.assertEqual(profiles.select(observation,'cam').profile_id,'upper')

    def test_layout_preserves_arbitrary_positions_and_existing_reference_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'layout.json'
            layout=MonitorLayout(path,[(0,0,1920,1080),(-1920,-800,0,280)],
                                 [{'id':'front','name':'front'}])
            self.assertEqual(layout.nodes[0]['id'],'front')
            layout.nodes[0].update(x=.25,y=.75,kind='laptop',name='노트북')
            layout.nodes[1].update(x=.18,y=.22,name='더 왼쪽 화면')
            layout.save()
            restored=MonitorLayout(path,[])
            self.assertEqual(restored.nodes,layout.nodes)
            added=restored.add()
            self.assertNotEqual(added['id'],'front')

    def test_preparation_uses_direction_after_countdown(self):
        worker=Worker(Path('.'),Settings(),demo=True)
        worker.recorder=Mock()
        target={'profile_id':'secondary','label':'보조 화면'}
        worker.registration_request=(4,target)
        worker.advance_registration(3,'front')
        self.assertIsNone(worker.calibration)
        worker.advance_registration(4,'unknown')
        self.assertIsNone(worker.calibration)
        worker.advance_registration(5,'oblique_left')
        self.assertEqual(worker.calibration.view,'oblique_left')
        self.assertEqual(worker.registration_target,target)

    def test_popup_positions_include_left_and_upper_displays(self):
        self.assertEqual(popup_positions([(0,0,1920,1080),(-1920,0,0,1080),(0,-1080,1920,0)],240),
                         [(840,24),(-1080,24),(840,-1056)])

    def test_worker_saves_two_named_references_in_same_direction(self):
        from posture_track.domain import Calibration
        with tempfile.TemporaryDirectory() as directory:
            worker=Worker(Path(directory),Settings(),demo=True)
            worker.recorder=Mock()
            worker.profiles=Profiles(Path(directory)/'profiles.json')
            for identity,yaw in (('left',-35),('further-left',-50)):
                worker.registration_target={'profile_id':identity,'label':identity}
                worker.calibration=Calibration(0,'oblique_left')
                worker.calibration_session=True
                for index in range(21):
                    worker.calibration.add(Observation(3+index*.5,'oblique_left',{'roll':0,'pitch':0,'view_yaw':yaw,'view_pitch':0}))
                worker.complete_calibration()
            restored=Profiles(worker.profiles.path)
            self.assertEqual(set(restored.items),{'left','further-left'})
            self.assertEqual(restored.items['further-left'].label,'further-left')

    def test_delete_removes_only_selected_screen_and_its_saved_posture(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            layout=MonitorLayout(path/'monitor-layout.json',[],[{'id':'one','name':'one'},{'id':'two','name':'two'}])
            layout.save()
            worker=Worker(path,Settings(),demo=True)
            worker.recorder=Mock()
            worker.profiles=Profiles(path/'profiles.json')
            for identity in ('one','two'):
                worker.profiles.save(Baseline('front',{'view_yaw':0},{},camera_signature=worker.signature(),profile_id=identity))
            worker.current_profile=worker.profiles.items['one']
            worker.screen_tracker.current='one'
            worker.registration_request=(100,{'profile_id':'one'})
            worker.submit('monitor_delete',{'profile_id':'one'})
            worker.handle_commands()
            self.assertEqual(set(Profiles(path/'profiles.json').items),{'two'})
            self.assertEqual([node['id'] for node in MonitorLayout(layout.path,[]).nodes],['two'])
            self.assertIsNone(worker.current_profile)
            self.assertIsNone(worker.registration_request)
            self.assertIsNone(worker.screen_tracker.current)
            worker.submit('monitor_delete',{'profile_id':'two'})
            worker.handle_commands()
            self.assertEqual(Profiles(path/'profiles.json').items,{})
            self.assertEqual(MonitorLayout(layout.path,[(0,0,1920,1080)]).nodes,[])

    def test_failed_posture_delete_restores_screen_layout(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            layout=MonitorLayout(path/'monitor-layout.json',[],[{'id':'one','name':'one'}])
            layout.save()
            worker=Worker(path,Settings(),demo=True)
            worker.recorder=Mock()
            worker.profiles=Profiles(path/'profiles.json')
            worker.profiles.save(Baseline('front',{}, {},profile_id='one'))
            worker.submit('monitor_delete',{'profile_id':'one'})
            with patch.object(worker.profiles,'delete',side_effect=OSError('disk full')):
                worker.handle_commands()
            self.assertEqual(set(worker.profiles.items),{'one'})
            self.assertEqual(MonitorLayout(layout.path,[]).nodes,layout.nodes)
            self.assertEqual(worker.events.get_nowait()[0],'monitor_delete_failed')
