"""패드를 생성하지 않고 확인한 연결 해제 창만 닫고 게임 화면을 기록."""
import sys,traceback,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
try:
 from state_probe import find_ohs_app
 sys.path.insert(0,find_ohs_app())
 import gamewin,screen
 from PIL import ImageGrab
 if not gamewin.focus_game():raise RuntimeError('게임 포커스 실패')
 try:gamewin.dismiss_controller_prompt(None)
 finally:
  pid=gamewin._game_pid()
  hwnd=screen.game_hwnd(pid) if pid else None
  if hwnd and screen.u32.GetForegroundWindow()==hwnd:
   x,y,w,h=screen.client_rect(hwnd)
   if w>0 and h>0:
    im=ImageGrab.grab(bbox=(x,y,x+w,y+h));im.thumbnail((1280,720));im.save(HERE/'controller_reset.png')
    with zipfile.ZipFile(HERE/'snaps_controller_reset.zip','w',zipfile.ZIP_DEFLATED) as z:z.write(HERE/'controller_reset.png','controller_reset.png')
except Exception:traceback.print_exc()
