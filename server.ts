import 'dotenv/config';
import express from 'express';
import crypto from 'crypto';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { execFile } from 'child_process';
import { promisify } from 'util';
import { fileURLToPath } from 'url';
import { GoogleGenAI, ThinkingLevel, Type } from '@google/genai';
import { GoogleAuth } from 'google-auth-library';
import {
  inferSemanticBlueprint,
  normalizeStudioBlueprint,
  renderStudioShotSvg,
  renderStudioThumbnailSvg,
  STUDIO_COMPOSITIONS,
  STUDIO_EXPRESSIONS,
  STUDIO_OVERLAYS,
  STUDIO_POSES,
  STUDIO_PROPS,
  type StudioShotBlueprint,
  type StudioThumbnailBlueprint,
} from './serverStudioArtEngine';

const execFileAsync = promisify(execFile);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = Number(process.env.PORT || 3000);
const IS_PROD = process.env.NODE_ENV === 'production';

interface ServiceAccountJson {
  type: 'service_account';
  project_id: string;
  private_key_id?: string;
  private_key: string;
  client_email: string;
  client_id?: string;
  token_uri?: string;
  [key: string]: unknown;
}

interface LoadedServiceAccount {
  credentials: ServiceAccountJson;
  projectId: string;
  clientEmail: string;
  source: string;
}

const DEFAULT_SA_FILENAMES = [
  'service-account-key.json',
  'credentials.json',
  'gcp-key.json',
] as const;

function tryJsonParseRobust(rawText: string): Record<string, unknown> | null {
  let candidate = rawText.trim();
  if (!candidate) return null;

  // Bỏ cặp dấu nháy bọc ngoài nếu bị copy dư trong .env / Secrets
  if (
    (candidate.startsWith("'") && candidate.endsWith("'")) ||
    (candidate.startsWith('"') && candidate.endsWith('"') && candidate.includes('\\"type\\"'))
  ) {
    candidate = candidate.slice(1, -1).trim();
  }

  // Hỗ trợ chuỗi Service Account JSON mã hóa Base64
  if (!candidate.startsWith('{') && /^[A-Za-z0-9+/=\s]+$/.test(candidate) && candidate.length > 80) {
    try {
      const decoded = Buffer.from(candidate.replace(/\s+/g, ''), 'base64').toString('utf-8').trim();
      if (decoded.startsWith('{')) {
        candidate = decoded;
      }
    } catch {
      // Không phải Base64 hợp lệ
    }
  }

  if (!candidate.startsWith('{')) return null;

  const attempts = [
    candidate,
    // Nếu dán JSON bị biến \n trong chuỗi thành xuống dòng thật (control char)
    candidate.replace(/\r\n/g, '\n').replace(/(?<!\\)\n/g, '\\n'),
    // Nếu bị double-escape \"type\"
    candidate.replace(/\\"/g, '"'),
  ];

  for (const text of attempts) {
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>;
      }
    } catch {
      // Thử phương án parse tiếp theo
    }
  }
  return null;
}

function validateServiceAccountObject(
  obj: Record<string, unknown>,
  source: string
): LoadedServiceAccount | null {
  if (obj.type !== 'service_account') {
    return null;
  }

  const projectId = String(process.env.GCP_PROJECT_ID || obj.project_id || '').trim();
  const clientEmail = String(obj.client_email || '').trim();
  let privateKey = String(obj.private_key || '').trim();

  // Chuẩn hóa ký tự xuống dòng trong PEM private_key
  if (privateKey.includes('\\n')) {
    privateKey = privateKey.replace(/\\n/g, '\n');
  }

  if (!projectId || !clientEmail || !privateKey) {
    throw new Error(
      `File Service Account JSON (${source}) thiếu trường bắt buộc (project_id, client_email hoặc private_key).`
    );
  }

  const normalizedCreds: ServiceAccountJson = {
    ...(obj as ServiceAccountJson),
    project_id: projectId,
    client_email: clientEmail,
    private_key: privateKey,
  };

  return {
    credentials: normalizedCreds,
    projectId,
    clientEmail,
    source,
  };
}

function loadServiceAccountJson(): LoadedServiceAccount | null {
  // 1. GOOGLE_APPLICATION_CREDENTIALS: hỗ trợ cả đường dẫn file .json lẫn nội dung JSON / Base64 dán trực tiếp
  const gacVal = (process.env.GOOGLE_APPLICATION_CREDENTIALS || '').trim();
  if (gacVal) {
    const resolved = path.isAbsolute(gacVal) ? gacVal : path.resolve(__dirname, gacVal);
    if (fs.existsSync(resolved) && fs.statSync(resolved).isFile()) {
      const parsed = tryJsonParseRobust(fs.readFileSync(resolved, 'utf-8'));
      if (parsed) {
        const sa = validateServiceAccountObject(parsed, path.basename(resolved));
        if (sa) return sa;
      }
    } else {
      const parsed = tryJsonParseRobust(gacVal);
      if (parsed) {
        const sa = validateServiceAccountObject(parsed, 'env:GOOGLE_APPLICATION_CREDENTIALS');
        if (sa) return sa;
      }
    }
  }

  // 2. Các biến môi trường chứa chuỗi Service Account JSON (kể cả khi người dùng dán JSON vào GEMINI_API_KEY)
  const jsonEnvCandidates = [
    'GCP_SA_KEY',
    'GCP_SERVICE_ACCOUNT_JSON',
    'GOOGLE_CREDENTIALS',
    'SERVICE_ACCOUNT_JSON',
    'GEMINI_API_KEY',
  ] as const;

  for (const envName of jsonEnvCandidates) {
    const rawVal = (process.env[envName] || '').trim();
    if (!rawVal) continue;
    const parsed = tryJsonParseRobust(rawVal);
    if (parsed) {
      const sa = validateServiceAccountObject(parsed, `env:${envName}`);
      if (sa) return sa;
    }
  }

  // 3. Tự động quét file khóa JSON đặt tại thư mục gốc hoặc python-project/
  const searchDirs = [__dirname, path.resolve(__dirname, 'python-project')];
  for (const dir of searchDirs) {
    for (const fileName of DEFAULT_SA_FILENAMES) {
      const candidate = path.join(dir, fileName);
      if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
        const parsed = tryJsonParseRobust(fs.readFileSync(candidate, 'utf-8'));
        if (parsed) {
          const rel = path.relative(__dirname, candidate) || fileName;
          const sa = validateServiceAccountObject(parsed, rel);
          if (sa) return sa;
        }
      }
    }
  }

  return null;
}

function getValidPreviewApiKey(): string | null {
  const key = (process.env.GEMINI_API_KEY || '').trim();
  if (!key || key.startsWith('MY_') || key.startsWith('{')) {
    return null;
  }
  return key;
}

function getGenAIClient(): {
  ai: GoogleGenAI;
  mode: 'service_account_json' | 'sandbox_fallback';
  sa: LoadedServiceAccount | null;
} {
  const httpOptions = {
    headers: {
      'User-Agent': 'aistudio-build',
    },
  };

  // Ưu tiên 1: Xác thực 100% Google Cloud Console bằng file Service Account JSON
  const sa = loadServiceAccountJson();
  if (sa) {
    const ai = new GoogleGenAI({
      vertexai: true,
      project: sa.projectId,
      location: process.env.VERTEX_LLM_LOCATION || 'global',
      googleAuthOptions: {
        credentials: sa.credentials,
      },
      httpOptions,
    });
    return { ai, mode: 'service_account_json', sa };
  }

  // Dự phòng khi chạy thử trên web preview mà chưa nạp Service Account JSON
  const apiKey = getValidPreviewApiKey();
  if (apiKey) {
    const ai = new GoogleGenAI({
      apiKey,
      apiVersion: 'v1beta',
      httpOptions,
    });
    return { ai, mode: 'sandbox_fallback', sa: null };
  }

  throw new Error(
    'Chưa có thông tin xác thực hợp lệ. Hãy thêm Secret GCP_SA_KEY (dán nội dung file Service Account JSON của Google Cloud Console) hoặc đặt file ./service-account-key.json ở thư mục gốc.'
  );
}

