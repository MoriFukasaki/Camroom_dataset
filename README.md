# Do an du phong — Quay 3 camera, ghép panorama và YOLO

Đẩy lên GitHub và cài trên máy bạn bè: xem [docs/GITHUB.md](docs/GITHUB.md). Cần Node 24 và Python 3.14; dependency Python trực tiếp được cố định theo môi trường đã thử. Video mẫu, model, môi trường ảo và secrets không nằm trong repo.

Project tích hợp riêng. Hai project nguồn không bị sửa: web Camroom ở `demo-big-data/bui`, đồ án Python ở `Do an xu ly anh`. Thư mục `legacy/` là bản sao mã Python, cấu hình, model và toàn bộ video mẫu/kết quả cũ; không tự áp cấu hình cũ cho video quay mới. `.venv` và `.idea` có sẵn của project mới được giữ, không sao chép môi trường hoặc secrets từ nguồn.

## Chạy ngay trên máy này

Mở thư mục project này bằng PyCharm hoặc terminal:

```powershell
npm run dev:local
```

Mở `http://localhost:3108`. Lệnh chạy web và worker, Ctrl+C dừng cả hai. `.env.local` riêng đã được tạo cho local; không chứa khóa Neon và không truy cập dữ liệu production. Nếu thiếu file, lệnh tự tạo bằng chế độ exclusive, không ghi đè file đã có. Không chạy đồng thời thêm `npm start` vào cùng cổng.

Máy tính có thể cấp quyền camera trên localhost. Điện thoại cần link HTTPS (Render/Caddy), không mở camera qua HTTP địa chỉ IP LAN. Local mode phục vụ thử nghiệm, không dành cho deploy: phòng vẫn ở RAM, không restart giữa buổi quay; media/queue nằm trong `data/`. Khi dùng Neon, metadata phòng và hàng đợi có migration riêng để phục hồi.

## Cách dùng

1. Tạo phòng **3 camera**. Join đúng vị trí: **CAM 1 bên phải**, **CAM 2 giữa**, **CAM 3 bên trái**. Giữ camera cố định, cùng hướng ngang, giữ nguyên zoom/ống kính/độ phân giải; các camera liền kề phải thấy chung một vùng sân đủ rộng. Slot là vị trí, không tự suy ra từ nội dung ảnh. Có thể thêm một máy Chỉ xem làm admin.
2. Preview mặc định là **một ảnh JPEG mỗi 5 giây, luân phiên từng máy**. Với 3 camera, mỗi góc mới khoảng 15 giây/lần; ảnh hiển thị tuổi. Không truyền WebRTC video ở chế độ này, không cần TURN cho ảnh. `PREVIEW_MODE=video` mới bật lại WebRTC (khi đó cần cấu hình TURN như web cũ).
3. Mỗi máy bấm Sẵn sàng; admin quay/dừng chung. Bản gốc yêu cầu 1080p/30 FPS/10 Mbps theo khả năng máy; không hạ track ghi để giảm preview. Dữ liệu ghi vào bộ nhớ trình duyệt, **chỉ upload sau khi dừng**. Có nút hoãn upload chờ mạng tốt, dừng riêng máy khi mất kết nối. Giữ trang mở/màn hình sáng. 10 Mbps khoảng 75 MB/phút/máy; nếu IndexedDB lỗi thì RAM chỉ 64 MB, không phù hợp quay dài.
4. Đợi đủ ba bản gốc. Tác vụ tự chuyển Chờ video → Chờ worker → Căn camera → Ghép và nhận diện → Hoàn tất. Worker trên PC phải đang chạy (`npm run worker` hoặc `npm run dev:local`). Video cuối không có âm thanh, giống pipeline panorama cũ.
5. Nếu báo **needs_calibration**, mở Căn điểm thủ công. Lấy ảnh các camera khi vị trí vẫn giống lúc quay, chọn CAM 3 rồi CAM 1: bấm một giao vạch trên ảnh camera bên, rồi bấm cùng giao vạch trên CAM 2. Tối thiểu 4 cặp/camera, nên chọn 6–10 cặp rải rộng, không thẳng hàng và không chọn người/cây. Lưu để worker tự chạy lại. Đây là căn phối cảnh, không phải chỉnh cho đẹp bằng cắt chồng ảnh tùy ý.
6. Chỉ admin được tải/xóa bản gốc và thành phẩm. Đợi xử lý xong trước khi quay lượt mới. Lượt mới xóa video cũ theo chính sách của phòng; tải bản muốn giữ trước. Có nút **Bỏ tác vụ ghép** nếu muốn ngừng xử lý, rồi admin mới xóa video đầu vào lỗi. Không tự xóa các bản chưa upload/đang ghép.

## Bộ xử lý mới

`processor/pipeline.py` đồng bộ theo mốc bắt đầu thực tế + timestamp video, lấy vùng thời gian chung; ước lượng SIFT/RANSAC cho camera cố định; kiểm tra số điểm, độ phủ, sai số, hướng trái/phải và canvas. Không đạt sẽ yêu cầu điểm thủ công. Không tái sử dụng motion-keyframes đo theo video cũ.

Pipeline cân màu trên vùng chung, chọn đường nối có phạt vùng chuyển động và thay đổi đường nối theo thời gian, hòa mép hẹp, tự cắt canvas thành hình chữ nhật tránh viền đen/răng cưa. YOLOWorld nhận diện trên panorama sau ghép, vẽ box rồi encode H.264 CRF 18 **một lần**. CSV box, ảnh preview, calibration và báo cáo nằm cạnh file `data/worker/<job-id>/final.mp4`. Bản gốc không bị encode lại.

