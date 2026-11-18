# Luong YOLO rieng cho video panorama

`main_yolo.py` doc video panorama da ghep va can bang rung trong `output1/panorama_stabilized_source.mp4`, chay YOLO tren tung frame, ve bounding box, roi xuat `output1/panorama_yolo.mp4`. Ma `main.py` va thu muc `outputs` khong thay doi. Nguon video dai 2402 frame, 30 fps; script se bao loi neu doc thieu frame.

## Chay lai

Can Python co `ultralytics`, `torch`, `opencv-python` va `ffmpeg`. Lan chay mau nay su dung Python tai `C:\Users\Mori\PycharmProjects\Xulyanh\.venv\Scripts\python.exe`; model duoc luu noi bo tai `models/yolov8s-worldv2.pt`.

```powershell
& 'C:\Users\Mori\PycharmProjects\Xulyanh\.venv\Scripts\python.exe' .\main_yolo.py
```

Mac dinh chi ve cac lop COCO `person`, `bicycle`, `car`, `motorcycle` (0, 1, 2, 3), nguong tin cay 0.25. De ve tat ca lop, them `--classes all`. Co the doi video dau vao bang `--input`, muc luu bang `--output`, do tin cay bang `--confidence`.

File `output1/panorama_yolo.csv` luu tung box theo so frame, thoi gian, lop, do tin cay va toa do tren frame panorama cuoi. YOLO duoc chay sau khi ghep va can bang rung, nen box nam trong he toa do cua video xuat. Video nay khong co am thanh vi luong panorama goc cung khong co am thanh.