function formatFriendlyApiError(err: unknown, mode: string): string {
  const raw = err instanceof Error ? err.message : String(err);
  if (raw.includes('API_KEY_INVALID') || raw.includes('API key not valid')) {
    if (mode === 'sandbox_fallback') {
      return (
        'Lỗi xác thực (API_KEY_INVALID): Khóa hiện tại trong Settings > Secrets không hợp lệ cho Gemini API. ' +
        'Nếu bạn muốn kết nối bằng Google Cloud Console Service Account JSON, hãy vào Settings > Secrets, thêm biến GCP_SA_KEY và dán toàn bộ nội dung file .json (hoặc kiểm tra lại khóa trong Settings > Secrets).'
      );
    }
  }
  return raw;
}

function wrapPcm16ToWavBase64(pcmBuffer: Buffer, sampleRate = 24000, channels = 1): string {
  if (pcmBuffer.length >= 12 && pcmBuffer.subarray(0, 4).toString('ascii') === 'RIFF') {
    return pcmBuffer.toString('base64');
  }
  const bitsPerSample = 16;
  const byteRate = (sampleRate * channels * bitsPerSample) / 8;
  const blockAlign = (channels * bitsPerSample) / 8;
  const header = Buffer.alloc(44);
  header.write('RIFF', 0);
  header.writeUInt32LE(36 + pcmBuffer.length, 4);
  header.write('WAVE', 8);
  header.write('fmt ', 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(channels, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(byteRate, 28);
  header.writeUInt16LE(blockAlign, 32);
  header.writeUInt16LE(bitsPerSample, 34);
  header.write('data', 36);
  header.writeUInt32LE(pcmBuffer.length, 40);
  return Buffer.concat([header, pcmBuffer]).toString('base64');
}

async function synthesizeViaGoogleCloudTTS(
  sa: LoadedServiceAccount,
  text: string,
  language: string,
  voicePersona: string
): Promise<{ audioBase64: string; mimeType: string; modelUsed: string; voiceName: string }> {
  const auth = new GoogleAuth({
    credentials: sa.credentials,
    scopes: ['https://www.googleapis.com/auth/cloud-platform'],
  });
  const client = await auth.getClient();
  const tokenResp = await client.getAccessToken();
  const accessToken = typeof tokenResp === 'string' ? tokenResp : tokenResp?.token;
  if (!accessToken) {
    throw new Error('Không thể lấy OAuth2 access token từ Service Account JSON cho Cloud TTS.');
  }

  const isVi = language.startsWith('vi');
  const langCode = isVi ? 'vi-VN' : 'en-US';
  const voiceCandidates = isVi
    ? [
        `vi-VN-Chirp3-HD-${voicePersona}`,
        'vi-VN-Chirp3-HD-Charon',
        'vi-VN-Neural2-D',
        'vi-VN-Wavenet-B',
        'vi-VN-Standard-B',
      ]
    : [
        `en-US-Chirp3-HD-${voicePersona}`,
        'en-US-Studio-Q',
        'en-US-Chirp3-HD-Charon',
        'en-US-Neural2-D',
        'en-US-Standard-D',
      ];

  const dedupedVoices = Array.from(new Set(voiceCandidates));
  let lastError = 'Google Cloud TTS không phản hồi.';

  for (const voiceName of dedupedVoices) {
    const isChirpOrStudio = voiceName.includes('Chirp') || voiceName.includes('Studio');
    const audioConfig: Record<string, unknown> = {
      audioEncoding: 'LINEAR16',
      sampleRateHertz: 24000,
      speakingRate: 0.95,
    };
    if (!isChirpOrStudio) {
      audioConfig.pitch = -1.5;
    }

    const resp = await fetch('https://texttospeech.googleapis.com/v1/text:synthesize', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
        'x-goog-user-project': sa.projectId,
      },
      body: JSON.stringify({
        input: { text },
        voice: {
          languageCode: langCode,
          name: voiceName,
        },
        audioConfig,
      }),
    });

    if (resp.ok) {
      const data = (await resp.json()) as { audioContent?: string };
      if (data.audioContent) {
        return {
          audioBase64: data.audioContent,
          mimeType: 'audio/wav',
          modelUsed: `Google Cloud TTS (${voiceName})`,
          voiceName,
        };
      }
    } else {
      const errText = await resp.text();
      lastError = `Cloud TTS (${voiceName}) HTTP ${resp.status}: ${errText.slice(0, 220)}`;
    }
  }

  throw new Error(lastError);
}

const SCRIPT_MODELS_VERTEX = ['gemini-2.5-flash', 'gemini-3.1-flash-lite', 'gemini-4-hydrogen'] as const;
const SCRIPT_MODELS_PREVIEW = ['gemini-4-hydrogen', 'gemini-3.1-flash-lite'] as const;
const ART_DIRECTOR_MODELS_PREVIEW = ['gemini-3.1-flash-lite', 'gemini-4-hydrogen'] as const;

function buildDirectorThinkingConfig(modelName: string) {
  return modelName.startsWith('gemini-4-')
    ? { thinkingConfig: { thinkingLevel: ThinkingLevel.LOW } }
    : {};
}

const TTS_GEMINI_CHAIN_MAP: Record<string, string[]> = {
  'gemini-3.8-flash-lite-tts': ['gemini-3.8-flash-lite-tts', 'gemini-3.8-flash-tts'],
  'gemini-3.8-flash-tts': ['gemini-3.8-flash-tts', 'gemini-3.8-flash-lite-tts'],
  'gemini-2.5-flash-tts': ['gemini-3.8-flash-lite-tts', 'gemini-3.8-flash-tts', 'gemini-2.5-flash-tts'],
};

