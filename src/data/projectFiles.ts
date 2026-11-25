import JSZip from 'jszip';
import type { PipelineConfig, ProjectFileEntry } from '../types/pipeline';

import rawGcpAuth from '../../python-project/src/gcp_auth.py?raw';
import rawVertexClient from '../../python-project/src/vertex_client.py?raw';
import rawDriveManager from '../../python-project/src/drive_manager.py?raw';
import rawDedupManager from '../../python-project/src/dedup_manager.py?raw';
import rawStep1Planner from '../../python-project/src/step1_script_planner.py?raw';
import rawTtsGenerator from '../../python-project/src/tts_generator.py?raw';
import rawGraphics2d from '../../python-project/src/graphics_2d.py?raw';
import rawSketchAnimator from '../../python-project/src/sketch_animator.py?raw';
import rawVideoRenderer from '../../python-project/src/video_renderer.py?raw';
import rawVideoReviewer from '../../python-project/src/video_reviewer.py?raw';
import rawStep2Worker from '../../python-project/src/step2_video_worker.py?raw';
import rawTestGcpConnection from '../../python-project/src/test_gcp_connection.py?raw';
import rawSrcInit from '../../python-project/src/__init__.py?raw';
import rawRequirements from '../../python-project/requirements.txt?raw';
import rawEnvExample from '../../python-project/.env.example?raw';
import rawGitignore from '../../python-project/.gitignore?raw';
import rawReadme from '../../python-project/README.md?raw';
import rawBgmGitkeep from '../../python-project/assets/bgm/.gitkeep?raw';

export const DEFAULT_PIPELINE_CONFIG: PipelineConfig = {
  language: 'vi-VN',
  aspectRatio: '16:9',
  videoVisualMode: 'stickman_whiteboard',
  penSketchPaperTheme: 'classic_parchment',
  whiteboardThemeId: 'cool_studio',
  whiteboardBgColor: '#EEF2F7',
  whiteboardInkColor: '#0F172A',
  whiteboardAccentColor: '#2563EB',
  channelTopic:
    'Stoicism & Modern Masculinity / Mindset (Triết lý Khắc kỷ & Tư duy bản lĩnh hiện đại)',
  visualStylePrompt:
    'Clean flat minimalist stickman explainer illustration on cool ice-gray #EEF2F7 studio background (NOT generic beige/cream), crisp bold deep navy-black #0F172A ink stickman narrator wearing a simple tie with clear facial expressions, simple line icons, vivid cobalt blue #2563EB arrows and highlight marks, uncluttered high-contrast diagram easy to understand in 1 second, no dark muddy shadows, no watermark',
  dailyVideoCount: 5,
  cronTimezone: 'ICT_0200',
  similarityThreshold: 0.75,
  criticMinScore: 8.0,
  historyRetentionDays: 90,
  llmFallbackModels: [
    'gemini-3.1-pro-preview',
    'gemini-3.8-flash',
    'gemini-3.5-flash',
    'gemini-3.1-flash-lite',
    'gemini-2.5-pro',
    'gemini-2.5-flash',
  ],
  imagenFallbackModels: [
    'imagen-4.0-fast-generate-001',
    'imagen-3.0-fast-generate-002',
  ],
  ttsPrimaryProvider: 'cloud_tts',
  ttsFallbackModels: [
    'gemini-2.5-flash-tts',
    'gemini-3.8-flash-tts',
    'gemini-3.8-flash-lite-tts',
  ],
  ttsVoicePersona: 'Charon',
  ttsVoiceStyle:
    'Deep, calm, resonant stoic male narrator, measured documentary pacing, rich authoritative baritone',
  embeddingFallbackModels: ['text-embedding-004', 'gemini-embedding-001'],
  musicFallbackModels: ['lyria-3-pro-preview', 'lyria-3-clip-preview'],
};

