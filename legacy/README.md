# Ghép panorama từ ba camera mới

Dự án dùng ba video 1920×1080 trong `inputs/`, theo thứ tự trái sang phải **Cam 3 → Cam 2 → Cam 1**. Chạy bằng interpreter của `.venv`:

```powershell
python main.py
```

Kết quả mặc định là `outputs/panorama.mp4` và ảnh kiểm tra `outputs/preview.jpg`. Thử ngắn trước khi chạy toàn bộ:

```powershell
python main.py --seconds 5 --output outputs/thu_5_giay.mp4
```

`configs/panorama.json` chứa phép chiếu và vùng cắt đo cho đúng ba video mới. `configs/motion_keyframes.json` chứa các mốc căn chỉnh hai camera bên với Cam 2 sau mỗi 0,5 giây. Mã nội suy giữa các mốc và sửa thêm những cú dịch nhanh bằng cách so sánh vùng sân chung ở từng frame. Cam 2 làm hệ tọa độ tham chiếu, nên đường kẻ sân ở hai mép nối không còn trôi dần so với video giữa. Mã đọc timestamp thực để lấy khung hình gần nhất tại mỗi mốc 30 fps, vì ba tệp ghi tốc độ khung hình hơi khác nhau. Mã đo sáng/màu trên vùng sân chung tại bảy thời điểm và dùng hiệu chỉnh cố định suốt video. Bản xuất là 2080×780, 30 fps và dài khoảng 80 giây.

Phép chiếu theo mặt sân căn được đường kẻ và gạch lát nhưng cây, người và các vật ở độ sâu khác vẫn có thị sai. Đường ghép có thể lộ khi người đi qua hoặc ở tán cây. Muốn cải thiện thêm cần hiệu chuẩn camera, căn chỉnh cục bộ theo độ sâu và chọn đường ghép có xét chuyển động theo thời gian. Cấu hình này không dành cho video khác hoặc kích thước khác; cần đo lại homography, mốc chuyển động và vùng cắt khi đổi dữ liệu.
