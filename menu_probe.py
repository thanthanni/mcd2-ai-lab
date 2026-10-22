"""빠른 이동 메뉴 오작동 조사: 입력 없이 게임 창만 촬영한다."""
import os
import sys
import time
import traceback
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    from state_probe import find_ohs_app
    app = find_ohs_app()
    if not app:
        raise RuntimeError('Offline Hero Sync 폴더 없음')
    sys.path.insert(0, app)
    import winproc
    import screen
    from PIL import ImageGrab
    p = winproc.Process()
    import gamewin
    gamewin.focus_game(p.pid)
    hwnd = screen.game_hwnd(p.pid)
    if not hwnd or screen.u32.GetForegroundWindow() != hwnd:
        raise RuntimeError('게임 창이 맨 앞이 아니라 촬영하지 않음')
    x, y, w, h = screen.client_rect(hwnd)
    if w <= 0 or h <= 0:
        raise RuntimeError('게임 창 크기 없음')
    image = ImageGrab.grab(bbox=(x, y, x+w, y+h))
    name = time.strftime('menu_probe_%m%d_%H%M%S.png')
    image.thumbnail((1280, 720))
    image.save(os.path.join(HERE, name))
    with zipfile.ZipFile(os.path.join(HERE, 'snaps_menu_probe.zip'), 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(HERE, name), name)
    print(f'게임 창 {w}x{h}, 입력 없이 현재 메뉴 촬영 완료', flush=True)
except Exception:
    traceback.print_exc()