export const VOICE_PERSONA_OPTIONS = [
  {
    id: 'Charon' as const,
    label: 'Charon — Nam trầm sâu, điềm tĩnh (Khuyên dùng)',
    style:
      'Deep, calm, resonant stoic male narrator, measured documentary pacing, rich authoritative baritone',
  },
  {
    id: 'Fenrir' as const,
    label: 'Fenrir — Nam uy lực, sắc bén, quyết đoán',
    style:
      'Strong, commanding baritone male voice, confident slow cadence, stoic warrior gravitas',
  },
  {
    id: 'Puck' as const,
    label: 'Puck — Giọng kể chuyện gần gũi, rõ nhịp',
    style:
      'Warm, articulate modern essayist narrator, calm steady rhythm, conversational clarity',
  },
  {
    id: 'Kore' as const,
    label: 'Kore — Giọng trầm ấm, mạch lạc chuẩn biên tập',
    style:
      'Clear, composed editorial documentary narrator, smooth balanced intonation',
  },
];

export const VISUAL_STYLE_PRESETS = [
  {
    id: 'cool_studio',
    label: 'Xám băng #EEF2F7 · Xanh Cobalt (Mới lạ · Chống trùng YouTube)',
    prompt:
      'Clean flat minimalist stickman explainer illustration on cool ice-gray #EEF2F7 studio background (NOT generic beige/cream), crisp bold deep navy-black #0F172A ink stickman narrator wearing a simple tie with clear facial expressions, simple line icons, vivid cobalt blue #2563EB arrows and highlight marks, uncluttered high-contrast diagram easy to understand in 1 second, no dark muddy shadows, no watermark',
  },
  {
    id: 'midnight_chalk',
    label: 'Bảng xanh đêm #111927 · Vàng hổ phách (Tương phản cao)',
    prompt:
      'Clean flat minimalist stickman explainer illustration on deep midnight-navy #111927 chalkboard background, crisp bright off-white #F3F6FA chalk-ink stickman with clear expressions and simple line icons, vivid amber-gold #F59E0B arrows and emphasis marks, high-CTR uncluttered YouTube explainer diagram, no watermark',
  },
  {
    id: 'sage_mist',
    label: 'Xanh bạc hà trầm #E8F0EC · Cam đất (Dịu mắt · Khác biệt)',
    prompt:
      'Clean flat minimalist stickman explainer illustration on muted sage-mist #E8F0EC background, crisp deep forest-charcoal #13221C ink stickman and clean line icons, vivid terracotta-vermilion #D94E2A arrows and X-marks, uncluttered diagram easy to read on mobile, no watermark',
  },
  {
    id: 'obsidian_crimson',
    label: 'Đen nhám #15161A · Đỏ san hô (Mạnh mẽ · Chuẩn Khắc kỷ)',
    prompt:
      'Clean flat minimalist stickman explainer illustration on matte obsidian-charcoal #15161A background, crisp warm ivory #F4F1EA ink stickman and simple line icons, vivid coral-red #EF4444 arrows and X-marks, sharp uncluttered composition, no watermark',
  },
];

export const PHILOSOPHERS_LIST = [
  'Marcus Aurelius (Meditations — Hoàng đế & sự tự chủ nội tâm)',
  'Seneca (Letters from a Stoic — Quản trị thời gian & nghịch cảnh)',
  'Epictetus (Enchiridion — Nhị phân kiểm soát & tự do từ bên trong)',
  'Musonius Rufus (Thực hành khổ hạnh hiện đại & rèn luyện thể chất)',
  'Zeno xứ Citium (Khởi nguồn Khắc kỷ & biến mất mát thành sức mạnh)',
  'Cato the Younger (Chính trực tuyệt đối & không khuất phục áp lực số đông)',
  'Tâm lý học hành vi hiện đại (Cognitive Reframing kết hợp Stoicism)',
  'Kỷ luật thép & Chủ nghĩa Tối giản tinh thần (Essentialism & Deep Focus)',
];

export const MODERN_CONTEXTS_LIST = [
  'Áp lực sự nghiệp, thu nhập và cảm giác tụt hậu ở tuổi 25–40',
  'Sự phản bội, mối quan hệ độc hại và nghệ thuật rời đi trong im lặng',
  'Kiểm soát cơn giận, cái tôi bị tổn thương và phản ứng dưới áp lực',
  'Cô độc chủ động, tự lập tài chính và không phụ thuộc vào sự công nhận',
  'Vượt qua thất bại lớn, phá sản tinh thần và tái thiết từ con số không',
  'Thói quen buổi sáng, kỷ luật sinh học và đánh bại sự trì hoãn mãn tính',
  'Nghiện dopamine ngắn hạn, mạng xã hội và lấy lại sự tập trung sâu',
  'Đối diện bất định kinh tế, lo âu tương lai và nghệ thuật Premeditatio Malorum',
  'Giao tiếp ít nói nhưng có trọng lượng, thiết lập ranh giới cá nhân',
  'Chấp nhận mất mát, vô thường và tập trung vào hành động hôm nay',
];

