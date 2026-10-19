"""가상 엑스박스 패드 시험. 게임 창을 앞에 두면 캐릭터가 움직이는지 본다.

순서(5초 뒤 시작): 왼쪽 스틱으로 한 바퀴 걷기 4초 → X 세 번(근접) → LB(구르기).
진짜 패드는 그대로 꽂아 둬도 된다. 오프라인 사본 캐릭터로만 시험.
"""
import math
import sys
import time

try:
    import vgamepad as vg
except Exception as e:
    print("가상 패드를 못 켰어:", e)
    print("ViGEmBus 드라이버가 없으면 이 주소에서 ViGEmBus_1.22.0_x64_x86_arm64.exe를 받아 설치해 줘:")
    print("https://github.com/nefarius/ViGEmBus/releases/tag/v1.22.0")
    sys.exit(1)

pad = vg.VX360Gamepad()
import gamewin
gamewin.focus_game()
time.sleep(0.5)

print("걷기")
t0 = time.time()
while time.time() - t0 < 4:
    a = (time.time() - t0) / 4 * 2 * math.pi
    pad.left_joystick_float(math.cos(a) * 0.9, math.sin(a) * 0.9)
    pad.update()
    time.sleep(0.02)
pad.left_joystick_float(0, 0)
pad.update()
time.sleep(0.3)

print("근접 공격 3번")
for _ in range(3):
    pad.press_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_X)
    pad.update()
    time.sleep(0.1)
    pad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_X)
    pad.update()
    time.sleep(0.35)

print("구르기")
pad.press_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER)
pad.update()
time.sleep(0.1)
pad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER)
pad.update()
time.sleep(1)
pad.reset()
pad.update()
print("끝. 캐릭터가 걷고, 때리고, 굴렀으면 성공이야.")