Hiệu chỉnh theo mặt sân không thể bảo đảm người/cột/cây ở độ sâu khác không bị thị sai. Ảnh thiếu vùng nhìn chung hoặc vị trí thay đổi không thể sửa hoàn toàn bằng blending. Timestamp/đồng hồ mạng không thay thế đồng bộ phần cứng: nên tạo tín hiệu chung đầu lượt để kiểm tra hậu kỳ; hiện chưa tự đồng bộ bằng âm thanh. Nhận diện có thể sai/bỏ sót; model COCO có nhiều lớp, không bảo đảm bắt được bóng nhỏ ngoài sân.

### Hiệu chỉnh méo ống kính (tùy chọn)

Chụp ít nhất 10 ảnh bàn cờ bằng đúng ống kính/hướng và cấu hình cần dùng. Ví dụ bàn cờ 9×6 góc trong:

```powershell
.\.venv\Scripts\python.exe processor/calibrate_lens.py --images calibration/cam1 --columns 9 --rows 6 --output calibration/lens1.json
```

Tạo file rig JSON dạng `{"lenses":{"1":<nội dung lens1.json>,"2":<...>,"3":<...>}}` (thay placeholders bằng JSON thật), đặt `PROCESSING_CALIBRATION_FILE=calibration/rig.json` trong env worker. Pipeline sửa méo cả frame và tọa độ điểm trước khi ghép. Đây là hiệu chuẩn riêng từng máy/ống kính; không có thông số giả mặc định. File rig cũng có thể chứa `points` với cấu trúc cặp `source`/`target` tọa độ chuẩn hóa 0..1 cho slot `1` và `3`.

## Deploy bản mới, giữ nguyên web cũ

- Tạo **repo/service mới**, không push đè repo `bui` khi chưa chủ động chuyển. Web Node chạy trên Render; Python worker chạy PC hoặc máy xử lý riêng, không mở cổng inbound trên PC.
- Build `npm ci && npm run build`; Start `npm start` chạy migration 001/002/**003_processing.sql**. Dùng Neon branch/database riêng cho bản dự phòng và bucket private; không lấy nhầm env production. Runtime giữ driver `pg`/AWS SDK đang dùng. Migration dùng URL unpooled.
- Render env: `DATABASE_URL`, `DATABASE_URL_UNPOOLED`, `AWS_*`, `NEON_BUCKET`, optional Realtime, `PREVIEW_MODE=snapshots`, `NODE_ENV=production`, **PROCESSING_WORKER_TOKEN** random ít nhất 32 ký tự. Không đặt `CAMROOM_LOCAL_MEDIA=1` trên production, bỏ `CAMROOM_OFFLINE`. Bản local không sẵn cloud credentials.
- PC worker env: `PROCESSING_SERVER_URL=https://<service>.onrender.com`, cùng `PROCESSING_WORKER_TOKEN`, optional `PROCESSING_PYTHON`. Xóa `CAMROOM_OFFLINE/CAMROOM_LOCAL_MEDIA` khi chuyển sang cloud. Chạy `npm run worker`. Worker chỉ cần URL + token, không cần đưa khóa bucket/DB lên trình duyệt hoặc mở cổng PC.
- **Chỉ chạy 1 web instance** cho phòng và queue hiện tại, worker chạy tuần tự một job. Lease/heartbeat 90 giây cho phép nhận lại việc nếu worker chết; lỗi xử lý hiển thị để admin thử lại. Metadata queue dùng Postgres khi cấu hình DB, local dùng JSON atomic trong `data/processing`.
- Render free có đĩa tạm: video đã hoàn tất trong Neon còn nguyên, nhưng phiên upload/chunks chưa chốt có thể mất khi restart/deploy. Không restart giữa upload; dùng persistent disk nếu cần. Khi chưa upload thành công, không đóng/xóa dữ liệu trình duyệt.

## Cài lại và kiểm thử

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci
npm test
npm run test:python
npm run build
```

Các file video/model đã sao chép chỉ nằm trên máy, bị gitignore để tránh push nặng. Khi chuyển máy, sao chép riêng `legacy/models/yolov8s-worldv2.pt`. Không tải model từ đường dẫn người dùng chưa tin cậy.

Chứng minh end-to-end bằng bản sao video mẫu (không dùng cloud):

```powershell
.\.venv\Scripts\python.exe scripts/make-sample-manifest.py --legacy-calibration --short
npm run prove:integration
```

Bài này dùng đúng cấu hình đã đo cho **bộ mẫu**, xuất 1 giây 30 FPS có YOLO, chạy đủ API upload → queue → worker → Python → upload thành phẩm → admin download và so SHA-256. Kết quả ở `verification/final-integrated.mp4`, báo cáo `verification/integration-report.json`. Cấu hình bộ mẫu không được áp mặc định cho video mới. Giới hạn 1 giây chỉ nằm trong script QA; worker bình thường xử lý toàn bộ phần thời gian chung. Không đặt `PROCESSING_TEST_SECONDS` khi dùng thật.

Tham khảo nguồn gốc web: `docs/CAMROOM-LEGACY.md`; bản Python gốc sao chép trong `legacy/`. Không có auto-deploy, không sửa schema/bucket production trong bước dựng project này.
