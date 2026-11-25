import { useState } from 'react';
import type { PipelineConfig } from '../types/pipeline';

interface FallbackSectionProps {
  config: PipelineConfig;
}

type ScenarioId = 'transient_429' | 'tts_fallback' | 'daily_quota' | 'imagen_fallback';

const SCENARIO_TRACES: Record<
  ScenarioId,
  { label: string; trigger: string; steps: { time: string; level: string; message: string }[] }
> = {
  transient_429: {
    label: 'HTTP 429/503 LLM',
    trigger: 'ResourceExhausted (Quá tải tốc độ yêu cầu theo phút trên LLM)',
    steps: [
      {
        time: '00:00.0',
        level: 'WARN',
        message: "[RETRY BACKOFF] Model='gemini-3.1-pro-preview' gặp lỗi HTTP 429 (lần 1/4). Chờ 11.42s...",
      },
      {
        time: '00:11.4',
        level: 'WARN',
        message: "[RETRY BACKOFF] Model='gemini-3.1-pro-preview' gặp lỗi HTTP 503 (lần 2/4). Chờ 22.18s...",
      },
      {
        time: '00:33.6',
        level: 'WARN',
        message: "[RETRY BACKOFF] Model='gemini-3.1-pro-preview' gặp lỗi HTTP 429 (lần 3/4). Chờ 41.85s...",
      },
      {
        time: '01:15.5',
        level: 'WARN',
        message: "[MODEL DOWNGRADE] Tự động hạ cấp: 'gemini-3.1-pro-preview' ---> 'gemini-3.8-flash'",
      },
      {
        time: '01:17.9',
        level: 'INFO',
        message: "[LLM OK] Task='script_gen_v2_try0' | Model='gemini-3.8-flash' (location='global')",
      },
    ],
  },
  tts_fallback: {
    label: 'Hạ cấp Giọng đọc TTS',
    trigger: 'Gemini Native TTS quá tải -> tự động hạ cấp sang Lite TTS hoặc Cloud TTS',
    steps: [
      {
        time: '00:00.0',
        level: 'WARN',
        message: "[RETRY BACKOFF] Model='gemini-3.8-flash-tts' gặp HTTP 429 (lần 1/4). Chờ 10.65s...",
      },
      {
        time: '01:13.8',
        level: 'WARN',
        message: "[MODEL DOWNGRADE] Task='tts_scene_04' | 'gemini-3.8-flash-tts' ---> 'gemini-3.8-flash-lite-tts'",
      },
      {
        time: '01:15.2',
        level: 'INFO',
        message: "[GEMINI TTS OK] Model='gemini-3.8-flash-lite-tts' | Voice='Charon' | Saved=scene_04.wav (17.42s)",
      },
      {
        time: '01:15.2',
        level: 'INFO',
        message: "[FAILSAFE READY] Nếu cả 2 model Gemini TTS hết quota, tts_generator.py tự chuyển sang Cloud TTS (Studio/Chirp3-HD/Neural2).",
      },
    ],
  },
  daily_quota: {
    label: 'Hết Quota ngày / 404',
    trigger: 'PER_DAY quota exhausted hoặc MODEL_NOT_FOUND',
    steps: [
      {
        time: '00:00.0',
        level: 'WARN',
        message: "[AUTO-FALLBACK] Model='gemini-3.1-pro-preview' không khả dụng/hết quota ngày (HTTP 404). Chuyển ngay không cần chờ backoff.",
      },
      {
        time: '00:00.1',
        level: 'WARN',
        message: "[MODEL DOWNGRADE] Tự động hạ cấp: 'gemini-3.1-pro-preview' ---> 'gemini-3.8-flash'",
      },
      {
        time: '00:02.4',
        level: 'INFO',
        message: "[LLM OK] Task='ai_critic_review' | Model='gemini-3.8-flash' (location='global')",
      },
    ],
  },
  imagen_fallback: {
    label: 'Hạ cấp Imagen 2D',
    trigger: 'Imagen 4 Fast gặp giới hạn quota trên us-central1',
    steps: [
      {
        time: '00:00.0',
        level: 'WARN',
        message: "[RETRY BACKOFF] Model='imagen-4.0-fast-generate-001' gặp HTTP 429 (lần 1/4). Chờ 10.95s...",
      },
      {
        time: '01:14.2',
        level: 'WARN',
        message: "[MODEL DOWNGRADE] Tự động hạ cấp: 'imagen-4.0-fast-generate-001' ---> 'imagen-3.0-fast-generate-002'",
      },
      {
        time: '01:17.8',
        level: 'INFO',
        message: "[IMAGEN OK] Model='imagen-3.0-fast-generate-002' | Seed=184920114 | Ratio=16:9",
      },
    ],
  },
};

