"""연결 해제 창을 재현하고 다음 패드 연결·정상 종료의 복구를 실제 화면으로 검사."""
import sys,time,traceback,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
first=second=None
try:
 from state_probe import find_ohs_app
 sys.path.insert(0,find_ohs_app())
 import gamewin,screen
 from rule_bot import Pad
 from PIL import Image,ImageGrab
 gamewin.prepare()
 hwnd=screen.game_hwnd(gamewin._game_pid())
 def frame():
  if not hwnd or screen.u32.GetForegroundWindow()!=hwnd:raise RuntimeError('게임 포커스 없음')
  x,y,w,h=screen.client_rect(hwnd)
  if w<=0 or h<=0:raise RuntimeError('게임 창 크기 없음')
  return ImageGrab.grab(bbox=(x,y,x+w,y+h))
 with Image.open(HERE/'controller_disconnected.png') as template:
  first=Pad()
  time.sleep(2.5)
  first.tap('LEFT_THUMB')  # 확인된 안내 경로 버튼, 이동·공격 없음.
  time.sleep(0.3)
  device=first.p
  first.p=None
  device.reset();device.update()
  del device  # 종료 처리를 생략한 연결 해제를 재현.
  deadline=time.time()+4
  while time.time()<deadline:
   if gamewin.controller_prompt_matches(frame(),template):break
   time.sleep(0.2)
  assert gamewin.controller_prompt_matches(frame(),template),'연결 해제 창이 재현되지 않음'
  print('CHECK disconnected prompt reproduced',flush=True)
  second=Pad()
  time.sleep(1)
  assert not gamewin.controller_prompt_matches(frame(),template),'재연결 후 창이 남음'
  print('CHECK startup recovered',flush=True)
  second.close()
  time.sleep(1)
  assert not gamewin.controller_prompt_matches(frame(),template),'정상 종료 후 창이 남음'
  print('CHECK shutdown recovered',flush=True)
except Exception:traceback.print_exc()
finally:
 for pad in (first,second):
  if pad is not None:pad.close()
 try:
  gamewin.dismiss_controller_prompt(None)
  im=frame();im.thumbnail((1280,720));im.save(HERE/'controller_cycle.png')
  with zipfile.ZipFile(HERE/'snaps_controller_cycle.zip','w',zipfile.ZIP_DEFLATED) as z:z.write(HERE/'controller_cycle.png','controller_cycle.png')
 except Exception:traceback.print_exc()