export const NARRATIVE_HOOKS_LIST = [
  'Câu chuyện lịch sử ít người biết mở đầu đầy kịch tính',
  'Nghịch lý tâm lý ngược đời khiến người xem phải dừng lại suy ngẫm',
  'Bài học đắt giá từ một sai lầm phổ biến mà 90% đàn ông hiện đại mắc phải',
  'Đối chiếu sắc bén giữa một tình huống cổ đại và áp lực thế kỷ 21',
  'Thử thách 7 ngày thực hành cụ thể từng bước thay đổi tư duy',
  'Bóc tách một câu nói kinh điển thường bị hiểu sai hoàn toàn',
  'Kịch bản giả định: Điều gì xảy ra nếu bạn biến mất 90 ngày để rèn mình',
];

function pyEscape(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, ' ');
}

function pyList(items: string[], indent = '    '): string {
  return items.map((item) => `${indent}"${pyEscape(item)}",`).join('\n');
}

export function generateConfigPy(cfg: PipelineConfig): string {
  return `"""
config.py — Cấu hình trung tâm cho Stoic Daily Video Automation Pipeline.
Tệp này được tạo tự động theo cấu hình cá nhân của bạn và sẵn sàng chạy trên GitHub Actions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Tuple


# ==============================================================================
# 1. CẤU HÌNH CÁ NHÂN (Tùy chỉnh trước khi chạy)
# ==============================================================================

# Ngôn ngữ nội dung video: "en-US" (Tiếng Anh) hoặc "vi-VN" (Tiếng Việt)
LANGUAGE: str = os.getenv("PIPELINE_LANGUAGE", "${cfg.language}")

# Tỷ lệ khung hình video: "16:9" (1920x1080 ngang) hoặc "9:16" (1080x1920 dọc)
ASPECT_RATIO: str = os.getenv("PIPELINE_ASPECT_RATIO", "${cfg.aspectRatio}")

# Chủ đề cốt lõi của kênh
CHANNEL_TOPIC: str = "${pyEscape(cfg.channelTopic)}"

# Phong cách hình ảnh 2D cố định (nhúng nhất quán vào mọi prompt Imagen)
VISUAL_STYLE_PROMPT: str = (
    "${pyEscape(cfg.visualStylePrompt)}"
)

# Chế độ diễn hoạt hình ảnh video:
# - "stickman_whiteboard": Tạo nhiều ảnh minh họa theo từng ý content, chuyển cảnh mượt (KHÔNG dùng cây bút)
# - "ken_burns_2d": Ảnh 2D tĩnh kết hợp chuyển động máy quay zoom/pan mượt
# - "pen_sketch": Cây bút chuyển động vẽ nét phác họa rồi đổ bóng hiện hình
VIDEO_VISUAL_MODE: str = os.getenv("VIDEO_VISUAL_MODE", "${cfg.videoVisualMode}")
VIDEO_PLAYBACK_SPEED: float = float(os.getenv("VIDEO_PLAYBACK_SPEED", "1.25"))
WHITEBOARD_BG_COLOR: str = os.getenv("WHITEBOARD_BG_COLOR", "${cfg.whiteboardBgColor}")
WHITEBOARD_INK_COLOR: str = os.getenv("WHITEBOARD_INK_COLOR", "${cfg.whiteboardInkColor}")
WHITEBOARD_ACCENT_COLOR: str = os.getenv("WHITEBOARD_ACCENT_COLOR", "${cfg.whiteboardAccentColor}")
PEN_SKETCH_PAPER_THEME: str = os.getenv("PEN_SKETCH_PAPER_THEME", "${cfg.penSketchPaperTheme}")
PEN_SKETCH_DRAW_RATIO: float = 0.65
PEN_SKETCH_WASH_RATIO: float = 0.20

# Số lượng video sản xuất mỗi ngày (khớp với matrix trên GitHub Actions)
DAILY_VIDEO_COUNT: int = int(os.getenv("DAILY_VIDEO_COUNT", "${cfg.dailyVideoCount}"))


# ==============================================================================
# 2. CẤU HÌNH GOOGLE CLOUD CONSOLE (XÁC THỰC 100% BẰNG FILE SERVICE ACCOUNT JSON)
# ==============================================================================
# Đặt file \`service-account-key.json\` ở thư mục gốc hoặc cấu hình \`GOOGLE_APPLICATION_CREDENTIALS\`
# / \`GCP_SA_KEY\`. Module \`src/gcp_auth.py\` sẽ tự động đọc \`project_id\` trong file JSON.

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
${pyList(cfg.llmFallbackModels)}
]

IMAGEN_FALLBACK_MODELS: List[str] = [
${pyList(cfg.imagenFallbackModels)}
]

# Chuỗi Tạo giọng đọc AI tự nhiên (Gemini Native TTS -> tự động fallback xuống Google Cloud TTS)
TTS_PRIMARY_PROVIDER: str = os.getenv("TTS_PRIMARY_PROVIDER", "${cfg.ttsPrimaryProvider}")
TTS_FALLBACK_MODELS: List[str] = [
${pyList(cfg.ttsFallbackModels)}
]
TTS_VOICE_PERSONA: str = os.getenv("TTS_VOICE_PERSONA", "${cfg.ttsVoicePersona}")
TTS_VOICE_STYLE: str = os.getenv(
    "TTS_VOICE_STYLE",
    "${pyEscape(cfg.ttsVoiceStyle)}",
)

EMBEDDING_FALLBACK_MODELS: List[str] = [
${pyList(cfg.embeddingFallbackModels)}
]

MUSIC_FALLBACK_MODELS: List[str] = [
${pyList(cfg.musicFallbackModels)}
]

# Exponential Backoff + Jitter cho lỗi nhất thời (429 / 503): 10s -> 20s -> 40s
BACKOFF_DELAYS_SECONDS: Tuple[int, ...] = (10, 20, 40)
BACKOFF_JITTER_MAX_SECONDS: float = 3.5


# ==============================================================================
# 4. CẤU HÌNH ANTI-DUPLICATION ENGINE 3 TẦNG
# ==============================================================================

HISTORY_FILENAME: str = "history_log.json"
HISTORY_RETENTION_DAYS: int = ${cfg.historyRetentionDays}
SEMANTIC_SIMILARITY_THRESHOLD: float = ${cfg.similarityThreshold.toFixed(2)}

PHILOSOPHERS_AND_SCHOOLS: List[str] = [
${pyList(PHILOSOPHERS_LIST)}
]

MODERN_CONTEXTS: List[str] = [
${pyList(MODERN_CONTEXTS_LIST)}
]

NARRATIVE_HOOKS: List[str] = [
${pyList(NARRATIVE_HOOKS_LIST)}
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

CRITIC_MIN_SCORE: float = ${cfg.criticMinScore.toFixed(1)}
SCRIPT_MAX_RETRIES: int = 2
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
`;
}