async function startServer() {
  const app = express();
  app.use(express.json({ limit: '4mb' }));

  // 0. Trạng thái kết nối Google Cloud Console bằng file Service Account JSON (chỉ đọc, không lộ khóa)
  app.get('/api/gcp/status', (_req, res) => {
    try {
      const sa = loadServiceAccountJson();
      if (sa) {
        return res.json({
          connected: true,
          mode: 'service_account_json',
          projectId: sa.projectId,
          clientEmail: sa.clientEmail,
          source: sa.source,
          location: process.env.VERTEX_LLM_LOCATION || 'global',
        });
      }
      if (getValidPreviewApiKey()) {
        return res.json({
          connected: true,
          mode: 'sandbox_fallback',
          projectId: null,
          clientEmail: null,
          source: 'preview-runtime',
          location: 'sandbox',
        });
      }
      return res.json({
        connected: false,
        mode: 'unconfigured',
        projectId: null,
        clientEmail: null,
        source: null,
        location: null,
      });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Lỗi đọc file Service Account JSON.';
      return res.json({
        connected: false,
        mode: 'error',
        projectId: null,
        clientEmail: null,
        source: null,
        error: message,
      });
    }
  });

  // 0b. Kiểm tra tên các thư mục con hiện có trên Google Drive để tính số thứ tự tiếp theo (bắt đầu từ 1)
  app.get('/api/gcp/drive-next-folder', async (_req, res) => {
    try {
      const sa = loadServiceAccountJson();
      const folderId = (process.env.GDRIVE_FOLDER_ID || '').trim();
      if (!sa || !folderId) {
        return res.json({
          connected: false,
          folderId: null,
          existingCount: 0,
          maxNumber: 0,
          nextNumber: 1,
          sampleFolders: [],
        });
      }

      const auth = new GoogleAuth({
        credentials: sa.credentials,
        scopes: ['https://www.googleapis.com/auth/drive.readonly'],
      });
      const client = await auth.getClient();
      const tokenResp = await client.getAccessToken();
      const accessToken = typeof tokenResp === 'string' ? tokenResp : tokenResp?.token;
      if (!accessToken) {
        throw new Error('Không lấy được OAuth2 token từ Service Account cho Google Drive.');
      }

      const escapedId = folderId.replace(/'/g, "\\'");
      const q = `'${escapedId}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false`;
      const allFolders: Array<{ id: string; name: string }> = [];
      let pageToken = '';

      do {
        const params = new URLSearchParams({
          q,
          fields: 'nextPageToken,files(id,name)',
          pageSize: '200',
          supportsAllDrives: 'true',
          includeItemsFromAllDrives: 'true',
        });
        if (pageToken) params.set('pageToken', pageToken);

        const resp = await fetch(`https://www.googleapis.com/drive/v3/files?${params.toString()}`, {
          headers: { Authorization: `Bearer ${accessToken}` },
        });
        if (!resp.ok) {
          const errText = await resp.text();
          throw new Error(`Google Drive API HTTP ${resp.status}: ${errText.slice(0, 180)}`);
        }
        const data = (await resp.json()) as {
          files?: Array<{ id: string; name: string }>;
          nextPageToken?: string;
        };
        if (Array.isArray(data.files)) {
          allFolders.push(...data.files);
        }
        pageToken = data.nextPageToken || '';
      } while (pageToken);

      const leadingNumRe = /^\s*(\d+)(?:[\s._\-–—]|$)/;
      let maxNumber = 0;
      const numberedFolders: Array<{ num: number; name: string }> = [];

      for (const f of allFolders) {
        const name = String(f.name || '').trim();
        const m = name.match(leadingNumRe);
        if (m) {
          const num = parseInt(m[1], 10);
          if (num > maxNumber) maxNumber = num;
          numberedFolders.push({ num, name });
        }
      }

      numberedFolders.sort((a, b) => b.num - a.num);

      return res.json({
        connected: true,
        folderId,
        existingCount: allFolders.length,
        maxNumber,
        nextNumber: maxNumber + 1,
        sampleFolders: numberedFolders.slice(0, 5).map((x) => x.name),
      });
    } catch (err: unknown) {
      return res.json({
        connected: false,
        folderId: null,
        existingCount: 0,
        maxNumber: 0,
        nextNumber: 1,
        sampleFolders: [],
        error: err instanceof Error ? err.message : 'Không thể kiểm tra thư mục Google Drive.',
      });
    }
  });

  // 1. Tạo kịch bản 5 phút (16 phân cảnh) hoặc test nhanh 45s (4 phân cảnh) chuẩn format video Stickman Whiteboard Explainer
  app.post('/api/studio/generate-script', async (req, res) => {
    let authMode = 'unknown';
    try {
      const {
        topic = 'Nghệ thuật giữ bình tĩnh tuyệt đối khi bị phản bội và công kích sau lưng',
        language = 'vi-VN',
        philosopher = 'Marcus Aurelius',
        durationMode = 'full_5min',
      } = req.body ?? {};

      const { ai, mode } = getGenAIClient();
      authMode = mode;
      const modelChain = mode === 'service_account_json' ? SCRIPT_MODELS_VERTEX : SCRIPT_MODELS_PREVIEW;
      const isVietnamese = String(language).startsWith('vi');
      const isFull5Min = durationMode !== 'quick_45s';
      const targetScenes = isFull5Min ? 24 : 6;
      const targetWordsRange = isFull5Min
        ? isVietnamese
          ? '1200–1360 từ tiếng Việt (mỗi cảnh ngắn gọn khoảng 50–58 từ để đổi ảnh liên tục, tổng thời lượng chuẩn ~5 phút khi chạy tốc độ 1.25x)'
          : '880–980 English words (about 36–42 words per scene for brisk multi-image pacing, ~5 minutes at 1.25x speed)'
        : isVietnamese
          ? '150–190 từ tiếng Việt (mỗi cảnh khoảng 25–32 từ, 6 cảnh chuyển ảnh liên tục trong ~45 giây ở tốc độ 1.25x)'
          : '110–140 English words (about 18–24 words per scene across 6 crisp visual scenes, ~45 seconds at 1.25x speed)';

      const langInstruction = isVietnamese
        ? 'Viết toàn bộ title, chapter_header, scene_label, narration và quote_overlay bằng TIẾNG VIỆT tự nhiên, gần gũi, nhịp nhanh cuốn hút như kênh YouTube tư duy/tâm lý giải thích bằng hình vẽ.'
        : 'Write title, chapter_header, scene_label, narration, and quote_overlay in crisp, engaging explainer ENGLISH.';

      const closingCtaSentence = isVietnamese
        ? 'Hãy bình luận ý kiến của bạn ngay dưới video nhé.'
        : 'Share your thoughts in the comments below.';

      const structureGuide = isFull5Min
        ? [
            'CẤU TRÚC KỊCH BẢN 5 PHÚT NHIỀU HÌNH CHUYỂN LIÊN TỤC (ĐÚNG 24 PHÂN CẢNH — CỨ ~10-12 GIÂY ĐỔI 1 TRANH MỚI):',
            '- Cảnh 1–3 (Hook + Nỗi đau thực tế): Đặt thẳng câu hỏi hoặc nghịch lý đánh trúng tâm lý người xem, gạch bỏ cách làm sai phổ biến (`chapter_header: ""`).',
            '- Cảnh 4–8 (Nguyên lý #1 + Ví dụ + Cách áp dụng): `chapter_header` = "#1 [Tên nguyên lý ngắn gọn]". Tách thành 5 cảnh ngắn, mỗi cảnh 1 ý trực quan rõ ràng.',
            '- Cảnh 9–13 (Nguyên lý #2 + So sánh Sai/Đúng + Cách áp dụng): `chapter_header` = "#2 [Tên nguyên lý ngắn gọn]". Mỗi câu chuyện/ví dụ là 1 hình minh họa riêng biệt.',
            '- Cảnh 14–18 (Nguyên lý #3 + Góc nhìn triết gia + Thực hành): `chapter_header` = "#3 [Tên nguyên lý ngắn gọn]". Chuyển cảnh linh hoạt theo từng ý nói.',
            '- Cảnh 19–22 (Nguyên lý #4 + 3 bước hành động): `chapter_header` = "#4 [Tên nguyên lý ngắn gọn]". Chia nhánh rõ từng bước dễ làm ngay hôm nay.',
            '- Cảnh 23 (Tổng kết Checklist): `chapter_header` = "Tổng kết 4 nguyên lý". Liệt kê nhanh 4 điểm cốt lõi (#1 -> #4).',
            `- Cảnh 24 (Câu chốt & Kêu gọi bình luận): \`chapter_header\` = "${isVietnamese ? 'Chia sẻ suy nghĩ của bạn' : 'Share Your Thoughts'}". BẮT BUỘC cấu trúc 3 nhịp: 1 câu tóm gọn thông điệp + 1 câu hỏi gợi mở hành động + kết thúc ĐÚNG bằng lời kêu gọi bình luận tự nhiên: "${closingCtaSentence}" (Ví dụ chuẩn: "Tóm lại, thành công là kết quả của sự lặp lại. Bạn đã sẵn sàng thức dậy vào ngày mai và giành lấy tự do cho chính cuộc đời mình chưa? Hãy bình luận ý kiến của bạn ngay dưới video nhé.").`,
          ].join('\n')
        : [
            'CẤU TRÚC TEST NHANH 45 GIÂY NHIỀU ẢNH (ĐÚNG 6 PHÂN CẢNH — CỨ ~7 GIÂY ĐỔI 1 TRANH):',
            '- Cảnh 1: Hook đặt vấn đề (`chapter_header: ""`, `layout_type: "stickman_explain"`).',
            '- Cảnh 2: Sai lầm phổ biến cần gạch bỏ (`chapter_header: ""`, `layout_type: "comparison_vs"`).',
            '- Cảnh 3: Nguyên lý #1 cốt lõi (`chapter_header: "#1 ..."`, `layout_type: "cause_effect"`).',
            '- Cảnh 4: Ví dụ đời thường minh họa (`chapter_header: "#1 ..."`, `layout_type: "stickman_explain"`).',
            '- Cảnh 5: Cách áp dụng 3 bước (`chapter_header: "Cách áp dụng ngay"`, `layout_type: "three_branches"`).',
            `- Cảnh 6: Câu chốt & Kêu gọi bình luận (\`chapter_header: "${isVietnamese ? 'Chia sẻ suy nghĩ của bạn' : 'Share Your Thoughts'}"\`, \`layout_type: "summary_list"\`). BẮT BUỘC kết thúc lời thoại \`narration\` bằng câu kêu gọi tương tác: "${closingCtaSentence}".`,
          ].join('\n');

      const prompt = [
        `Chủ đề video: ${topic}`,
        `Triết gia / Tư duy trọng tâm: ${philosopher}`,
        langInstruction,
        `Độ dài bắt buộc: ${targetWordsRange}.`,
        `Số phân cảnh bắt buộc: ĐÚNG ${targetScenes} phân cảnh (scene_id từ 1 đến ${targetScenes}).`,
        structureGuide,
        '',
        'QUY TẮC CHIA NHIỀU ẢNH DÀY THEO TỪNG CỤM Ý (3–4 ẢNH / 1 PHÂN CẢNH = ~72–96 ẢNH CHO 5 PHÚT, CỨ ~3–4 GIÂY ĐỔI 1 ẢNH MỚI):',
        '- Mỗi phân cảnh PHẢI có mảng `visual_beats` gồm ĐÚNG 3 đến 4 phần tử tương ứng với từng cụm ý ngắn trong `narration` của cảnh đó.',
        '- Ví dụ chuẩn: Nếu câu thoại là "Ví dụ, khi bị chê bai, thay vì đau khổ, hãy coi đó là luồng gió thổi qua. Gió không thể làm tổn thương hòn đá tảng là tâm trí vững vàng của bạn." => PHẢI tách thành 4 `visual_beats` nối tiếp nhau:',
        '  1) phrase: "khi bị chê bai" | short_label: "Bị chê bai" | image_prompt: "Stickman looking calm while sharp speech bubbles point at him from the left"',
        '  2) phrase: "thay vì đau khổ" | short_label: "Đừng đau khổ" | image_prompt: "Hunched sad stickman holding head crossed out by a bold accent X"',
        '  3) phrase: "coi đó là luồng gió thổi qua hòn đá tảng" | short_label: "Gió qua đá tảng" | image_prompt: "Swirling wind arrows blowing harmlessly past a giant solid mountain boulder"',
        '  4) phrase: "tâm trí vững vàng của bạn" | short_label: "Tâm trí vững vàng" | image_prompt: "Confident smiling stickman standing tall on top of the solid boulder with a shining mind shield"',
        `- Riêng \`visual_beats\` cuối cùng của phân cảnh cuối cùng: PHẢI minh họa lời kêu gọi bình luận ("${closingCtaSentence}") với nhân vật Stickman thân thiện chỉ xuống biểu tượng khung bình luận / bong bóng trò chuyện.`,
        '- Mỗi `visual_beats[i]` chỉ mô tả DUY NHẤT 1 hình ảnh trọng tâm cực kỳ dễ hiểu (15–28 từ tiếng Anh), KHÔNG vẽ đám đông phức tạp, KHÔNG mô tả bàn tay chi tiết, KHÔNG dùng từ bạo lực/máu me/vũ khí.',
        '- Mỗi `short_label` ngắn 2–4 từ tiếng Việt/Anh sạch (KHÔNG dùng `&`, `<`, `>`).',
        '- Mỗi phân cảnh vẫn có `layout_type` ("stickman_explain" | "comparison_vs" | "cause_effect" | "three_branches" | "chapter_title" | "summary_list"), `chapter_header` (<= 7 từ, không `&`, `<`, `>`, để "" ở phần mở đầu), `scene_label` (2–5 từ), `quote_overlay` (<= 6 từ hoặc ""), `motion_type`, và `image_prompt` tóm tắt cảnh.',
        '- BẮT BUỘC thêm `thumbnail_hook` (3–5 từ cực kỳ thu hút để in cỡ lớn trên Thumbnail YouTube) và `thumbnail_prompt` (tiếng Anh, 15–28 từ mô tả nhân vật Stickman + 1 biểu tượng tâm điểm sạch sẽ cho Thumbnail 16:9).',
      ].join('\n');

      let lastErr: unknown = null;
      for (const modelName of modelChain) {
        try {
          const response = await ai.models.generateContent({
            model: modelName,
            contents: prompt,
            config: {
              systemInstruction:
                'Bạn là biên kịch kiêm đạo diễn storyboard Whiteboard Stickman Explainer nhịp nhanh (mỗi 3–4 giây đổi 1 hình minh họa riêng cho từng cụm từ/ý tưởng, tổng ~72–96 hình cho video 5 phút). Luôn chia nhỏ từng câu thoại thành 3–4 visual_beats trực quan, dễ hiểu trong 1 giây, và luôn kết thúc cảnh cuối bằng câu kêu gọi người xem bình luận ý kiến ngay dưới video.',
              responseMimeType: 'application/json',
              responseSchema: {
                type: Type.OBJECT,
                properties: {
                  title: { type: Type.STRING },
                  core_quote: { type: Type.STRING },
                  thumbnail_hook: { type: Type.STRING },
                  thumbnail_prompt: { type: Type.STRING },
                  scenes: {
                    type: Type.ARRAY,
                    items: {
                      type: Type.OBJECT,
                      properties: {
                        scene_id: { type: Type.INTEGER },
                        chapter_header: { type: Type.STRING },
                        layout_type: { type: Type.STRING },
                        scene_label: { type: Type.STRING },
                        narration: { type: Type.STRING },
                        quote_overlay: { type: Type.STRING },
                        motion_type: { type: Type.STRING },
                        image_prompt: { type: Type.STRING },
                        visual_beats: {
                          type: Type.ARRAY,
                          items: {
                            type: Type.OBJECT,
                            properties: {
                              beat_id: { type: Type.INTEGER },
                              phrase: { type: Type.STRING },
                              short_label: { type: Type.STRING },
                              image_prompt: { type: Type.STRING },
                            },
                            required: ['beat_id', 'phrase', 'short_label', 'image_prompt'],
                          },
                        },
                      },
                      required: [
                        'scene_id',
                        'chapter_header',
                        'layout_type',
                        'scene_label',
                        'narration',
                        'quote_overlay',
                        'motion_type',
                        'image_prompt',
                        'visual_beats',
                      ],
                    },
                  },
                },
                required: ['title', 'core_quote', 'thumbnail_hook', 'thumbnail_prompt', 'scenes'],
              },
            },
          });

          const parsed = JSON.parse((response.text ?? '{}').trim());

          // Đảm bảo cảnh cuối LUÔN có lời kêu gọi bình luận ngay dưới video (tránh AI bỏ sót)
          if (Array.isArray(parsed?.scenes) && parsed.scenes.length > 0) {
            const lastScene = parsed.scenes[parsed.scenes.length - 1];
            const rawNarration = String(lastScene?.narration ?? '').trim();
            const hasCommentCta = /(bình luận|comment|để lại ý kiến|chia sẻ ý kiến)/i.test(
              rawNarration
            );
            if (!hasCommentCta && rawNarration) {
              const needsPunct = !/[.!?…]$/.test(rawNarration);
              lastScene.narration = `${rawNarration}${needsPunct ? '.' : ''} ${closingCtaSentence}`;

              const beats = Array.isArray(lastScene.visual_beats) ? lastScene.visual_beats : [];
              const ctaBeatPrompt =
                'Friendly smiling stickman narrator gesturing toward a glowing comment speech bubble inviting viewers to share their thoughts below';
              const ctaLabel = isVietnamese ? 'Bình luận ngay' : 'Comment Below';

              if (beats.length > 0 && beats.length < 4) {
                beats.push({
                  beat_id: beats.length + 1,
                  phrase: closingCtaSentence,
                  short_label: ctaLabel,
                  image_prompt: ctaBeatPrompt,
                });
                lastScene.visual_beats = beats;
              } else if (beats.length >= 4) {
                const lastBeat = beats[beats.length - 1];
                if (lastBeat && !/(bình luận|comment)/i.test(String(lastBeat.phrase ?? ''))) {
                  lastBeat.phrase = `${String(lastBeat.phrase ?? '').trim()} ${closingCtaSentence}`.trim();
                }
              }
            }
          }

          return res.json({
            ...parsed,
            durationMode: isFull5Min ? 'full_5min' : 'quick_45s',
            modelUsed: mode === 'service_account_json' ? `Vertex AI (${modelName})` : modelName,
            authMode: mode,
          });
        } catch (err) {
          lastErr = err;
        }
      }

      throw lastErr instanceof Error
        ? lastErr
        : new Error('Không thể tạo kịch bản từ Google Cloud Vertex AI.');
    } catch (err: unknown) {
      return res.status(500).json({ error: formatFriendlyApiError(err, authMode) });
    }
  });

  // 2. Tạo giọng đọc WAV 24kHz thật: Ưu tiên Google Cloud TTS qua Service Account JSON, fallback Gemini TTS
  app.post('/api/studio/synthesize-voice', async (req, res) => {
    let authMode = 'unknown';
    try {
      const {
        text,
        language = 'vi-VN',
        voiceName = 'Charon',
        voiceStyle = 'Deep, calm, resonant stoic male narrator, measured documentary pacing',
        preferredModel = 'gemini-3.8-flash-lite-tts',
      } = req.body ?? {};

      if (!text || typeof text !== 'string' || !text.trim()) {
        return res.status(400).json({ error: 'Thiếu nội dung lời thoại để tạo giọng đọc.' });
      }

      const { ai, mode, sa } = getGenAIClient();
      authMode = mode;

      // Khi đang kết nối bằng file Service Account JSON: gọi trực tiếp Google Cloud Text-to-Speech API trước
      if (mode === 'service_account_json' && sa) {
        try {
          const cloudTtsResult = await synthesizeViaGoogleCloudTTS(
            sa,
            text.trim(),
            String(language),
            String(voiceName)
          );
          return res.json({ ...cloudTtsResult, authMode: mode });
        } catch (cloudErr) {
          console.warn('[Cloud TTS fallback -> Vertex Gemini TTS]', cloudErr);
        }
      }

      const chain = TTS_GEMINI_CHAIN_MAP[String(preferredModel)] ?? [
        'gemini-3.8-flash-lite-tts',
        'gemini-3.8-flash-tts',
      ];

      let lastErr: unknown = null;
      for (const modelName of chain) {
        try {
          const response = await ai.models.generateContent({
            model: modelName,
            contents: [
              {
                role: 'user',
                parts: [
                  {
                    text: text.trim(),
                    speechMetadata: {
                      style: String(voiceStyle),
                    },
                  } as Record<string, unknown>,
                ],
              },
            ],
            config: {
              responseModalities: ['AUDIO'],
              speechConfig: {
                voiceConfig: {
                  prebuiltVoiceConfig: {
                    voiceName: String(voiceName),
                  },
                },
              },
            },
          });

          const rawBase64 =
            response.candidates?.[0]?.content?.parts?.[0]?.inlineData?.data;
          if (!rawBase64) {
            throw new Error(`Model ${modelName} không trả về dữ liệu âm thanh.`);
          }

          const audioBuf = Buffer.from(rawBase64, 'base64');
          const wavBase64 = wrapPcm16ToWavBase64(audioBuf, 24000, 1);

          return res.json({
            audioBase64: wavBase64,
            mimeType: 'audio/wav',
            modelUsed: mode === 'service_account_json' ? `Vertex AI (${modelName})` : modelName,
            voiceName: String(voiceName),
            authMode: mode,
          });
        } catch (err) {
          lastErr = err;
        }
      }

      throw lastErr instanceof Error
        ? lastErr
        : new Error('Tất cả model TTS đều không phản hồi.');
    } catch (err: unknown) {
      return res.status(500).json({ error: formatFriendlyApiError(err, authMode) });
    }
  });

  // 3. Tạo hình minh họa trực tiếp từ nội dung phân cảnh:
  //    - Mặc định ("stickman_whiteboard"): Vẽ SVG Whiteboard Stickman Explainer (#F3E8C8, mực đen, mũi tên/dấu X đỏ #D92323, chữ Việt ngắn rõ nét, tách 3 lớp beat-1/beat-2/beat-3 để chạy hoạt ảnh từng nhịp giống video mẫu)
  //    - Chế độ "editorial_sketch": Ưu tiên Vertex AI Imagen khi có Service Account JSON, fallback 2D Editorial SVG sạch
  app.post('/api/studio/generate-image', async (req, res) => {
    let authMode = 'unknown';
    try {
      const {
        narration = '',
        imagePrompt = '',
        sceneLabel = '',
        chapterHeader = '',
        layoutType = 'stickman_explain',
        language = 'vi-VN',
        styleMode = 'stickman_whiteboard',
        bgColor = '#EEF2F7',
        inkColor = '#0F172A',
        accentColor = '#2563EB',
        surfaceFill = '#FFFFFF',
        visualStylePrompt = 'Clean flat minimalist whiteboard stickman explainer illustration on cool ice-gray #EEF2F7 studio background, crisp bold deep navy-black #0F172A ink stickman with tie and clear facial expressions, simple line icons, vivid cobalt blue #2563EB arrows and highlight marks, ultra-clear uncluttered diagram easy to understand in 1 second',
        paperTheme = 'classic_parchment',
        aspectRatio = '16:9',
      } = req.body ?? {};

      const safeBg = /^#[0-9a-fA-F]{6}$/.test(String(bgColor).trim())
        ? String(bgColor).trim().toUpperCase()
        : '#EEF2F7';
      const safeInk = /^#[0-9a-fA-F]{6}$/.test(String(inkColor).trim())
        ? String(inkColor).trim().toUpperCase()
        : '#0F172A';
      const safeAccent = /^#[0-9a-fA-F]{6}$/.test(String(accentColor).trim())
        ? String(accentColor).trim().toUpperCase()
        : '#2563EB';
      const safeSurface = /^#[0-9a-fA-F]{6}$/.test(String(surfaceFill).trim())
        ? String(surfaceFill).trim().toUpperCase()
        : '#FFFFFF';

      const effectivePrompt = String(imagePrompt || narration).trim();
      if (!effectivePrompt) {
        return res.status(400).json({ error: 'Thiếu nội dung phân cảnh để tạo ảnh.' });
      }

      const sa = loadServiceAccountJson();
      const isVertical = aspectRatio === '9:16';
      const vbW = isVertical ? 720 : 1280;
      const vbH = isVertical ? 1280 : 720;

      // Nhánh A: Chế độ ảnh raster editorial / Ken Burns khi người dùng đã kết nối Service Account JSON
      if (styleMode !== 'stickman_whiteboard' && sa) {
        const imagenClient = new GoogleGenAI({
          vertexai: true,
          project: sa.projectId,
          location: process.env.VERTEX_IMAGEN_LOCATION || 'us-central1',
          googleAuthOptions: {
            credentials: sa.credentials,
          },
          httpOptions: {
            headers: { 'User-Agent': 'aistudio-build' },
          },
        });

        const fullPrompt =
          `${effectivePrompt}. ${String(visualStylePrompt).trim()}. ` +
          `Flat 2D editorial vector illustration on solid clean ${safeBg} background, crisp bold ${safeInk} outlines, ` +
          `vivid ${safeAccent} highlights, uncluttered single focal metaphor, strictly NO embedded text, NO letters, NO numbers, NO watermarks, NO distorted hands.`;
        const imagenModels = ['imagen-4.0-fast-generate-001', 'imagen-3.0-fast-generate-002'] as const;

        for (const modelName of imagenModels) {
          try {
            const result = await imagenClient.models.generateImages({
              model: modelName,
              prompt: fullPrompt,
              config: {
                numberOfImages: 1,
                aspectRatio: isVertical ? '9:16' : '16:9',
                outputMimeType: 'image/png',
              },
            });

            const imgBytes = result.generatedImages?.[0]?.image?.imageBytes;
            if (imgBytes) {
              return res.json({
                source: 'vertex_imagen',
                modelUsed: `Vertex AI (${modelName})`,
                imageDataUrl: `data:image/png;base64,${imgBytes}`,
              });
            }
          } catch (err) {
            console.warn(`[Vertex Imagen fallback ${modelName}]`, err);
          }
        }
      }

      const { ai, mode } = getGenAIClient();
      authMode = mode;
      const directorModelChain =
        mode === 'service_account_json' ? SCRIPT_MODELS_VERTEX : ART_DIRECTOR_MODELS_PREVIEW;
      const isVietnamese = String(language).startsWith('vi');
      const isRegenerate = Boolean(req.body?.isRegenerate);

      const headerLine = String(chapterHeader || '').trim().replace(/[&<>]/g, ' ');
      const safeSceneLabel = String(sceneLabel || '').trim().replace(/[&<>]/g, ' ');
      const isParchment = paperTheme !== 'dark_slate';
      const theme =
        styleMode === 'stickman_whiteboard'
          ? {
              bgColor: safeBg,
              inkColor: safeInk,
              accentColor: safeAccent,
              surfaceFill: safeSurface,
            }
          : isParchment
            ? {
                bgColor: '#F7F3E9',
                inkColor: '#1E2430',
                accentColor: '#C89D46',
                surfaceFill: '#FFFFFF',
              }
            : {
                bgColor: '#131A26',
                inkColor: '#F2EDE2',
                accentColor: '#D9B35C',
                surfaceFill: '#1D2738',
              };

      const directorPrompt = [
        'You are an Art Director for a clean, broadcast-grade YouTube Explainer channel.',
        'Pick the SINGLE most expressive visual composition, character pose, facial expression, visual metaphor prop, and overlay effect that instantly illustrates this scene.',
        '',
        `Chapter Header: ${headerLine || '(none)'}`,
        `Scene Label: ${safeSceneLabel}`,
        `Layout Hint: ${String(layoutType || 'stickman_explain')}`,
        `Spoken Narration: ${String(narration || '').slice(0, 320)}`,
        `Visual Idea: ${effectivePrompt}`,
        isRegenerate
          ? `REGENERATE VARIATION: Choose a FRESH alternative composition & metaphor prop different from the most obvious cliché (variation seed: ${Date.now() % 97}).`
          : '',
        '',
        'ALLOWED ENUM VALUES (USE EXACT STRINGS):',
        `- composition: ${STUDIO_COMPOSITIONS.join(' | ')}`,
        `- character_pose: ${STUDIO_POSES.join(' | ')}`,
        `- character_expression: ${STUDIO_EXPRESSIONS.join(' | ')}`,
        `- secondary_pose (used in two_characters_interaction): ${STUDIO_POSES.join(' | ')}`,
        `- secondary_expression: ${STUDIO_EXPRESSIONS.join(' | ')}`,
        `- primary_prop: ${STUDIO_PROPS.join(' | ')}`,
        `- secondary_prop (optional for cause_effect_flow): ${STUDIO_PROPS.join(' | ')}`,
        `- overlay_effect: ${STUDIO_OVERLAYS.join(' | ')}`,
        `- caption: ${isVietnamese ? '2–6 crisp Vietnamese words with proper diacritics summarizing the visual' : '2–6 crisp English words summarizing the visual'}`,
        `- left_badge / right_badge: optional short 2–3 word tag (e.g. "Phản ứng cũ" / "Tâm trí vững").`,
        '- step_items: only when composition is "checklist_steps" — 3 crisp short points (<= 26 chars each).',
      ]
        .filter(Boolean)
        .join('\n');

      let rawBlueprint: Record<string, unknown> | undefined;
      let usedModel = 'Studio Vector Semantic Engine';

      for (const modelName of directorModelChain) {
        try {
          const response = await ai.models.generateContent({
            model: modelName,
            contents: directorPrompt,
            config: {
              ...buildDirectorThinkingConfig(modelName),
              systemInstruction:
                'You are a precision Visual Storyboard Art Director. Return strictly valid JSON matching the schema with exact allowed enum names.',
              responseMimeType: 'application/json',
              responseSchema: {
                type: Type.OBJECT,
                properties: {
                  composition: { type: Type.STRING },
                  character_pose: { type: Type.STRING },
                  character_expression: { type: Type.STRING },
                  secondary_pose: { type: Type.STRING },
                  secondary_expression: { type: Type.STRING },
                  primary_prop: { type: Type.STRING },
                  secondary_prop: { type: Type.STRING },
                  overlay_effect: { type: Type.STRING },
                  caption: { type: Type.STRING },
                  left_badge: { type: Type.STRING },
                  right_badge: { type: Type.STRING },
                  step_items: {
                    type: Type.ARRAY,
                    items: { type: Type.STRING },
                  },
                },
                required: [
                  'composition',
                  'character_pose',
                  'character_expression',
                  'primary_prop',
                  'overlay_effect',
                  'caption',
                ],
              },
            },
          });

          const parsed = JSON.parse((response.text ?? '{}').trim()) as Record<string, unknown>;
          if (parsed && typeof parsed === 'object' && parsed.primary_prop) {
            rawBlueprint = parsed;
            usedModel =
              mode === 'service_account_json'
                ? `Vertex Studio Vector (${modelName})`
                : `Studio Vector Art (${modelName})`;
            break;
          }
        } catch (err) {
          console.warn(
            `[Studio Art Director single retry -> next model] ${modelName}:`,
            err instanceof Error ? err.message : err
          );
        }
      }

      const blueprint = normalizeStudioBlueprint(rawBlueprint, {
        phrase: String(narration || effectivePrompt),
        shortLabel: safeSceneLabel || headerLine,
        imagePrompt: effectivePrompt,
        chapterHeader: headerLine,
        layoutType: String(layoutType || 'stickman_explain'),
      });

      const finalSvg = renderStudioShotSvg({
        blueprint,
        theme,
        vbW,
        vbH,
        includeBeatGroups: true,
      });

      const base64Svg = Buffer.from(finalSvg, 'utf-8').toString('base64');
      return res.json({
        source: styleMode === 'stickman_whiteboard' ? 'ai_stickman_whiteboard' : 'ai_vector_content',
        modelUsed: usedModel,
        imageDataUrl: `data:image/svg+xml;base64,${base64Svg}`,
        svgMarkup: finalSvg,
        themeColors: theme,
      });
    } catch (err: unknown) {
      return res.status(500).json({ error: formatFriendlyApiError(err, authMode) });
    }
  });

  // 3a. Tạo nhanh theo lô 3–4 hình minh họa độc lập chuẩn Studio cho 1 phân cảnh (cứ ~3–4 giây đổi 1 hình khớp từng cụm từ)
  app.post('/api/studio/generate-scene-beats', async (req, res) => {
    let authMode = 'unknown';
    try {
      const {
        chapterHeader = '',
        narration = '',
        visualBeats = [],
        language = 'vi-VN',
        bgColor = '#EEF2F7',
        inkColor = '#0F172A',
        accentColor = '#2563EB',
        surfaceFill = '#FFFFFF',
        aspectRatio = '16:9',
        isRegenerate = false,
      } = req.body ?? {};

      const beatsInput: Array<{
        beat_id?: number;
        phrase?: string;
        short_label?: string;
        image_prompt?: string;
      }> = Array.isArray(visualBeats) ? visualBeats.slice(0, 5) : [];

      if (beatsInput.length === 0) {
        return res.status(400).json({ error: 'Thiếu danh sách visualBeats để tạo chuỗi hình ảnh.' });
      }

      const safeBg = /^#[0-9a-fA-F]{6}$/.test(String(bgColor).trim())
        ? String(bgColor).trim().toUpperCase()
        : '#EEF2F7';
      const safeInk = /^#[0-9a-fA-F]{6}$/.test(String(inkColor).trim())
        ? String(inkColor).trim().toUpperCase()
        : '#0F172A';
      const safeAccent = /^#[0-9a-fA-F]{6}$/.test(String(accentColor).trim())
        ? String(accentColor).trim().toUpperCase()
        : '#2563EB';
      const safeSurface = /^#[0-9a-fA-F]{6}$/.test(String(surfaceFill).trim())
        ? String(surfaceFill).trim().toUpperCase()
        : '#FFFFFF';

      const isVertical = aspectRatio === '9:16';
      const vbW = isVertical ? 720 : 1280;
      const vbH = isVertical ? 1280 : 720;
      const headerLine = String(chapterHeader || '').trim().replace(/[&<>]/g, ' ');
      const isVietnamese = String(language).startsWith('vi');

      const { ai, mode } = getGenAIClient();
      authMode = mode;
      const modelChain =
        mode === 'service_account_json' ? SCRIPT_MODELS_VERTEX : ART_DIRECTOR_MODELS_PREVIEW;

      const beatsSpec = beatsInput
        .map(
          (b, idx) =>
            `Shot #${idx + 1} (beat_id=${b.beat_id ?? idx + 1}):\n` +
            `  - Spoken phrase: "${String(b.phrase || '').replace(/[&<>]/g, ' ')}"\n` +
            `  - Short caption: "${String(b.short_label || '').replace(/[&<>]/g, ' ')}"\n` +
            `  - Visual cue: ${String(b.image_prompt || b.phrase || '')}`
        )
        .join('\n');

      const directorBatchPrompt = [
        `You are the Lead Visual Storyboard Director for a clean Editorial Explainer YouTube channel.`,
        `Direct ${beatsInput.length} COMPLETELY DISTINCT visual shots matching each spoken phrase below.`,
        `Every consecutive shot MUST use a DIFFERENT composition and a DIFFERENT primary_prop so rapid 3-second cuts look dynamic and directly match each clause!`,
        '',
        `Full Scene Narration: ${String(narration || '').slice(0, 320)}`,
        headerLine ? `Chapter Header: ${headerLine}` : '',
        isRegenerate
          ? `REGENERATE REQUEST: Pick a fresh, creative alternative composition & visual metaphor (variation #${Date.now() % 100}).`
          : '',
        '',
        'SHOTS TO DIRECT:',
        beatsSpec,
        '',
        'ALLOWED ENUM VALUES (PICK EXACT STRINGS ONLY):',
        `- composition: ${STUDIO_COMPOSITIONS.join(' | ')}`,
        `- character_pose: ${STUDIO_POSES.join(' | ')}`,
        `- character_expression: ${STUDIO_EXPRESSIONS.join(' | ')}`,
        `- secondary_pose (when composition="two_characters_interaction"): ${STUDIO_POSES.join(' | ')}`,
        `- secondary_expression: ${STUDIO_EXPRESSIONS.join(' | ')}`,
        `- primary_prop: ${STUDIO_PROPS.join(' | ')}`,
        `- secondary_prop (optional for cause_effect_flow): ${STUDIO_PROPS.join(' | ')}`,
        `- overlay_effect: ${STUDIO_OVERLAYS.join(' | ')}`,
        '',
        'EXACT STORYTELLING EXAMPLES:',
        '- "khi bị chê bai" -> composition="two_characters_interaction", secondary_pose="pointing_accuse", secondary_expression="angry", character_pose="standing_calm", character_expression="calm", primary_prop="criticism_arrows", overlay_effect="none"',
        '- "thay vì đau khổ" -> composition="character_left_prop_right", character_pose="slumped_sad", character_expression="sad", primary_prop="storm_cloud", overlay_effect="big_x_crossout"',
        '- "luồng gió thổi qua hòn đá tảng" -> composition="center_metaphor", primary_prop="boulder_wind", overlay_effect="shield_aura"',
        '- "tâm trí vững vàng của bạn" -> composition="character_on_pedestal", character_pose="shield_stance", character_expression="confident", primary_prop="mind_shield", overlay_effect="checkmark_badge"',
        '',
        `Keep every "caption" crisp (2–5 ${isVietnamese ? 'Vietnamese' : 'English'} words matching the short caption).`,
        `Return JSON { "beats": [ ... ] } with EXACTLY ${beatsInput.length} items.`,
      ]
        .filter(Boolean)
        .join('\n');

      const theme = {
        bgColor: safeBg,
        inkColor: safeInk,
        accentColor: safeAccent,
        surfaceFill: safeSurface,
      };

      let directedBeats: Array<Record<string, unknown>> = [];
      let usedModel = 'Studio Vector Semantic Engine';

      for (const modelName of modelChain) {
        try {
          const response = await ai.models.generateContent({
            model: modelName,
            contents: directorBatchPrompt,
            config: {
              ...buildDirectorThinkingConfig(modelName),
              systemInstruction: `You are a precision Visual Storyboard Art Director. Output strictly valid JSON with EXACTLY ${beatsInput.length} diverse, expressive visual shot blueprints using ONLY the allowed enum names.`,
              responseMimeType: 'application/json',
              responseSchema: {
                type: Type.OBJECT,
                properties: {
                  beats: {
                    type: Type.ARRAY,
                    items: {
                      type: Type.OBJECT,
                      properties: {
                        beat_id: { type: Type.INTEGER },
                        composition: { type: Type.STRING },
                        character_pose: { type: Type.STRING },
                        character_expression: { type: Type.STRING },
                        secondary_pose: { type: Type.STRING },
                        secondary_expression: { type: Type.STRING },
                        primary_prop: { type: Type.STRING },
                        secondary_prop: { type: Type.STRING },
                        overlay_effect: { type: Type.STRING },
                        caption: { type: Type.STRING },
                        left_badge: { type: Type.STRING },
                        right_badge: { type: Type.STRING },
                        step_items: {
                          type: Type.ARRAY,
                          items: { type: Type.STRING },
                        },
                      },
                      required: [
                        'beat_id',
                        'composition',
                        'character_pose',
                        'character_expression',
                        'primary_prop',
                        'overlay_effect',
                        'caption',
                      ],
                    },
                  },
                },
                required: ['beats'],
              },
            },
          });

          const parsed = JSON.parse((response.text ?? '{}').trim()) as {
            beats?: Array<Record<string, unknown>>;
          };
          if (Array.isArray(parsed.beats) && parsed.beats.length > 0) {
            directedBeats = parsed.beats;
            usedModel =
              mode === 'service_account_json'
                ? `Vertex Studio Vector (${modelName})`
                : `Studio Vector Art (${modelName})`;
            break;
          }
        } catch (err) {
          console.warn(
            `[Scene Beats Art Director retry -> next model] ${modelName}:`,
            err instanceof Error ? err.message : err
          );
        }
      }

      // Chuẩn hóa & đảm bảo độ đa dạng hình ảnh giữa các ảnh liền kề trong cùng phân cảnh
      const usedCompositions = new Set<string>();
      const usedProps = new Set<string>();

      const results = beatsInput.map((beat, idx) => {
        const beatId = beat.beat_id ?? idx + 1;
        const candidate =
          directedBeats.find((p) => Number(p.beat_id) === beatId) || directedBeats[idx];

        const bp: StudioShotBlueprint = normalizeStudioBlueprint(candidate, {
          phrase: String(beat.phrase || '').trim(),
          shortLabel: String(beat.short_label || '').trim(),
          imagePrompt: String(beat.image_prompt || '').trim(),
          chapterHeader: headerLine,
          beatIndex: idx,
          totalBeats: beatsInput.length,
        });

        // Nếu AI lỡ chọn trùng hệt cả composition lẫn primary_prop của ảnh ngay trước -> tự động xoay bố cục khác
        if (usedCompositions.has(bp.composition) && usedProps.has(bp.primary_prop)) {
          const altComp = STUDIO_COMPOSITIONS.find((c) => !usedCompositions.has(c));
          if (altComp) bp.composition = altComp;
        }
        // Khi người dùng bấm "Vẽ lại" cho 1 ảnh lẻ mà semantic fallback trả lại cấu hình cũ -> xoay góc mới
        if (isRegenerate && beatsInput.length === 1 && !candidate) {
          const shift = Math.floor(Date.now() / 1000) % STUDIO_COMPOSITIONS.length;
          bp.composition = STUDIO_COMPOSITIONS[shift];
        }

        usedCompositions.add(bp.composition);
        usedProps.add(bp.primary_prop);

        const finalSvg = renderStudioShotSvg({
          blueprint: bp,
          theme,
          vbW,
          vbH,
          includeBeatGroups: false,
        });
        const base64Svg = Buffer.from(finalSvg, 'utf-8').toString('base64');
        return {
          beat_id: beatId,
          imageDataUrl: `data:image/svg+xml;base64,${base64Svg}`,
          svgMarkup: finalSvg,
          themeColors: theme,
          modelUsed: candidate ? usedModel : 'Studio Vector Semantic Engine',
        };
      });

      return res.json({
        beats: results,
        modelUsed: usedModel,
        themeColors: theme,
      });
    } catch (err: unknown) {
      return res.status(500).json({ error: formatFriendlyApiError(err, authMode) });
    }
  });

  // 3b. Tạo Thumbnail YouTube 1280x720 tỷ lệ click cao chuẩn Studio (0% lỗi cắt chữ, 0% méo hình)
  app.post('/api/studio/generate-thumbnail', async (req, res) => {
    let authMode = 'unknown';
    try {
      const {
        title = '',
        thumbnailHook = '',
        thumbnailPrompt = '',
        coreQuote = '',
        folderNumber = 1,
        language = 'vi-VN',
        bgColor = '#EEF2F7',
        inkColor = '#0F172A',
        accentColor = '#2563EB',
        surfaceFill = '#FFFFFF',
      } = req.body ?? {};

      const safeBg = /^#[0-9a-fA-F]{6}$/.test(String(bgColor).trim())
        ? String(bgColor).trim().toUpperCase()
        : '#EEF2F7';
      const safeInk = /^#[0-9a-fA-F]{6}$/.test(String(inkColor).trim())
        ? String(inkColor).trim().toUpperCase()
        : '#0F172A';
      const safeAccent = /^#[0-9a-fA-F]{6}$/.test(String(accentColor).trim())
        ? String(accentColor).trim().toUpperCase()
        : '#2563EB';
      const safeSurface = /^#[0-9a-fA-F]{6}$/.test(String(surfaceFill).trim())
        ? String(surfaceFill).trim().toUpperCase()
        : '#FFFFFF';

      const seqNum = Math.max(1, Number(folderNumber) || 1);
      const isVietnamese = String(language).startsWith('vi');
      const mainHook = String(thumbnailHook || title || 'TƯ DUY KHẮC KỶ')
        .trim()
        .slice(0, 65)
        .toUpperCase();
      const subText = String(coreQuote || title || '')
        .trim()
        .slice(0, 85);
      const badgeLabel = isVietnamese
        ? `TẬP #${String(seqNum).padStart(2, '0')}`
        : `EP #${String(seqNum).padStart(2, '0')}`;

      const theme = {
        bgColor: safeBg,
        inkColor: safeInk,
        accentColor: safeAccent,
        surfaceFill: safeSurface,
      };

      const { ai, mode } = getGenAIClient();
      authMode = mode;
      const modelChain =
        mode === 'service_account_json' ? SCRIPT_MODELS_VERTEX : ART_DIRECTOR_MODELS_PREVIEW;

      const inferred = inferSemanticBlueprint({
        phrase: `${title} ${coreQuote}`,
        shortLabel: mainHook,
        imagePrompt: String(thumbnailPrompt || title),
      });

      let thumbBlueprint: StudioThumbnailBlueprint = {
        headline: mainHook,
        subtitle: subText,
        badgeLabel,
        character_pose: inferred.character_pose,
        character_expression: inferred.character_expression,
        primary_prop: inferred.primary_prop,
        overlay_effect:
          inferred.overlay_effect === 'none' ? 'spark_emphasis' : inferred.overlay_effect,
      };
      let usedModel = 'Studio Thumbnail Engine';

      const thumbDirectorPrompt = [
        'Pick the highest-CTR character pose, facial expression, focal visual metaphor prop, and accent overlay for a 1280x720 YouTube Explainer Thumbnail.',
        `Title: ${title}`,
        `Headline: ${mainHook}`,
        `Visual Idea: ${thumbnailPrompt || title}`,
        '',
        `Allowed character_pose: ${STUDIO_POSES.join(' | ')}`,
        `Allowed character_expression: ${STUDIO_EXPRESSIONS.join(' | ')}`,
        `Allowed primary_prop: ${STUDIO_PROPS.join(' | ')}`,
        `Allowed overlay_effect: ${STUDIO_OVERLAYS.join(' | ')}`,
      ].join('\n');

      for (const modelName of modelChain) {
        try {
          const response = await ai.models.generateContent({
            model: modelName,
            contents: thumbDirectorPrompt,
            config: {
              ...buildDirectorThinkingConfig(modelName),
              systemInstruction:
                'Return strictly valid JSON selecting exact enum names for a high-CTR YouTube thumbnail.',
              responseMimeType: 'application/json',
              responseSchema: {
                type: Type.OBJECT,
                properties: {
                  character_pose: { type: Type.STRING },
                  character_expression: { type: Type.STRING },
                  primary_prop: { type: Type.STRING },
                  overlay_effect: { type: Type.STRING },
                },
                required: [
                  'character_pose',
                  'character_expression',
                  'primary_prop',
                  'overlay_effect',
                ],
              },
            },
          });

          const parsed = JSON.parse((response.text ?? '{}').trim()) as Record<string, unknown>;
          const normalized = normalizeStudioBlueprint(parsed, {
            phrase: String(title),
            shortLabel: mainHook,
            imagePrompt: String(thumbnailPrompt || title),
          });
          thumbBlueprint = {
            headline: mainHook,
            subtitle: subText,
            badgeLabel,
            character_pose: normalized.character_pose,
            character_expression: normalized.character_expression,
            primary_prop: normalized.primary_prop,
            overlay_effect: normalized.overlay_effect,
          };
          usedModel =
            mode === 'service_account_json'
              ? `Vertex Studio Thumbnail (${modelName})`
              : `Studio Thumbnail Art (${modelName})`;
          break;
        } catch (err) {
          console.warn(
            `[Thumbnail Art Director retry -> next model] ${modelName}:`,
            err instanceof Error ? err.message : err
          );
        }
      }

      const thumbSvg = renderStudioThumbnailSvg({
        blueprint: thumbBlueprint,
        theme,
      });
      const base64Svg = Buffer.from(thumbSvg, 'utf-8').toString('base64');
      return res.json({
        source: 'ai_youtube_thumbnail',
        modelUsed: usedModel,
        imageDataUrl: `data:image/svg+xml;base64,${base64Svg}`,
        svgMarkup: thumbSvg,
        themeColors: theme,
      });
    } catch (err: unknown) {
      return res.status(500).json({ error: formatFriendlyApiError(err, authMode) });
    }
  });

  // 4. Chuyển đổi luồng ghi hình trình duyệt (.webm) sang tệp MP4 chuẩn (H.264 + AAC)
  //    và tự động tăng tốc video + giọng đọc lên tốc độ yêu cầu (mặc định 1.25x, giữ nguyên cao độ giọng tự nhiên bằng atempo)
  app.post(
    '/api/studio/convert-mp4',
    express.raw({ type: '*/*', limit: '250mb' }),
    async (req, res) => {
      const id = crypto.randomUUID();
      const inputPath = path.join(os.tmpdir(), `studio-in-${id}.webm`);
      const outputPath = path.join(os.tmpdir(), `studio-out-${id}.mp4`);

      try {
        if (!Buffer.isBuffer(req.body) || req.body.length < 100) {
          return res.status(400).json({ error: 'Dữ liệu video gửi lên không hợp lệ.' });
        }

        const rawSpeed = Number(req.query.speed ?? 1.25);
        const playbackSpeed = Number.isFinite(rawSpeed)
          ? Math.max(0.75, Math.min(2.0, rawSpeed))
          : 1.25;

        await fs.promises.writeFile(inputPath, req.body);

        const ffmpegArgs: string[] = ['-y', '-i', inputPath];

        if (Math.abs(playbackSpeed - 1.0) > 0.01) {
          ffmpegArgs.push(
            '-vf',
            `setpts=PTS/${playbackSpeed.toFixed(4)}`,
            '-af',
            `atempo=${playbackSpeed.toFixed(4)}`
          );
        }

        ffmpegArgs.push(
          '-c:v',
          'libx264',
          '-preset',
          'veryfast',
          '-crf',
          '22',
          '-pix_fmt',
          'yuv420p',
          '-r',
          '30',
          '-c:a',
          'aac',
          '-b:a',
          '128k',
          '-movflags',
          '+faststart',
          outputPath
        );

        await execFileAsync('ffmpeg', ffmpegArgs, { maxBuffer: 20 * 1024 * 1024 });

        const mp4Buffer = await fs.promises.readFile(outputPath);
        res.setHeader('Content-Type', 'video/mp4');
        res.setHeader('Content-Length', String(mp4Buffer.length));
        return res.send(mp4Buffer);
      } catch (err: unknown) {
        const message =
          err instanceof Error ? err.message : 'Lỗi FFmpeg khi đóng gói tệp MP4.';
        return res.status(500).json({ error: message });
      } finally {
        await fs.promises.unlink(inputPath).catch(() => {});
        await fs.promises.unlink(outputPath).catch(() => {});
      }
    }
  );

  if (!IS_PROD) {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.resolve(__dirname, 'dist');
    app.use(express.static(distPath));
    app.get('*', (_req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`Stoic Pipeline Studio server listening on http://0.0.0.0:${PORT}`);
  });
}

startServer();
