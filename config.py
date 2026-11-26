"""
config.py — Cấu hình trung tâm cho Stoic Daily Video Automation Pipeline.
Tệp này được tạo tự động theo cấu hình cá nhân của bạn và sẵn sàng chạy trên GitHub Actions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Tuple


PIPELINE_BUILD: str = "v3.5"

# ==============================================================================
# 1. CẤU HÌNH CÁ NHÂN (Tùy chỉnh trước khi chạy)
# ==============================================================================

# Ngôn ngữ nội dung video: "en-US" (Tiếng Anh) hoặc "vi-VN" (Tiếng Việt)
LANGUAGE: str = os.getenv("PIPELINE_LANGUAGE", "vi-VN")

# Tỷ lệ khung hình video: "16:9" (1920x1080 ngang) hoặc "9:16" (1080x1920 dọc)
ASPECT_RATIO: str = os.getenv("PIPELINE_ASPECT_RATIO", "16:9")

# Chủ đề cốt lõi của kênh
CHANNEL_TOPIC: str = "Stoicism & Modern Masculinity / Mindset (Triết lý Khắc kỷ & Tư duy bản lĩnh hiện đại)"

# Phong cách hình ảnh 2D cố định (nhúng nhất quán vào mọi prompt Imagen)
VISUAL_STYLE_PROMPT: str = (
    "Clean flat minimalist stickman explainer illustration on cool ice-gray #EEF2F7 studio background (NOT generic beige/cream), crisp bold deep navy-black #0F172A ink stickman narrator wearing a simple tie with clear facial expressions, simple line icons, vivid cobalt blue #2563EB arrows and highlight marks, uncluttered high-contrast diagram easy to understand in 1 second, no dark muddy shadows, no watermark"
)

# Chế độ diễn hoạt hình ảnh video:
# - "stickman_whiteboard": Tạo nhiều ảnh minh họa theo từng ý content, chuyển cảnh mượt (KHÔNG dùng cây bút)
# - "ken_burns_2d": Ảnh 2D tĩnh kết hợp chuyển động máy quay zoom/pan mượt
# - "pen_sketch": Cây bút chuyển động vẽ nét phác họa rồi đổ bóng hiện hình
VIDEO_VISUAL_MODE: str = os.getenv("VIDEO_VISUAL_MODE", "stickman_whiteboard")
VIDEO_PLAYBACK_SPEED: float = float(os.getenv("VIDEO_PLAYBACK_SPEED", "1.25"))
WHITEBOARD_BG_COLOR: str = os.getenv("WHITEBOARD_BG_COLOR", "#EEF2F7")
WHITEBOARD_INK_COLOR: str = os.getenv("WHITEBOARD_INK_COLOR", "#0F172A")
WHITEBOARD_ACCENT_COLOR: str = os.getenv("WHITEBOARD_ACCENT_COLOR", "#2563EB")
PEN_SKETCH_PAPER_THEME: str = os.getenv("PEN_SKETCH_PAPER_THEME", "classic_parchment")
PEN_SKETCH_DRAW_RATIO: float = 0.65
PEN_SKETCH_WASH_RATIO: float = 0.20

# Số lượng video sản xuất mỗi ngày (khớp với matrix trên GitHub Actions)
DAILY_VIDEO_COUNT: int = int(os.getenv("DAILY_VIDEO_COUNT", "5"))


# ==============================================================================
# 2. CẤU HÌNH GOOGLE CLOUD CONSOLE (XÁC THỰC 100% BẰNG FILE SERVICE ACCOUNT JSON)
# ==============================================================================
# Đặt file `service-account-key.json` ở thư mục gốc hoặc cấu hình `GOOGLE_APPLICATION_CREDENTIALS`
# / `GCP_SA_KEY`. Module `src/gcp_auth.py` sẽ tự động đọc `project_id` trong file JSON.

GCP_PROJECT_ID: str = os.getenv("GCP_PROJECT_ID", "")  # Tùy chọn (tự lấy từ file JSON)
GDRIVE_FOLDER_ID: str = os.getenv("GDRIVE_FOLDER_ID", "")

# Vertex AI Locations (100% Google Cloud Console — KHÔNG dùng Google AI Studio):
# - LLM dùng "global" để tận dụng điều hướng tải tự động
# - Imagen & Embedding dùng vùng tiêu chuẩn (us-central1)
VERTEX_LLM_LOCATION: str = os.getenv("VERTEX_LLM_LOCATION", "global")
VERTEX_IMAGEN_LOCATION: str = os.getenv("VERTEX_IMAGEN_LOCATION", "us-central1")
VERTEX_EMBEDDING_LOCATION: str = os.getenv("VERTEX_EMBEDDING_LOCATION", "us-central1")


# ==============================================================================
# 3. CHUỖI AUTO-FALLBACK MODEL (LLM, IMAGEN, VOICE TTS, EMBEDDING, MUSIC)
# ==============================================================================

LLM_FALLBACK_MODELS: List[str] = [
    "gemini-4-hydrogen",
    "gemini-3-flash-preview",
    "gemini-4-neon",
    "gemini-3.1-pro-preview",
    "gemini-2.5-flash",
    "gemini-3.1-flash-lite",
]

IMAGEN_FALLBACK_MODELS: List[str] = [
    "gemini-3.1-flash-lite-image",
    "gemini-nano-banana-2.1",
    "gemini-3-pro-image",
    "gemini-2.5-flash-image",
    "imagen-4.0-generate-001",
    "imagen-4.0-fast-generate-001",
    "imagen-3.0-generate-002",
]

# Chuỗi Tạo giọng đọc AI tự nhiên (Gemini Native TTS -> tự động fallback xuống Google Cloud TTS)
TTS_PRIMARY_PROVIDER: str = os.getenv("TTS_PRIMARY_PROVIDER", "gemini_tts")
TTS_FALLBACK_MODELS: List[str] = [
    "gemini-2.5-flash-tts",
    "gemini-3.8-flash-tts",
    "gemini-3.8-flash-lite-tts",
]
TTS_VOICE_PERSONA: str = os.getenv("TTS_VOICE_PERSONA", "Puck")
TTS_VOICE_STYLE: str = os.getenv(
    "TTS_VOICE_STYLE",
    "Warm, articulate modern essayist narrator, calm steady rhythm, conversational clarity",
)

EMBEDDING_FALLBACK_MODELS: List[str] = [
    "text-embedding-004",
    "gemini-embedding-001",
]

MUSIC_FALLBACK_MODELS: List[str] = [
    "lyria-3-pro-preview",
    "lyria-3-clip-preview",
]

# Exponential Backoff + Jitter cho lỗi nhất thời (429 / 503): 10s -> 20s -> 40s
BACKOFF_DELAYS_SECONDS: Tuple[int, ...] = (10, 20, 40)
BACKOFF_JITTER_MAX_SECONDS: float = 3.5


# ==============================================================================
# 4. CẤU HÌNH ANTI-DUPLICATION ENGINE 3 TẦNG
# ==============================================================================

HISTORY_FILENAME: str = "history_log.json"
HISTORY_RETENTION_DAYS: int = 90
SEMANTIC_SIMILARITY_THRESHOLD: float = 0.86
OPEN_TOPIC_EXPANSION: bool = os.getenv("OPEN_TOPIC_EXPANSION", "true").strip().lower() != "false"

# Kho gợi ý mở rộng đa lĩnh vực (chỉ dùng làm nguồn cảm hứng dự phòng khi brainstorm mở gặp sự cố)
PHILOSOPHERS_AND_SCHOOLS: List[str] = [
    "Tâm lý học hành vi & Thiên kiến nhận thức (Daniel Kahneman, Amos Tversky)",
    "Khoa học thần kinh về thói quen, sự chú ý & Dopamine (Andrew Huberman, Cal Newport)",
    "Tâm lý học ý nghĩa & Nội lực vượt nghịch cảnh (Viktor Frankl, Carl Jung)",
    "Kinh tế học hành vi & Tư duy ra quyết định xác suất (Charlie Munger, Nassim Taleb)",
    "Triết học phương Đông & Nghệ thuật tĩnh tâm (Lão Tử, Thiền tông, Miyamoto Musashi)",
    "Chiến lược & Quyền lực mềm trong lịch sử (Tôn Tử, Machiavelli, Robert Greene)",
    "Triết lý Khắc kỷ cổ đại (Marcus Aurelius, Seneca, Epictetus)",
    "Triết học hiện sinh & Tự kiến tạo giá trị (Nietzsche, Schopenhauer, Albert Camus)",
    "Tư duy hệ thống & Mô hình tinh thần đa ngành (First Principles, Inversion, Second-Order Thinking)",
    "Kỷ luật thực chiến & Chủ nghĩa Tối giản tinh thần (Essentialism, Deep Work)",
    "Tâm lý đàm phán, thuyết phục & Ảnh hưởng xã hội (Robert Cialdini, Chris Voss)",
    "Tiểu sử & Bước ngoặt lịch sử của những nhân vật kiệt xuất ít người biết",
    "Tâm lý học tiến hóa & Bản năng sinh tồn trong thế giới hiện đại",
    "Tư duy tài chính cá nhân, tự do thời gian & Lãi kép cuộc đời (Morgan Housel, Naval Ravikant)",
]

MODERN_CONTEXTS: List[str] = [
    "Bẫy so sánh ngầm, FOMO và cách định nghĩa thước đo thành công của riêng mình",
    "Nghệ thuật ra quyết định sáng suốt khi thiếu thông tin và áp lực thời gian cao",
    "Tâm lý tiền bạc: Vì sao thu nhập tăng nhưng cảm giác bất an tài chính vẫn không giảm",
    "Hội chứng kiệt sức thầm lặng (Quiet Burnout) và cách phục hồi năng lượng nhận thức",
    "Nghệ thuật đàm phán, nói 'không' đúng lúc và bảo vệ thời gian cá nhân",
    "Thiên kiến nhận thức khiến người thông minh vẫn lặp lại cùng một sai lầm trong công việc",
    "Làm chủ sự tập trung sâu giữa thời đại thuật toán và thông báo liên tục",
    "Tâm lý trong các mối quan hệ: Nhận diện thao túng cảm xúc và xây dựng kết nối lành mạnh",
    "Cách bộ não phản ứng với sợ hãi, thất bại và cơ chế biến áp lực thành bản lĩnh",
    "Bẫy hoàn hảo (Perfectionism) và nghệ thuật bắt đầu hành động khi chưa sẵn sàng",
    "Xây dựng uy tín thầm lặng, giao tiếp có trọng lượng và lắng nghe chiến lược",
    "Tư duy dài hạn: Tại sao 1% cải thiện thầm lặng mỗi ngày luôn thắng nỗ lực bộc phát",
    "Quản trị cái tôi khi đang ở đỉnh cao lẫn khi rơi xuống đáy sự nghiệp",
    "Nghệ thuật học nhanh, tư duy phản biện và tự nâng cấp kỹ năng giữa kỷ nguyên AI",
    "Cô độc chủ động vs. Cô đơn tiêu cực: Rèn sức mạnh nội tâm khi bước đi một mình",
    "Đối diện bất định kinh tế, biến động nghề nghiệp và tâm thế 'Chống mong manh' (Antifragile)",
]

NARRATIVE_HOOKS: List[str] = [
    "Phân tích một thí nghiệm tâm lý học kinh điển hé lộ sự thật bất ngờ về hành vi con người",
    "Câu chuyện lịch sử hoặc tiểu sử thực tế ít người biết dẫn vào bài học thực chiến",
    "Bóc tách một niềm tin phổ biến mà phần lớn mọi người đang hiểu sai hoàn toàn",
    "Giải mã một mô hình tư duy (Mental Model) sắc bén của giới tinh hoa và cách áp dụng ngay",
    "Phân tích chuỗi nhân quả: Một thói quen nhỏ vô hình đang âm thầm định hình 5 năm tới của bạn",
    "Đối chiếu sắc bén giữa phản xạ bản năng thông thường và cách xử lý của người có tư duy bậc cao",
    "Câu hỏi phản trực giác mở đầu khiến người xem phải tự soi lại chính mình",
    "Nghiên cứu tình huống thực tế (Case Study): Từ một khoảnh khắc sai lầm đến bước ngoặt đổi đời",
    "Bản đồ tư duy trực quan: 3 cấp độ trưởng thành tâm lý trong cùng một tình huống đời thường",
    "Giải phẫu cơ chế hoạt động của não bộ đằng sau một thói quen khó bỏ",
]


# ==============================================================================
# 5. THÔNG SỐ KỊCH BẢN, TTS, ĐỒ HỌA 2D & FFMPEG
# ==============================================================================

SCENES_MIN: int = 22
SCENES_MAX: int = 26
# Số lượng ảnh minh họa theo từng vế câu (visual_beats) trong MỖI phân cảnh:
# 24 cảnh × 3–4 ảnh/cảnh = ~72–96 ảnh khác nhau cho video 5 phút (~3–4 giây/ảnh ở tốc độ 1.25x)
BEATS_PER_SCENE_MIN: int = 3
BEATS_PER_SCENE_MAX: int = 4

TARGET_WORD_COUNT: Dict[str, Tuple[int, int]] = {
    "en-US": (880, 980),
    "vi-VN": (1200, 1360),
}

CRITIC_MIN_SCORE: float = 7.5
SCRIPT_MAX_RETRIES: int = 1
VIDEO_REVIEW_MAX_RETRIES: int = 2

RESOLUTION_MAP: Dict[str, Tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
}

VIDEO_FPS: int = 30
FFMPEG_PRESET: str = "veryfast"
FFMPEG_TUNE: str = ""
FFMPEG_CRF: str = "22"
BGM_VOLUME_DB: str = "-22dB"

MIN_VIDEO_DURATION_SEC: float = 210.0
MAX_VIDEO_DURATION_SEC: float = 420.0
MAX_SILENCE_GAP_SEC: float = 3.2
CONTACT_SHEET_INTERVAL_SEC: int = 10


@dataclass(frozen=True)
class VoiceOption:
    language_code: str
    voice_name: str
    speaking_rate: float
    pitch: float


# Chuỗi giọng nam trầm Google Cloud Text-to-Speech (Chirp 3 HD -> Studio -> Neural2 -> WaveNet)
TTS_VOICE_CHAINS: Dict[str, List[VoiceOption]] = {
    "en-US": [
        VoiceOption("en-US", "en-US-Chirp3-HD-Charon", 0.95, 0.0),
        VoiceOption("en-US", "en-US-Studio-Q", 0.94, 0.0),
        VoiceOption("en-US", "en-US-Chirp3-HD-Fenrir", 0.95, 0.0),
        VoiceOption("en-US", "en-US-Neural2-D", 0.93, -2.0),
        VoiceOption("en-US", "en-US-Neural2-J", 0.94, -1.5),
    ],
    "vi-VN": [
        VoiceOption("vi-VN", "vi-VN-Chirp3-HD-Charon", 0.95, 0.0),
        VoiceOption("vi-VN", "vi-VN-Chirp3-HD-Fenrir", 0.95, 0.0),
        VoiceOption("vi-VN", "vi-VN-Neural2-D", 0.95, -2.0),
        VoiceOption("vi-VN", "vi-VN-Wavenet-B", 0.95, -2.0),
        VoiceOption("vi-VN", "vi-VN-Standard-B", 0.96, -1.5),
    ],
}

BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR: str = os.path.join(BASE_DIR, "output")
WORK_DIR: str = os.path.join(BASE_DIR, "workdir")
ASSETS_BGM_DIR: str = os.path.join(BASE_DIR, "assets", "bgm")
ASSETS_FONTS_DIR: str = os.path.join(BASE_DIR, "assets", "fonts")
SCRIPTS_JSON_PATH: str = os.path.join(OUTPUT_DIR, "scripts.json")


def get_video_resolution() -> Tuple[int, int]:
    """Trả về (width, height) theo ASPECT_RATIO hiện tại."""
    if ASPECT_RATIO not in RESOLUTION_MAP:
        raise ValueError(f"ASPECT_RATIO không hợp lệ: {ASPECT_RATIO}. Chỉ hỗ trợ '16:9' hoặc '9:16'.")
    return RESOLUTION_MAP[ASPECT_RATIO]