export function generateWorkflowYaml(cfg: PipelineConfig): string {
  const cronExpr = cfg.cronTimezone === 'ICT_0200' ? '0 19 * * *' : '0 2 * * *';
  const cronComment =
    cfg.cronTimezone === 'ICT_0200'
      ? '# 02:00 sáng giờ Việt Nam (UTC+7) = 19:00 UTC ngày hôm trước'
      : '# 02:00 sáng giờ UTC';
  const matrixIndices = Array.from({ length: cfg.dailyVideoCount }, (_, i) => i).join(', ');

  return `name: Daily Stoic 2D Video Pipeline

on:
  schedule:
    ${cronComment}
    - cron: '${cronExpr}'

  workflow_dispatch:
    inputs:
      language:
        description: 'Ngôn ngữ nội dung (vi-VN hoặc en-US)'
        required: false
        default: '${cfg.language}'
        type: choice
        options:
          - vi-VN
          - en-US
      aspect_ratio:
        description: 'Tỷ lệ khung hình (16:9 hoặc 9:16)'
        required: false
        default: '${cfg.aspectRatio}'
        type: choice
        options:
          - '16:9'
          - '9:16'
      tts_provider:
        description: 'Hệ thống tạo giọng đọc ưu tiên'
        required: false
        default: '${cfg.ttsPrimaryProvider}'
        type: choice
        options:
          - gemini_tts
          - cloud_tts

permissions:
  contents: read

env:
  PIPELINE_LANGUAGE: \${{ github.event.inputs.language || '${cfg.language}' }}
  PIPELINE_ASPECT_RATIO: \${{ github.event.inputs.aspect_ratio || '${cfg.aspectRatio}' }}
  VIDEO_VISUAL_MODE: '${cfg.videoVisualMode}'
  PEN_SKETCH_PAPER_THEME: '${cfg.penSketchPaperTheme}'
  TTS_PRIMARY_PROVIDER: \${{ github.event.inputs.tts_provider || '${cfg.ttsPrimaryProvider}' }}
  TTS_VOICE_PERSONA: '${cfg.ttsVoicePersona}'
  DAILY_VIDEO_COUNT: '${cfg.dailyVideoCount}'
  VERTEX_LLM_LOCATION: 'global'
  VERTEX_IMAGEN_LOCATION: 'us-central1'
  VERTEX_EMBEDDING_LOCATION: 'us-central1'

jobs:
  # ============================================================================
  # GIAI ĐOẠN 1: Lập kế hoạch ${cfg.dailyVideoCount} kịch bản + Chống trùng 3 tầng + AI Critic Review
  # ============================================================================
  job1_plan_scripts:
    name: Stage 1 — Script Planner & 3-Tier Dedup
    runs-on: ubuntu-latest
    timeout-minutes: 20
    env:
      GCP_PROJECT_ID: \${{ secrets.GCP_PROJECT_ID }}
      GDRIVE_FOLDER_ID: \${{ secrets.GDRIVE_FOLDER_ID }}

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install Python dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Write GCP Service Account credentials
        env:
          GCP_SA_KEY: \${{ secrets.GCP_SA_KEY }}
        run: |
          if [ -z "$GCP_SA_KEY" ]; then
            echo "::error::Repository secret GCP_SA_KEY dang bi trong! Vao Settings -> Secrets and variables -> Actions -> Repository secrets va tao secret ten GCP_SA_KEY."
            exit 1
          fi
          printf '%s' "$GCP_SA_KEY" > "\${{ runner.temp }}/gcp-sa-key.json"
          echo "GOOGLE_APPLICATION_CREDENTIALS=\${{ runner.temp }}/gcp-sa-key.json" >> $GITHUB_ENV

      - name: Run Stage 1 Script Planner
        run: python -m src.step1_script_planner

      - name: Upload approved scripts.json artifact
        uses: actions/upload-artifact@v4
        with:
          name: daily-stoic-scripts
          path: output/scripts.json
          retention-days: 3

      - name: Cleanup credentials
        if: always()
        run: rm -f "\${{ runner.temp }}/gcp-sa-key.json"

  # ============================================================================
  # GIAI ĐOẠN 2: Chạy song song ${cfg.dailyVideoCount} Matrix Workers (VIDEO_INDEX 0..${cfg.dailyVideoCount - 1})
  # ============================================================================
  job2_produce_videos:
    name: Stage 2 — Produce Video #\${{ matrix.video_index }}
    needs: job1_plan_scripts
    runs-on: ubuntu-latest
    timeout-minutes: 25
    env:
      GCP_PROJECT_ID: \${{ secrets.GCP_PROJECT_ID }}
      GDRIVE_FOLDER_ID: \${{ secrets.GDRIVE_FOLDER_ID }}
    strategy:
      fail-fast: false
      matrix:
        video_index: [${matrixIndices}]

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install FFmpeg & Unicode Serif Fonts (Ubuntu headless)
        run: |
          sudo apt-get update -qq
          sudo apt-get install -y -qq ffmpeg fonts-noto-core fonts-dejavu-core

      - name: Install Python dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Download scripts.json artifact from Stage 1
        uses: actions/download-artifact@v4
        with:
          name: daily-stoic-scripts
          path: output

      - name: Write GCP Service Account credentials
        env:
          GCP_SA_KEY: \${{ secrets.GCP_SA_KEY }}
        run: |
          if [ -z "$GCP_SA_KEY" ]; then
            echo "::error::Repository secret GCP_SA_KEY dang bi trong! Vao Settings -> Secrets and variables -> Actions -> Repository secrets va tao secret ten GCP_SA_KEY."
            exit 1
          fi
          printf '%s' "$GCP_SA_KEY" > "\${{ runner.temp }}/gcp-sa-key.json"
          echo "GOOGLE_APPLICATION_CREDENTIALS=\${{ runner.temp }}/gcp-sa-key.json" >> $GITHUB_ENV

      - name: Run Video Worker (Index \${{ matrix.video_index }})
        env:
          VIDEO_INDEX: \${{ matrix.video_index }}
        run: python -m src.step2_video_worker

      - name: Cleanup credentials
        if: always()
        run: rm -f "\${{ runner.temp }}/gcp-sa-key.json"
`;
}

