"""현재 경로 첫 점으로 클릭1초와 짧은 스틱 입력의 실제 변위를 비교."""
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
 import hashlib,inspect
 print('STARTUP',json.dumps({'prompt_handler':hasattr(gamewin,'dismiss_controller_prompt'),'pad_has_handler':'dismiss_controller_prompt' in inspect.getsource(Pad.__init__),'gamewin_hash':hashlib.sha256(Path(gamewin.__file__).read_bytes()).hexdigest()[:10]}),flush=True)
 pad=None
 bot=None
 try:
  bot=Bot(ue,pad)
  bot.clicker=screen.Clicker(ue,ue.p.pid)
  if not bot.r.player:raise RuntimeError('조작 캐릭터 없음')
  if not (HERE/'calib.json').exists():raise RuntimeError('기존 보정 없음: 시험 중단')
  bot.calibrate()
  actor=next(o for o in ue.find_instances('LovikaRecastNavMesh') if not ue.objname(o).startswith('Default__'))
  mesh=navmesh.read_navmesh(ue,actor)
  me=bot.r.loc(bot.r.player)
  poly=mesh.find(me)
  if poly is None:raise RuntimeError('현재 위치의 보행 지도 없음')
  candidates=[mesh.center[poly]]+[mesh.center[k] for k,*_ in mesh.adj[poly] if (poly,k) not in mesh.jump_edges]
  path=None
  for point in sorted(candidates,key=lambda p:abs(math.dist(p[:2],me[:2])-300)):
   distance=math.dist(point[:2],me[:2])
   if not 150 < distance < 600 or abs(point[2]-me[2])>200:continue
   route=mesh.path(me,point)
   if not route or any((a,b) in mesh.jump_pairs for a,b in zip(route,route[1:])):continue
   if sum(math.dist(a[:2],b[:2]) for a,b in zip([me]+route,route))>900:continue
   path=route
   break
  if not path:raise RuntimeError('입력을 시험할 짧은 보행 경로 없음')
  target=next((p for p in path if math.dist(p[:2],me[:2])>120),None)
  if target is None:raise RuntimeError('시험할 경로 점 없음')
  assert 120 < math.dist(target[:2],me[:2]) < 900
  assert all((a,b) not in mesh.jump_pairs for a,b in zip(path,path[1:]))
  if not gamewin.focus_game(ue.p.pid):raise RuntimeError('게임 포커스 실패')
  time.sleep(0.5)
  print('TARGET',json.dumps({'me':me,'target':target,'route':path[:6]}),flush=True)
  for mode in ('click','stick'):
   if mode=='stick':
    pad=Pad()
    bot.pad=pad
    time.sleep(2.5)
   p0=bot.r.loc(bot.r.player)
   if mode=='stick' and math.dist(target[:2],p0[:2])<120:
    print(json.dumps({'input':mode,'skipped':'target already reached'}),flush=True)
    continue
   if mode=='click':accepted=bot.clicker.click_world(target,p0)
   else:
    pad.stick(*bot.to_stick(target[0]-p0[0],target[1]-p0[1]));accepted=True
   time.sleep(1 if mode=='click' else 0.15)
   if pad:pad.reset()
   time.sleep(0.15)
   p1=bot.r.loc(bot.r.player)
   print(json.dumps({'input':mode,'accepted':accepted,'start':p0,'end':p1,'delta':math.dist(p0[:2],p1[:2]),'goal_before':math.dist(p0[:2],target[:2]),'goal_after':math.dist(p1[:2],target[:2])}),flush=True)
 finally:
  if bot:bot.stop=True
  if pad:pad.reset()
  if bot and bot.clicker and screen.u32.GetForegroundWindow()==bot.clicker.hwnd:
   x,y,w,h=screen.client_rect(bot.clicker.hwnd)
   img=ImageGrab.grab(bbox=(x,y,x+w,y+h))
   img.resize((960,540)).crop((350,215,610,347)).save(HERE/'controller_raw.png')
   img.thumbnail((960,540))
   img.save(HERE/'movement_current.jpg')
   with zipfile.ZipFile(HERE/'snaps_movement_check.zip','w',zipfile.ZIP_DEFLATED) as z:
    z.write(HERE/'movement_current.jpg','movement_current.jpg')
    z.write(HERE/'controller_raw.png','controller_raw.png')

if __name__=='__main__':
 try:main()
 except Exception:traceback.print_exc()
