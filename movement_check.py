"""현재 경로 첫 점으로 클릭과 스틱을 각각 1초 시험하고 실제 변위를 비교."""
import json,math,sys,time,traceback,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent

def main():
 from state_probe import find_ohs_app
 sys.path.insert(0,find_ohs_app())
 import winproc,uemem,gamewin,screen,navmesh
 from rule_bot import Bot,Pad
 from PIL import ImageGrab
 gamewin.prepare()
 ue=uemem.UE(winproc.Process(),rescan=True)
 pad=Pad()
 try:
  bot=Bot(ue,pad)
  bot.clicker=screen.Clicker(ue,ue.p.pid)
  if not bot.r.player:raise RuntimeError('조작 캐릭터 없음')
  if not (HERE/'calib.json').exists():raise RuntimeError('기존 보정 없음: 시험 중단')
  bot.calibrate()
  actor=next(o for o in ue.find_instances('LovikaRecastNavMesh') if not ue.objname(o).startswith('Default__'))
  mesh=navmesh.read_navmesh(ue,actor)
  me=bot.r.loc(bot.r.player)
  stations=[]
  for o in ue.find_instances('BP_MinecartStation_C'):
   try:
    if ue.fname(o+ue.field(o,'NameOnMap').offset)=='ForestA1-Outpost':stations.append(bot.r.loc(o))
   except Exception:continue
  if not stations:raise RuntimeError('숲 역 없음')
  path=mesh.path(me,stations[0])
  if not path:raise RuntimeError('연결 경로 없음')
  target=next((p for p in path if math.dist(p[:2],me[:2])>120),None)
  if target is None:raise RuntimeError('시험할 경로 점 없음')
  if not gamewin.focus_game(ue.p.pid):raise RuntimeError('게임 포커스 실패')
  time.sleep(0.5)
  print('TARGET',json.dumps({'me':me,'target':target,'route':path[:6]}),flush=True)
  for mode in ('click','stick'):
   p0=bot.r.loc(bot.r.player)
   if mode=='click':accepted=bot.clicker.click_world(target,p0)
   else:
    pad.stick(*bot.to_stick(target[0]-p0[0],target[1]-p0[1]));accepted=True
   time.sleep(1)
   pad.reset()
   time.sleep(0.15)
   p1=bot.r.loc(bot.r.player)
   print(json.dumps({'input':mode,'accepted':accepted,'start':p0,'end':p1,'delta':math.dist(p0[:2],p1[:2]),'goal_before':math.dist(p0[:2],target[:2]),'goal_after':math.dist(p1[:2],target[:2])}),flush=True)
  if screen.u32.GetForegroundWindow()==bot.clicker.hwnd:
   x,y,w,h=screen.client_rect(bot.clicker.hwnd)
   img=ImageGrab.grab(bbox=(x,y,x+w,y+h));img.thumbnail((960,540))
   img.save(HERE/'movement_current.jpg')
   with zipfile.ZipFile(HERE/'snaps_movement_check.zip','w',zipfile.ZIP_DEFLATED) as z:z.write(HERE/'movement_current.jpg','movement_current.jpg')
 finally:pad.reset()

if __name__=='__main__':
 try:main()
 except Exception:traceback.print_exc()
