from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all('mediapipe')
a = Analysis(['installer/launcher.py'], pathex=['.'],
    binaries=binaries,
    datas=datas + [('assets', 'assets'), ('models/*.task', 'models'), ('models/manifest.json', 'models')],
    hiddenimports=hiddenimports + ['pystray._win32'],
    excludes=['pytest', 'IPython'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='PostureTrack',
    console=False, icon='assets/posture-track.ico')
coll = COLLECT(exe, a.binaries, a.datas, name='PostureTrack')