export function FallbackSection({ config }: FallbackSectionProps) {
  const [scenario, setScenario] = useState<ScenarioId>('tts_fallback');
  const activeTrace = SCENARIO_TRACES[scenario];

  const dailyScenes = config.dailyVideoCount * 18;
  const monthlyVideos = config.dailyVideoCount * 30;
  const monthlyImages = dailyScenes * 30;

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="space-y-1.5 pb-6 border-b border-[#1E2738]">
        <h1 className="text-2xl font-semibold text-[#F1F5F9]">
          Hệ thống Model đầy đủ, Auto-Fallback &amp; Tối ưu chi phí
        </h1>
        <p className="text-sm text-[#94A3B8] max-w-3xl">
          Bao gồm đầy đủ chuỗi model cho <strong>Kịch bản &amp; Vision</strong>,{' '}
          <strong>Giọng đọc AI 2 tầng (Gemini Native TTS + Cloud TTS)</strong>,{' '}
          <strong>Ảnh 2D Imagen</strong>, <strong>Embedding chống trùng</strong> và{' '}
          <strong>Nhạc nền Lyria</strong>, tất cả đều có Exponential Backoff + Jitter (10s → 20s → 40s).
        </p>
      </div>

      {/* Priority Chains Grid (4 Cards) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-[#111722] border border-[#1E2738] rounded-lg p-6 space-y-4">
          <div className="flex items-baseline justify-between border-b border-[#1E2738] pb-3">
            <h2 className="text-sm font-semibold text-[#F1F5F9]">
              1. Chuỗi LLM &amp; Gemini Vision QA
            </h2>
            <span className="text-xs font-mono text-[#C8A252]">location=&quot;global&quot;</span>
          </div>
          <ol className="space-y-2.5 text-sm">
            {config.llmFallbackModels.map((model, idx) => (
              <li key={model} className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-[#E2E8F0]">
                  {idx + 1}. {model}
                </span>
                <span className="text-[11px] text-[#7C8DA6]">
                  {idx === 0 ? 'Ưu tiên chính' : `Hạ cấp #${idx}`}
                </span>
              </li>
            ))}
          </ol>
        </div>

        <div className="bg-[#111722] border border-[#1E2738] rounded-lg p-6 space-y-4">
          <div className="flex items-baseline justify-between border-b border-[#1E2738] pb-3">
            <h2 className="text-sm font-semibold text-[#F1F5F9]">
              2. Chuỗi Tạo Giọng đọc AI (2 tầng)
            </h2>
            <span className="text-xs font-mono text-[#C8A252]">
              Voice: {config.ttsVoicePersona}
            </span>
          </div>
          <ol className="space-y-2.5 text-sm">
            {config.ttsFallbackModels.map((model, idx) => (
              <li key={model} className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-[#E2E8F0]">
                  {idx + 1}. {model}
                </span>
                <span className="text-[11px] text-[#7C8DA6]">
                  {idx === 0 ? 'Tầng 1 · Voice Design WAV 24kHz' : 'Tầng 1 · Siêu nhanh tiết kiệm'}
                </span>
              </li>
            ))}
            <li className="flex items-center justify-between gap-2 pt-1.5 border-t border-[#1A2232]">
              <span className="font-mono text-xs text-[#CBD5E1]">
                3. Cloud TTS (Studio / Chirp3-HD / Neural2)
              </span>
              <span className="text-[11px] text-[#C8A252]">Tầng 2 · Dự phòng</span>
            </li>
          </ol>
        </div>

        <div className="bg-[#111722] border border-[#1E2738] rounded-lg p-6 space-y-4">
          <div className="flex items-baseline justify-between border-b border-[#1E2738] pb-3">
            <h2 className="text-sm font-semibold text-[#F1F5F9]">
              3. Chuỗi Tạo ảnh 2D (Không dùng Veo)
            </h2>
            <span className="text-xs font-mono text-[#C8A252]">us-central1</span>
          </div>
          <ol className="space-y-2.5 text-sm">
            {config.imagenFallbackModels.map((model, idx) => (
              <li key={model} className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-[#E2E8F0]">
                  {idx + 1}. {model}
                </span>
                <span className="text-[11px] text-[#7C8DA6]">
                  {idx === 0 ? 'Imagen 4 Fast (~$0.02/ảnh)' : 'Dự phòng ổn định'}
                </span>
              </li>
            ))}
          </ol>
          <p className="text-xs text-[#8B9BB4] pt-2 border-t border-[#1A2232]">
            Mỗi phân cảnh truyền <code className="text-[#CBD5E1]">seed</code> ngẫu nhiên riêng để không lặp bố cục.
          </p>
        </div>

        <div className="bg-[#111722] border border-[#1E2738] rounded-lg p-6 space-y-4">
          <div className="flex items-baseline justify-between border-b border-[#1E2738] pb-3">
            <h2 className="text-sm font-semibold text-[#F1F5F9]">
              4. Embedding Chống trùng &amp; Nhạc nền BGM
            </h2>
            <span className="text-xs font-mono text-[#C8A252]">10s → 20s → 40s</span>
          </div>
          <ol className="space-y-2.5 text-sm">
            {config.embeddingFallbackModels.map((model, idx) => (
              <li key={model} className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-[#E2E8F0]">
                  {idx + 1}. {model}
                </span>
                <span className="text-[11px] text-[#7C8DA6]">
                  {idx === 0 ? 'Embedding chính' : 'Embedding dự phòng'}
                </span>
              </li>
            ))}
            <li className="flex items-center justify-between gap-2 pt-1.5 border-t border-[#1A2232]">
              <span className="font-mono text-xs text-[#CBD5E1]">
                BGM: assets/bgm/ ({config.musicFallbackModels.join(' / ')})
              </span>
              <span className="text-[11px] text-[#7C8DA6]">Tùy chọn</span>
            </li>
          </ol>
        </div>
      </div>

      {/* Interactive Fault-Handling Trace Inspector */}
      <section className="bg-[#111722] border border-[#1E2738] rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-[#1E2738] flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold text-[#F1F5F9]">
              Mô phỏng nhật ký xử lý lỗi &amp; hạ cấp tự động
            </h2>
            <p className="text-xs text-[#8B9BB4] mt-0.5">{activeTrace.trigger}</p>
          </div>

          <div className="flex flex-wrap gap-1.5 p-1 bg-[#0B0F17] border border-[#1E2738] rounded-md">
            {(Object.keys(SCENARIO_TRACES) as ScenarioId[]).map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => setScenario(id)}
                className={`px-3 py-1.5 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                  scenario === id
                    ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                    : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                }`}
              >
                {SCENARIO_TRACES[id].label}
              </button>
            ))}
          </div>
        </div>

        <div className="p-5 bg-[#0D121B] font-mono text-xs space-y-2.5 overflow-x-auto">
          {activeTrace.steps.map((line, i) => (
            <div key={i} className="flex items-start gap-4 leading-relaxed">
              <span className="text-[#64748B] tabular-nums shrink-0">+{line.time}s</span>
              <span
                className={`shrink-0 font-semibold ${
                  line.level === 'WARN' ? 'text-[#FBBF24]' : 'text-[#4ADE80]'
                }`}
              >
                {line.level}
              </span>
              <span className="text-[#CBD5E1]">{line.message}</span>
            </div>
          ))}
        </div>
      </section>

      {/* Cost Optimization Breakdown */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-[#F1F5F9]">
          Phân tích tối ưu chi phí vận hành ({monthlyVideos} video / tháng)
        </h2>

        <div className="bg-[#111722] border border-[#1E2738] rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-[#1E2738] text-xs font-medium text-[#8B9BB4] bg-[#0E131D]">
                  <th className="py-3 px-5">Thành phần</th>
                  <th className="py-3 px-5">Lưu lượng ước tính / tháng</th>
                  <th className="py-3 px-5">Kỹ thuật tiết kiệm áp dụng</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1A2232] text-sm">
                <tr>
                  <td className="py-3.5 px-5 font-medium text-[#E2E8F0]">GitHub Actions (Ubuntu)</td>
                  <td className="py-3.5 px-5 font-mono tabular-nums text-[#C8A252]">
                    ~{config.dailyVideoCount * 230} phút / 2.000 phút free
                  </td>
                  <td className="py-3.5 px-5 text-[#94A3B8]">
                    FFmpeg <code className="text-[#CBD5E1]">-preset ultrafast -tune stillimage -r 24</code> + Matrix song song 5 worker.
                  </td>
                </tr>
                <tr>
                  <td className="py-3.5 px-5 font-medium text-[#E2E8F0]">Giọng đọc AI (TTS 2 tầng)</td>
                  <td className="py-3.5 px-5 font-mono tabular-nums text-[#C8A252]">
                    ~{Math.round((monthlyVideos * 5500) / 1000).toLocaleString('vi-VN')}k ký tự (~750 phút audio)
                  </td>
                  <td className="py-3.5 px-5 text-[#94A3B8]">
                    Ưu tiên Gemini Native TTS (<code className="text-[#CBD5E1]">gemini-3.8-flash-tts</code> / <code className="text-[#CBD5E1]">flash-lite-tts</code>), tự động hạ cấp sang 1M ký tự free/tháng của Cloud TTS Neural2.
                  </td>
                </tr>
                <tr>
                  <td className="py-3.5 px-5 font-medium text-[#E2E8F0]">Vertex AI Imagen 2D</td>
                  <td className="py-3.5 px-5 font-mono tabular-nums text-[#C8A252]">
                    ~{monthlyImages.toLocaleString('vi-VN')} ảnh tĩnh (~18 ảnh/video)
                  </td>
                  <td className="py-3.5 px-5 text-[#94A3B8]">
                    Dùng Imagen 4 Fast (~$0.02/ảnh) thay vì Veo video AI, cắt giảm &gt;95% chi phí tạo hình.
                  </td>
                </tr>
                <tr>
                  <td className="py-3.5 px-5 font-medium text-[#E2E8F0]">Gemini Vision QA</td>
                  <td className="py-3.5 px-5 font-mono tabular-nums text-[#C8A252]">
                    {monthlyVideos} ảnh lưới Contact Sheet
                  </td>
                  <td className="py-3.5 px-5 text-[#94A3B8]">
                    Nén 20 frame (1 frame/15s) thành 1 tấm JPEG duy nhất thay vì gửi file MP4 5 phút.
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  );
}
