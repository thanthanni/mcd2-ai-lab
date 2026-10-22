"""숲 역 길찾기 진단. 게임 조작·패드 생성 없이 주변 내비 메시와 경로만 저장."""
import base64
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
    dt = ue.q(ue.q(actor + navmesh.ACTOR_IMPL) + 8)
    tiles_ptr = ue.q(dt + navmesh.DT_TILES)
    max_tiles = min(ue.i32(dt + navmesh.DT_MAXTILES), 20000)
    tile_raw = ue.read(tiles_ptr, max_tiles * navmesh.TILE_STRIDE)
    runtime = []
    for ti in range(max_tiles):
        tr = tile_raw[ti*navmesh.TILE_STRIDE:(ti+1)*navmesh.TILE_STRIDE]
        h = struct.unpack_from('<Q',tr,8)[0]
        size = struct.unpack_from('<i',tr,0x58)[0]
        if not navmesh.ptr_ok(h) or not 0 < size < 4000000:
            continue
        item = {'index':ti, 'salt':struct.unpack_from('<I',tr)[0]}
        try:
            maxlinks = struct.unpack('<H',ue.read(h+16,2))[0]
            lp = struct.unpack_from('<Q',tr,0x20)[0]
            item['links'] = base64.b64encode(ue.read(lp,maxlinks*16)).decode()
            dp = struct.unpack_from('<Q',tr,0x90)[0]
            nc, count = struct.unpack_from('<II',tr,0x98)
            item['chunks'],item['count'] = nc,count
            if 0 < nc < 256 and 0 < count <= nc*128:
                cp = struct.unpack('<'+'Q'*nc,ue.read(dp,nc*8))
                dyn = b''.join(ue.read(p,min(128,max(0,count-k*128))*16) for k,p in enumerate(cp) if count>k*128)
                item['dynamic'] = base64.b64encode(dyn).decode()
        except Exception as e:
            item['error']=str(e)
        runtime.append(item)
    mesh = navmesh.NavMesh(blobs)
    n = nav.Nav(r, None, None, None)
    n.goal, n.mesh = goal, mesh
    record = {'me':me, 'goal':goal, 'start_poly':mesh.find(me), 'goal_poly':mesh.find(goal),
              'mesh_path':mesh.path(me, goal), 'planned_path':n.plan(me), 'stats':n.stats,
              'tiles':len(blobs), 'polygons':len(mesh), 'stations':stations,
              'runtime':runtime, 'bits':struct.unpack('<3i',ue.read(dt+0xf0,12)),
              'reachable_stations':{name:path for name,pos in stations.items() if (path:=mesh.path(me,pos))}}
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
