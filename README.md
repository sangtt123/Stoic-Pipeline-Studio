# Stoic Daily 2D Video Automation Pipeline (Google Cloud Console + GitHub Actions)

Hệ thống Python tự động hóa hoàn toàn (100% headless trên Ubuntu GitHub Actions) sử dụng **100% API của Google Cloud Console** (Vertex AI + Cloud Text-to-Speech + Google Drive — **KHÔNG dùng Google AI Studio API Key**) để sản xuất **5 video Triết lý Khắc kỷ 2D (~5 phút/video)** lúc **02:00 sáng mỗi ngày**.

## Cấu trúc dự án

```text
.
├── .github/workflows/
│   └── daily_stoic_pipeline.yml   # GitHub Actions 2 giai đoạn (Stage 1 -> Matrix 5 workers)
├── assets/
│   └── bgm/                       # (Tùy chọn) Thả các file nhạc nền .mp3 không bản quyền vào đây
├── src/
│   ├── gcp_auth.py                # Nạp & xác thực file JSON Service Account dùng chung (tự lấy project_id)
│   ├── vertex_client.py           # Auto-Fallback Wrapper (100% Vertex AI vertexai=True)
│   ├── drive_manager.py           # Đồng bộ history_log.json & Resumable Upload .mp4 lên Drive
│   ├── dedup_manager.py           # Cơ chế chống trùng lặp 3 tầng (90 ngày + Matrix + Embedding)
│   ├── step1_script_planner.py    # Giai đoạn 1: Viết 5 kịch bản + Lọc trùng + AI Critic (>= 8/10)
│   ├── tts_generator.py           # Google Cloud TTS (Chirp 3 HD / Studio / Neural2) + Vertex TTS fallback
│   ├── graphics_2d.py             # Vẽ khung viền, thanh tiến trình, trích dẫn, hạt phim (Pillow)
│   ├── sketch_animator.py         # Động cơ Bút mực chuyển động vẽ nét hiện hình (OpenCV + FFmpeg pipe)
│   ├── video_renderer.py          # Render FFmpeg ultrafast + chuyển động 2D + Contact Sheet
│   ├── video_reviewer.py          # Kiểm duyệt kỹ thuật + Gemini Vision Contact Sheet
│   ├── step2_video_worker.py      # Giai đoạn 2: Worker độc lập theo VIDEO_INDEX (0..4)
│   └── test_gcp_connection.py     # Script kiểm thử nhanh (10 giây) toàn bộ API Google Cloud Console
├── config.py                      # Toàn bộ cấu hình cá nhân & chuỗi fallback model
├── requirements.txt
└── .env.example
```

## Hướng dẫn kết nối 100% bằng file Service Account JSON

### 1. Bật 3 API bắt buộc trên Google Cloud Console
Chạy lệnh trong Cloud Shell hoặc bật trực tiếp tại **APIs & Services → Library**:
```bash
gcloud services enable \
  aiplatform.googleapis.com \
  texttospeech.googleapis.com \
  drive.googleapis.com
```

### 2. Tạo Service Account & tải file JSON Key
- Vào **IAM & Admin → Service Accounts** → Tạo Service Account mới (ví dụ: `stoic-pipeline-bot`).
- Cấp quyền **Vertex AI User** (`roles/aiplatform.user`).
- Vào tab **Keys → Add Key → JSON** để tải file khóa `.json`.
- Đổi tên file thành `service-account-key.json` và đặt ngay tại thư mục gốc dự án (khi chạy local). File này tự chứa sẵn `project_id`, `client_email` và `private_key` cho cả Vertex AI, Cloud TTS và Google Drive.

### 3. Chia sẻ thư mục Google Drive
- Tạo 1 thư mục trống trên Google Drive và chia sẻ cho **`client_email` nằm trong file JSON** với quyền **Editor**.
- Lấy **Folder ID** phía sau `/folders/` trên thanh địa chỉ URL.

### 4. Chạy kiểm thử nhanh (10 giây) trước khi render video
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # Điền GDRIVE_FOLDER_ID (project_id tự động lấy từ service-account-key.json)

python -m src.test_gcp_connection
# Tùy chọn test thêm tạo 1 ảnh 2D bằng Vertex AI Imagen:
python -m src.test_gcp_connection --with-imagen
```

### 5. Khai báo GitHub Secrets & chạy tự động
Vào **GitHub Repo → Settings → Secrets and variables → Actions** chỉ cần thêm **2 biến bắt buộc**:
1. `GCP_SA_KEY` *(dán toàn bộ nội dung file JSON của Service Account — hệ thống tự đọc `project_id`)*
2. `GDRIVE_FOLDER_ID` *(ID thư mục Google Drive đã chia sẻ cho email trong file JSON)*

*(Tùy chọn: có thể khai báo thêm `GCP_PROJECT_ID` nếu muốn ghi đè project khác với trong file JSON).*

Sau đó vào tab **Actions → Daily Stoic 2D Video Pipeline → Run workflow** để chạy test ngay lập tức.
