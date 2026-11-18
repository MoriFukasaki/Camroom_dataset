import cv2
from pathlib import Path
root=Path(__file__).resolve().parents[1];dest=root/'verification';dest.mkdir(exist_ok=True)
for slot in (1,2,3):
    cap=cv2.VideoCapture(str(root/'legacy/inputs'/f'Cam {slot}.mp4'));ok,frame=cap.read();cap.release()
    if not ok:raise ValueError('Cannot read copied sample')
    frame=cv2.resize(frame,(640,360));cv2.imwrite(str(dest/f'cam{slot}.jpg'),frame,[cv2.IMWRITE_JPEG_QUALITY,15])
