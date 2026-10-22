"""로컬 플레이어 식별 및 봇 중복 실행 조사. 게임 조작 없음."""
import json,sys,time,traceback,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
try:
 from state_probe import find_ohs_app
 sys.path.insert(0,find_ohs_app())
 import winproc,uemem
 from state_reader import Reader
 ue=uemem.UE(winproc.Process(),rescan=True)
 r=Reader(ue)
 for i in range(3):
  r.scan()
  players=[]
  for o in ue.iter_objects():
   try:
    ch=r._chain(ue.cls(o))
    if 'PlayerCharacter' in ch and not ue.objname(o).startswith('Default__'):
     players.append({'id':hex(o),'class':ue.objname(ue.cls(o)),'pos':r.loc(o),'selected':o==r.player})
   except Exception:continue
  controllers=[]
  for pc in ue.find_instances('PlayerController'):
   if ue.objname(pc).startswith('Default__'):continue
   row={'id':hex(pc),'class':ue.objname(ue.cls(pc))}
   for key in ['Pawn','Character','AcknowledgedPawn','Player']:
    try:
     ptr=ue.q(pc+ue.field(pc,key).offset)
     row[key]={'id':hex(ptr),'class':ue.objname(ue.cls(ptr)) if ptr else None}
    except Exception as e:row[key]=str(e)
   controllers.append(row)
  print(json.dumps({'tick':i,'players':players,'controllers':controllers},ensure_ascii=False),flush=True)
  time.sleep(2)
 import navmesh
 actor=next(o for o in ue.find_instances('LovikaRecastNavMesh') if not ue.objname(o).startswith('Default__'))
 mesh=navmesh.read_navmesh(ue,actor)
 me=r.loc(r.player)
 poly=mesh.find(me)
 extra={'me':me,'poly':poly,'ground_center':mesh.center[poly] if poly is not None else None,'velocity':r.vel(r.player)}
 for key in ['CapsuleComponent','Mesh','CharacterMovement']:
  try:
   ptr=ue.q(r.player+ue.field(r.player,key).offset)
   row={'class':ue.objname(ue.cls(ptr))}
   fields={'CapsuleComponent':['CapsuleHalfHeight','CapsuleRadius'],'Mesh':['RelativeLocation'],'CharacterMovement':['MovementMode']}[key]
   for f in fields:
    off=ue.field(ptr,f).offset
    if f=='RelativeLocation':
     import struct
     row[f]=struct.unpack('<ddd',ue.read(ptr+off,24))
    elif f=='MovementMode':row[f]=ue.read(ptr+off,1).hex()
    else:row[f]=ue.f32(ptr+off)
   extra[key]=row
  except Exception as e:extra[key]=str(e)
 from pathlib import Path
 try:extra['calibration']=json.loads((HERE/'calib.json').read_text())
 except Exception:pass
 print('GEOMETRY',json.dumps(extra,ensure_ascii=False),flush=True)
 ps="Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(w)?\\.exe$' -and $_.CommandLine -match '(loop_step|travel_nav_test|nav_test|ppo_bot|learn_bot)\\.py' } | ForEach-Object { $script=[regex]::Match($_.CommandLine,'(loop_step|travel_nav_test|nav_test|ppo_bot|learn_bot)\\.py').Value; [pscustomobject]@{PID=$_.ProcessId;Parent=$_.ParentProcessId;Script=$script} } | ConvertTo-Json -Compress"
 p=subprocess.run(['powershell','-NoProfile','-Command',ps],capture_output=True,text=True,errors='replace',timeout=15)
 print('PROCESSES',p.stdout,p.stderr,flush=True)
except Exception:traceback.print_exc()
