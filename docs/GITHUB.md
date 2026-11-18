# Push Do an du phong lên GitHub

Repo này độc lập với `bui`, chưa đặt remote và chưa tự push. Đừng upload ZIP toàn bộ thư mục: nó chứa môi trường ảo, video, model và file env riêng.

Trong terminal tại root project:

```powershell
npm run check:publish
npm test
npm run test:python
npm run build
git add .
npm run check:publish
git diff --cached --name-only
git commit -m "Add integrated multicamera panorama and YOLO project"
git branch -M main
git remote add origin https://github.com/YOUR_ACCOUNT/YOUR_NEW_REPOSITORY.git
git push -u origin main
```

Thay URL bằng repo mới, rỗng. Không dùng force push và không trỏ nhầm repo `bui`. Nếu Git yêu cầu danh tính, cấu hình `user.name`/`user.email` của chính bạn. File `.env.local`, `data`, `verification`, `.venv`, video mẫu và model phải vắng mặt trong danh sách staged. Bộ quét vẫn từ chối chúng khi bị `git add -f` nhầm. Chỉ `.env.example` với trường credential trống được công khai.

## Máy của người test

1. Cài Node 24 và Python 3.14, clone repo và mở root bằng PyCharm.
2. Chạy `npm ci`, `python -m venv .venv`, rồi cài `requirements.txt` bằng Python trong `.venv`.
3. Copy model tin cậy `yolov8s-worldv2.pt` vào `legacy/models/` (tạo thư mục nếu chưa có). Model/video không đi kèm Git; kiểm tra quyền phân phối trước khi chia sẻ riêng.
4. Chạy `npm run dev:local`; mở `http://localhost:3108`. Lần đầu tạo env riêng, không cần gửi secret trong chat/GitHub. Muốn chạy bài prove mẫu, copy riêng video mẫu vào `legacy/inputs/` rồi làm theo README.

CI kiểm tra Node và hình học Python bằng dữ liệu tổng hợp, không cần model/video/khóa cloud. Bài end-to-end YOLO thật được chạy riêng trên máy có model và video; CI không giả vờ đã chạy bài này.

Docker là phương án web bổ sung; không bắt buộc khi chạy local và image web không bao gồm Python worker/model. Không commit output `dist`; Render build lại từ mã nguồn. Xem README cho cấu hình HTTPS/Neon/worker nếu cần điện thoại thật.