export function buildProjectFiles(cfg: PipelineConfig): ProjectFileEntry[] {
  return [
    {
      path: '.github/workflows/daily_stoic_pipeline.yml',
      name: 'daily_stoic_pipeline.yml',
      folder: '.github/workflows',
      language: 'yaml',
      summary:
        'Workflow 2 giai đoạn trên Ubuntu runner: Cron 02:00 sáng -> Job 1 tạo kịch bản -> Job 2 chạy song song Matrix workers.',
      isDynamic: true,
      content: generateWorkflowYaml(cfg),
    },
    {
      path: 'config.py',
      name: 'config.py',
      folder: 'root',
      language: 'python',
      summary:
        'Cấu hình cá nhân, chuỗi Auto-Fallback đầy đủ (LLM, Imagen 2D, Gemini Native TTS, Cloud TTS, Embedding, Lyria) và Ma trận 3 trục.',
      isDynamic: true,
      content: generateConfigPy(cfg),
    },
    {
      path: 'src/gcp_auth.py',
      name: 'gcp_auth.py',
      folder: 'src',
      language: 'python',
      summary:
        'Trung tâm xác thực 100% bằng file Service Account JSON: tự quét service-account-key.json / GOOGLE_APPLICATION_CREDENTIALS / GCP_SA_KEY và tự đọc project_id.',
      content: rawGcpAuth,
    },
    {
      path: 'src/vertex_client.py',
      name: 'vertex_client.py',
      folder: 'src',
      language: 'python',
      summary:
        'Auto-Fallback Wrapper dùng google-genai SDK (vertexai=True + Service Account JSON) cho LLM, Vision, Imagen 2D, Vertex TTS và Embedding.',
      content: rawVertexClient,
    },
    {
      path: 'src/tts_generator.py',
      name: 'tts_generator.py',
      folder: 'src',
      language: 'python',
      summary:
        'Tạo giọng đọc 2 tầng: ưu tiên Gemini Native TTS (gemini-3.8-flash-tts -> flash-lite-tts) và tự động fallback xuống Google Cloud TTS (Studio/Chirp3-HD/Neural2).',
      content: rawTtsGenerator,
    },
    {
      path: 'src/dedup_manager.py',
      name: 'dedup_manager.py',
      folder: 'src',
      language: 'python',
      summary:
        'Anti-Duplication Engine 3 tầng: Lịch sử 90 ngày trên Drive + Ma trận trực giao + Embedding (gemini-embedding-2 / text-embedding-004).',
      content: rawDedupManager,
    },
    {
      path: 'src/drive_manager.py',
      name: 'drive_manager.py',
      folder: 'src',
      language: 'python',
      summary:
        'Quét thư mục con trên Google Drive tính số thứ tự tiếp theo (bắt đầu từ 1), tạo thư mục "<STT> - <Chủ đề>", đồng bộ history_log.json và upload cả Video (.mp4) + Thumbnail (.png) vào cùng thư mục.',
      content: rawDriveManager,
    },
    {
      path: 'src/step1_script_planner.py',
      name: 'step1_script_planner.py',
      folder: 'src',
      language: 'python',
      summary:
        'Giai đoạn 1: Quét số thứ tự thư mục hiện có trên Drive để cấp STT liên tiếp không trùng (tránh race condition), tạo 5 kịch bản ~5 phút kèm thumbnail_hook/prompt và xuất scripts.json.',
      content: rawStep1Planner,
    },
    {
      path: 'src/step2_video_worker.py',
      name: 'step2_video_worker.py',
      folder: 'src',
      language: 'python',
      summary:
        'Giai đoạn 2: Worker độc lập theo VIDEO_INDEX (0..4) — TTS, Imagen 2D, tạo Thumbnail 1280x720 đồng bộ màu nền, FFmpeg MP4 1.25x, Vision QA và tải cả Video + Thumbnail vào thư mục "<STT> - <Chủ đề>" trên Drive.',
      content: rawStep2Worker,
    },
    {
      path: 'src/graphics_2d.py',
      name: 'graphics_2d.py',
      folder: 'src',
      language: 'python',
      summary:
        'Pillow RGBA 2D engine: render Thumbnail YouTube 1280x720 đồng bộ màu nền kênh (WHITEBOARD_BG/INK/ACCENT) + khung viền, thanh tiến trình và trích dẫn UTF-8.',
      content: rawGraphics2d,
    },
    {
      path: 'src/sketch_animator.py',
      name: 'sketch_animator.py',
      folder: 'src',
      language: 'python',
      summary:
        'Động cơ hoạt hình Bút vẽ nét hiện hình (OpenCV Contour Tracing + Fountain Pen sprite + FFmpeg stdin pipe ultrafast).',
      content: rawSketchAnimator,
    },
    {
      path: 'src/video_renderer.py',
      name: 'video_renderer.py',
      folder: 'src',
      language: 'python',
      summary:
        'FFmpeg CPU ultrafast (-preset ultrafast -tune stillimage -r 24): zoom/pan 2D mượt, ghép overlay, trộn BGM và xuất Contact Sheet.',
      content: rawVideoRenderer,
    },
    {
      path: 'src/video_reviewer.py',
      name: 'video_reviewer.py',
      folder: 'src',
      language: 'python',
      summary:
        'Kiểm duyệt thành phẩm: ffprobe + silencedetect kỹ thuật kết hợp Gemini Vision thẩm định 1 ảnh lưới Contact Sheet (15s/frame).',
      content: rawVideoReviewer,
    },
    {
      path: 'src/test_gcp_connection.py',
      name: 'test_gcp_connection.py',
      folder: 'src',
      language: 'python',
      summary:
        'Script kiểm thử nhanh (10 giây) toàn bộ API Google Cloud Console: Vertex AI LLM, Embedding, Cloud TTS, Imagen, FFmpeg/OpenCV và Google Drive.',
      content: rawTestGcpConnection,
    },
    {
      path: 'src/__init__.py',
      name: '__init__.py',
      folder: 'src',
      language: 'python',
      summary: 'Định nghĩa package Python cho thư mục src/.',
      content: rawSrcInit,
    },
    {
      path: 'requirements.txt',
      name: 'requirements.txt',
      folder: 'root',
      language: 'text',
      summary: 'Danh sách thư viện Python tối giản cho Vertex AI, Cloud TTS, Google Drive, Pillow và NumPy.',
      content: rawRequirements,
    },
    {
      path: 'README.md',
      name: 'README.md',
      folder: 'root',
      language: 'markdown',
      summary: 'Tài liệu hướng dẫn cấu hình GCP IAM, Google Drive Service Account và GitHub Secrets.',
      content: rawReadme,
    },
    {
      path: '.env.example',
      name: '.env.example',
      folder: 'root',
      language: 'text',
      summary: 'Mẫu biến môi trường để kiểm thử local trước khi đẩy lên GitHub Actions.',
      content: rawEnvExample,
    },
    {
      path: '.gitignore',
      name: '.gitignore',
      folder: 'root',
      language: 'text',
      summary: 'Loại trừ file khóa Service Account, .env, output và file media tạm khỏi Git.',
      content: rawGitignore,
    },
    {
      path: 'assets/bgm/.gitkeep',
      name: '.gitkeep',
      folder: 'assets/bgm',
      language: 'text',
      summary: 'Thư mục chứa nhạc nền không bản quyền (.mp3/.wav) tự động chọn ngẫu nhiên khi render.',
      content: rawBgmGitkeep,
    },
  ];
}

export async function downloadProjectZip(cfg: PipelineConfig): Promise<void> {
  const zip = new JSZip();
  const files = buildProjectFiles(cfg);

  for (const file of files) {
    zip.file(file.path, file.content);
  }

  const blob = await zip.generateAsync({ type: 'blob' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `stoic-video-pipeline-${cfg.language.toLowerCase()}-${cfg.aspectRatio.replace(':', 'x')}.zip`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
