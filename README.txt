마던2 AI 실험실 (VPT 작게 따라 하기)

0_setup.bat           처음 한 번. 파이썬·PyTorch(그래픽카드용)·영상 도구를 이 폴더에 받음(약 3GB)
(녹화)                MCD2-AI-Recorder.exe로 오프라인 캐릭터 플레이를 3~5시간 모음 → E:\MCD2-AI\data (E 드라이브 없으면 문서\MCD2-AI\data, data_path.txt에 다른 폴더를 적으면 그곳)
1_train_idm.bat       키 맞히는 AI 학습 → runs\idm\best.pt
2_download_videos.bat videos.txt에 적은 유튜브 영상 받기(360p)
3_label_videos.bat    영상에 키 입력 채워 넣기 → data_video
4_train_bc.bat        내 녹화 + 영상으로 모방학습 → runs\bc\best.pt

학습 중엔 그래픽카드를 꽉 쓰니까 게임 안 할 때 돌려. 남의 영상은 학습에만 쓰고 밖에 올리지 마.
