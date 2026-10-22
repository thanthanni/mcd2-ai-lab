"""숲 역 길찾기 진단. 게임 조작·패드 생성 없이 주변 내비 메시와 경로만 저장."""
import json
import os
import struct
import sys
import time
import traceback
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)
try:
    from state_probe import find_ohs_app
    app = find_ohs_app()
    if not app:
        raise RuntimeError('Offline Hero Sync 폴더 없음')
    sys.path.insert(0, app)
    import winproc
    import uemem
    import navmesh
    import nav
    import gamewin
    import screen
    from state_reader import Reader
    from PIL import ImageGrab
    ue = uemem.UE(winproc.Process(), rescan=True)
    r = Reader(ue)
    r.scan()
    me = r.loc(r.player)
    stations = {}
    for o in ue.find_instances('BP_MinecartStation_C'):
        try:
            props = ue.oprops(o)
            name = ue.fname(o + props['NameOnMap'].offset)
            rc = ue.q(o + props['RootComponent'].offset)
            stations[name] = struct.unpack('<ddd', ue.read(rc + ue.field(rc, 'RelativeLocation').offset, 24))
        except Exception:
            continue
    goal = stations['ForestA1-Outpost']
    actor = next(o for o in ue.find_instances('LovikaRecastNavMesh') if not ue.objname(o).startswith('Default__'))
    blobs = navmesh.read_tiles(ue, actor)
    mesh = navmesh.NavMesh(blobs)
    n = nav.Nav(r, None, None, None)
    n.goal, n.mesh = goal, mesh
    record = {'me':me, 'goal':goal, 'start_poly':mesh.find(me), 'goal_poly':mesh.find(goal),
              'mesh_path':mesh.path(me, goal), 'planned_path':n.plan(me), 'stats':n.stats,
              'tiles':len(blobs), 'polygons':len(mesh)}
    print(json.dumps(record, ensure_ascii=False), flush=True)
    with zipfile.ZipFile(HERE/'snaps_forest_probe.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('forest_probe.json', json.dumps(record,ensure_ascii=False))
        for i, data in enumerate(blobs):
            z.writestr(f'tiles/{i}.bin', data)
        if gamewin.focus_game(ue.p.pid):
            hwnd = screen.game_hwnd(ue.p.pid)
            if hwnd and screen.u32.GetForegroundWindow() == hwnd:
                x,y,w,h = screen.client_rect(hwnd)
                if w>0 and h>0:
                    img = ImageGrab.grab(bbox=(x,y,x+w,y+h))
                    img.thumbnail((1280,720))
                    img.save(HERE/'forest_current.png')
                    z.write(HERE/'forest_current.png','forest_current.png')
    print('진단 묶음 저장 완료', flush=True)
except Exception:
    traceback.print_exc()
