import { useEffect, useRef, useState } from 'react';
import { Code2, RotateCcw } from 'lucide-react';
import {
  DEFAULT_PIPELINE_CONFIG,
  VISUAL_STYLE_PRESETS,
  VOICE_PERSONA_OPTIONS,
} from '../data/projectFiles';
import {
  buildCustomWhiteboardTheme,
  resolveWhiteboardTheme,
  rethemeStickmanSvg,
  WHITEBOARD_THEME_PRESETS,
  type WhiteboardTheme,
} from '../data/whiteboardThemes';
import type {
  AspectRatioOption,
  ContentLanguage,
  CronTimezone,
  GeminiVoicePersona,
  NavSectionId,
  PenSketchPaperTheme,
  PipelineConfig,
  TTSProviderOption,
  VideoVisualMode,
} from '../types/pipeline';
import {
  preparePenSketchAsset,
  renderPenSketchFrame,
  type PenSketchAsset,
} from '../utils/penSketchCanvas';
import {
  prepareStickmanBeatAsset,
  renderStickmanBeatFrame,
  SAMPLE_STICKMAN_EXPLAINER_SVG,
} from '../utils/stickmanBeatRenderer';

interface ConfigSectionProps {
  config: PipelineConfig;
  onChange: (next: PipelineConfig) => void;
  onNavigate: (section: NavSectionId) => void;
}

const LANDSCAPE_IMG = '/src/assets/images/stoic_preview_landscape_1795344788817.jpg';
const VERTICAL_IMG = '/src/assets/images/stoic_preview_vertical_1795344788433.jpg';

export function ConfigSection({ config, onChange, onNavigate }: ConfigSectionProps) {
  const isVertical = config.aspectRatio === '9:16';
  const previewCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const [replayNonce, setReplayNonce] = useState(0);
  const [previewPhase, setPreviewPhase] = useState('Bút đang vẽ nét phác họa...');

  const sampleQuote =
    config.language === 'vi-VN'
      ? '“Bạn có quyền kiểm soát tâm trí mình — không phải những biến cố bên ngoài.”'
      : '“You have power over your mind — not outside events.”';
  const sampleAttribution =
    config.language === 'vi-VN'
      ? 'Marcus Aurelius · Suy tưởng · Cảnh 04 / 18'
      : 'Marcus Aurelius · Meditations · Scene 04 / 18';

  const setLanguage = (language: ContentLanguage) => onChange({ ...config, language });
  const setAspectRatio = (aspectRatio: AspectRatioOption) => onChange({ ...config, aspectRatio });
  const setCronTimezone = (cronTimezone: CronTimezone) => onChange({ ...config, cronTimezone });

  const activeTheme: WhiteboardTheme = resolveWhiteboardTheme(
    config.whiteboardThemeId,
    config.whiteboardBgColor,
    config.whiteboardAccentColor
  );

  const applyConfigTheme = (nextTheme: WhiteboardTheme) => {
    onChange({
      ...config,
      whiteboardThemeId: nextTheme.id,
      whiteboardBgColor: nextTheme.bgColor,
      whiteboardInkColor: nextTheme.inkColor,
      whiteboardAccentColor: nextTheme.accentColor,
      visualStylePrompt: `Clean flat minimalist stickman explainer illustration on ${nextTheme.promptDescription}, uncluttered high-contrast diagram easy to understand in 1 second, no dark muddy shadows, no watermark`,
    });
  };

  useEffect(() => {
    if (
      config.videoVisualMode !== 'pen_sketch' &&
      config.videoVisualMode !== 'stickman_whiteboard'
    ) {
      return;
    }
    let cancelled = false;
    let rafId = 0;

    const width = isVertical ? 360 : 640;
    const height = isVertical ? 640 : 360;

    if (config.videoVisualMode === 'stickman_whiteboard') {
      const themedSvg = rethemeStickmanSvg(SAMPLE_STICKMAN_EXPLAINER_SVG, activeTheme);
      prepareStickmanBeatAsset(themedSvg, '', width, height).then((asset) => {
        if (cancelled) return;
        const canvas = previewCanvasRef.current;
        if (!canvas) return;
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const cycleMs = 6800;
        const startTime = performance.now();
        let lastLabel = '';

        const tick = (now: number) => {
          if (cancelled) return;
          const progress = ((now - startTime) % cycleMs) / cycleMs;
          renderStickmanBeatFrame(ctx, asset, progress, activeTheme.bgColor);
          ctx.fillStyle = activeTheme.isDark
            ? 'rgba(255, 255, 255, 0.14)'
            : 'rgba(15, 23, 42, 0.12)';
          ctx.fillRect(0, height - 4, width, 4);
          ctx.fillStyle = activeTheme.accentColor;
          ctx.fillRect(0, height - 4, width * progress, 4);

          const nextLabel =
            progress < 0.30
              ? `Nhịp 1: Hiện Stickman trên nền ${activeTheme.bgColor} (mượt, không bút)...`
              : progress < 0.62
                ? `Nhịp 2: Hiện dấu X & mũi tên nhấn (${activeTheme.accentColor})...`
                : 'Nhịp 3: Hiện giải pháp & từ khóa chốt rõ nét';
          if (nextLabel !== lastLabel) {
            lastLabel = nextLabel;
            setPreviewPhase(nextLabel);
          }
          rafId = requestAnimationFrame(tick);
        };
        rafId = requestAnimationFrame(tick);
      });

      return () => {
        cancelled = true;
        cancelAnimationFrame(rafId);
      };
    }

    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.src = isVertical ? VERTICAL_IMG : LANDSCAPE_IMG;

    img.onload = () => {
      if (cancelled) return;
      const canvas = previewCanvasRef.current;
      if (!canvas) return;
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      const asset: PenSketchAsset = preparePenSketchAsset(
        img,
        width,
        height,
        config.penSketchPaperTheme
      );
      const cycleMs = 7800;
      const startTime = performance.now();
      let lastLabel = '';

      const tick = (now: number) => {
        if (cancelled) return;
        const progress = ((now - startTime) % cycleMs) / cycleMs;
        renderPenSketchFrame(ctx, asset, progress);

        const nextLabel =
          progress < 0.66
            ? 'Giai đoạn 1: Bút mực chuyển động phác họa đường nét...'
            : progress < 0.86
              ? 'Giai đoạn 2: Đổ bóng màu hiện hình hoàn chỉnh...'
              : 'Giai đoạn 3: Giữ khung hình sắc nét theo lời thoại';
        if (nextLabel !== lastLabel) {
          lastLabel = nextLabel;
          setPreviewPhase(nextLabel);
        }
        rafId = requestAnimationFrame(tick);
      };
      rafId = requestAnimationFrame(tick);
    };

    return () => {
      cancelled = true;
      cancelAnimationFrame(rafId);
    };
  }, [
    config.videoVisualMode,
    config.penSketchPaperTheme,
    activeTheme.id,
    activeTheme.bgColor,
    activeTheme.accentColor,
    isVertical,
    replayNonce,
  ]);

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 pb-6 border-b border-[#1E2738]">
        <div className="space-y-1.5">
          <h1 className="text-2xl font-semibold text-[#F1F5F9]">
            Cấu hình cá nhân trước khi chạy
          </h1>
          <p className="text-sm text-[#94A3B8]">
            Mọi thay đổi tại đây được đồng bộ trực tiếp vào tệp{' '}
            <code className="text-[#E2E8F0]">config.py</code> và{' '}
            <code className="text-[#E2E8F0]">daily_stoic_pipeline.yml</code> khi bạn xem mã hoặc tải ZIP.
          </p>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          <button
            type="button"
            onClick={() => onChange(DEFAULT_PIPELINE_CONFIG)}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium text-[#94A3B8] hover:text-[#E2E8F0] bg-[#111722] border border-[#222B3B] rounded-md transition-colors whitespace-nowrap cursor-pointer"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Khôi phục mặc định
          </button>
          <button
            type="button"
            onClick={() => onNavigate('code')}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium text-[#E2E8F0] bg-[#172030] border border-[#2A374E] hover:border-[#3D5070] rounded-md transition-colors whitespace-nowrap cursor-pointer"
          >
            <Code2 className="w-3.5 h-3.5 text-[#C8A252]" />
            Xem config.py đã sinh
          </button>
        </div>
      </div>

      {/* Main 2-column configuration + live 2D visual framing preview */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-8 items-start">
        {/* Left: Form Controls */}
        <div className="xl:col-span-7 bg-[#111722] border border-[#1E2738] rounded-lg divide-y divide-[#1A2232]">
          {/* Row 1: Language & Aspect Ratio */}
          <div className="p-6 grid grid-cols-1 sm:grid-cols-2 gap-6">
            <div className="space-y-2.5">
              <label className="block text-sm font-medium text-[#E2E8F0]">
                Ngôn ngữ nội dung video
              </label>
              <div className="grid grid-cols-2 gap-1.5 p-1 bg-[#0B0F17] border border-[#1E2738] rounded-md">
                <button
                  type="button"
                  onClick={() => setLanguage('vi-VN')}
                  className={`py-2 px-3 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                    config.language === 'vi-VN'
                      ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                      : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                  }`}
                >
                  Tiếng Việt (vi-VN)
                </button>
                <button
                  type="button"
                  onClick={() => setLanguage('en-US')}
                  className={`py-2 px-3 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                    config.language === 'en-US'
                      ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                      : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                  }`}
                >
                  Tiếng Anh (en-US)
                </button>
              </div>
              <p className="text-xs text-[#7C8DA6] font-mono tabular-nums">
                {config.language === 'vi-VN'
                  ? 'Mục tiêu ~1.050–1.180 từ · Giọng vi-VN-Neural2-D'
                  : 'Target ~750–820 words · Voice en-US-Studio-Q / Chirp3-HD'}
              </p>
            </div>

            <div className="space-y-2.5">
              <label className="block text-sm font-medium text-[#E2E8F0]">
                Tỷ lệ khung hình video
              </label>
              <div className="grid grid-cols-2 gap-1.5 p-1 bg-[#0B0F17] border border-[#1E2738] rounded-md">
                <button
                  type="button"
                  onClick={() => setAspectRatio('16:9')}
                  className={`py-2 px-3 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                    config.aspectRatio === '16:9'
                      ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                      : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                  }`}
                >
                  16:9 Ngang (1080p)
                </button>
                <button
                  type="button"
                  onClick={() => setAspectRatio('9:16')}
                  className={`py-2 px-3 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                    config.aspectRatio === '9:16'
                      ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                      : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                  }`}
                >
                  9:16 Dọc (Shorts)
                </button>
              </div>
              <p className="text-xs text-[#7C8DA6] font-mono tabular-nums">
                {isVertical ? '1080 × 1920 px · 24 fps' : '1920 × 1080 px · 24 fps'}
              </p>
            </div>
          </div>

          {/* Row 2: Channel Topic */}
          <div className="p-6 space-y-2.5">
            <label htmlFor="channel-topic" className="block text-sm font-medium text-[#E2E8F0]">
              Chủ đề kênh (CHANNEL_TOPIC)
            </label>
            <input
              id="channel-topic"
              type="text"
              value={config.channelTopic}
              onChange={(e) => onChange({ ...config, channelTopic: e.target.value })}
              className="w-full px-3.5 py-2.5 text-sm text-[#F1F5F9] bg-[#0B0F17] border border-[#243045] rounded-md focus:outline-none focus:border-[#C8A252] transition-colors"
            />
          </div>

          {/* Row 3: Fixed 2D Visual Style Prompt */}
          <div className="p-6 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <label htmlFor="visual-style" className="text-sm font-medium text-[#E2E8F0]">
                Phong cách hình ảnh 2D cố định (VISUAL_STYLE_PROMPT)
              </label>
              <span className="text-xs text-[#7C8DA6]">
                Nhúng tự động vào mọi lệnh gọi Imagen
              </span>
            </div>

            <div className="flex flex-wrap gap-2">
              {VISUAL_STYLE_PRESETS.map((preset) => {
                const active = config.visualStylePrompt === preset.prompt;
                return (
                  <button
                    key={preset.id}
                    type="button"
                    onClick={() => onChange({ ...config, visualStylePrompt: preset.prompt })}
                    className={`px-3 py-1.5 text-xs font-medium rounded-md border transition-colors whitespace-nowrap cursor-pointer ${
                      active
                        ? 'bg-[#1D2536] border-[#C8A252] text-[#F1F5F9]'
                        : 'bg-[#0B0F17] border-[#222B3B] text-[#94A3B8] hover:text-[#E2E8F0]'
                    }`}
                  >
                    {preset.label}
                  </button>
                );
              })}
            </div>

            <textarea
              id="visual-style"
              rows={4}
              value={config.visualStylePrompt}
              onChange={(e) => onChange({ ...config, visualStylePrompt: e.target.value })}
              className="w-full px-3.5 py-2.5 text-xs font-mono leading-relaxed text-[#CBD5E1] bg-[#0B0F17] border border-[#243045] rounded-md focus:outline-none focus:border-[#C8A252] transition-colors"
            />
          </div>

          {/* Row 4: Schedule & Thresholds */}
          <div className="p-6 grid grid-cols-1 sm:grid-cols-2 gap-6">
            <div className="space-y-2.5">
              <label className="block text-sm font-medium text-[#E2E8F0]">
                Lịch chạy tự động 02:00 sáng
              </label>
              <div className="grid grid-cols-2 gap-1.5 p-1 bg-[#0B0F17] border border-[#1E2738] rounded-md">
                <button
                  type="button"
                  onClick={() => setCronTimezone('ICT_0200')}
                  className={`py-2 px-2.5 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                    config.cronTimezone === 'ICT_0200'
                      ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                      : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                  }`}
                >
                  02:00 Giờ VN
                </button>
                <button
                  type="button"
                  onClick={() => setCronTimezone('UTC_0200')}
                  className={`py-2 px-2.5 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                    config.cronTimezone === 'UTC_0200'
                      ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                      : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                  }`}
                >
                  02:00 Giờ UTC
                </button>
              </div>
              <p className="text-xs font-mono text-[#7C8DA6]">
                cron: {config.cronTimezone === 'ICT_0200' ? "'0 19 * * *'" : "'0 2 * * *'"}
              </p>
            </div>

            <div className="space-y-2.5">
              <div className="flex items-center justify-between">
                <label htmlFor="daily-count" className="text-sm font-medium text-[#E2E8F0]">
                  Số video mỗi ngày (Matrix)
                </label>
                <span className="text-sm font-mono tabular-nums text-[#C8A252]">
                  {config.dailyVideoCount} video
                </span>
              </div>
              <input
                id="daily-count"
                type="range"
                min={1}
                max={5}
                step={1}
                value={config.dailyVideoCount}
                onChange={(e) =>
                  onChange({ ...config, dailyVideoCount: Number(e.target.value) })
                }
                className="w-full accent-[#C8A252] cursor-pointer"
              />
              <p className="text-xs font-mono tabular-nums text-[#7C8DA6]">
                {config.dailyVideoCount * 30} video/tháng · ~{config.dailyVideoCount * 230} phút Actions/tháng
              </p>
            </div>

            <div className="space-y-2.5">
              <div className="flex items-center justify-between">
                <label htmlFor="sim-threshold" className="text-sm font-medium text-[#E2E8F0]">
                  Ngưỡng chặn trùng lặp ngữ nghĩa
                </label>
                <span className="text-sm font-mono tabular-nums text-[#C8A252]">
                  {Math.round(config.similarityThreshold * 100)}%
                </span>
              </div>
              <input
                id="sim-threshold"
                type="range"
                min={0.6}
                max={0.85}
                step={0.01}
                value={config.similarityThreshold}
                onChange={(e) =>
                  onChange({ ...config, similarityThreshold: Number(e.target.value) })
                }
                className="w-full accent-[#C8A252] cursor-pointer"
              />
              <p className="text-xs text-[#7C8DA6]">
                Cosine similarity vượt ngưỡng này sẽ bị hủy và viết lại góc nhìn mới.
              </p>
            </div>

            <div className="space-y-2.5">
              <div className="flex items-center justify-between">
                <label htmlFor="critic-score" className="text-sm font-medium text-[#E2E8F0]">
                  Điểm AI Critic tối thiểu
                </label>
                <span className="text-sm font-mono tabular-nums text-[#C8A252]">
                  {config.criticMinScore.toFixed(1)} / 10
                </span>
              </div>
              <input
                id="critic-score"
                type="range"
                min={7.0}
                max={9.0}
                step={0.5}
                value={config.criticMinScore}
                onChange={(e) =>
                  onChange({ ...config, criticMinScore: Number(e.target.value) })
                }
                className="w-full accent-[#C8A252] cursor-pointer"
              />
              <p className="text-xs text-[#7C8DA6]">
                Kịch bản đạt điểm dưới ngưỡng này sẽ tự động viết lại (tối đa 2 lần).
              </p>
            </div>
          </div>

          {/* Row 5: Voice & TTS Models */}
          <div className="p-6 space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              <div className="space-y-2.5">
                <label className="block text-sm font-medium text-[#E2E8F0]">
                  Hệ thống Giọng đọc ưu tiên (TTS)
                </label>
                <div className="grid grid-cols-2 gap-1.5 p-1 bg-[#0B0F17] border border-[#1E2738] rounded-md">
                  <button
                    type="button"
                    onClick={() =>
                      onChange({
                        ...config,
                        ttsPrimaryProvider: 'gemini_tts' as TTSProviderOption,
                      })
                    }
                    className={`py-2 px-2.5 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                      config.ttsPrimaryProvider === 'gemini_tts'
                        ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                        : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                    }`}
                  >
                    Gemini Native TTS
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      onChange({
                        ...config,
                        ttsPrimaryProvider: 'cloud_tts' as TTSProviderOption,
                      })
                    }
                    className={`py-2 px-2.5 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                      config.ttsPrimaryProvider === 'cloud_tts'
                        ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                        : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                    }`}
                  >
                    Google Cloud TTS
                  </button>
                </div>
                <p className="text-xs font-mono text-[#7C8DA6]">
                  {config.ttsPrimaryProvider === 'gemini_tts'
                    ? 'gemini-3.8-flash-tts → flash-lite-tts → Cloud TTS'
                    : 'Studio / Chirp3-HD / Neural2 (Google Cloud TTS)'}
                </p>
              </div>

              <div className="space-y-2.5">
                <label htmlFor="voice-persona" className="block text-sm font-medium text-[#E2E8F0]">
                  Nhân vật giọng đọc (Gemini TTS)
                </label>
                <select
                  id="voice-persona"
                  value={config.ttsVoicePersona}
                  onChange={(e) => {
                    const nextPersona = e.target.value as GeminiVoicePersona;
                    const found = VOICE_PERSONA_OPTIONS.find((v) => v.id === nextPersona);
                    onChange({
                      ...config,
                      ttsVoicePersona: nextPersona,
                      ttsVoiceStyle: found ? found.style : config.ttsVoiceStyle,
                    });
                  }}
                  className="w-full px-3 py-2 text-sm text-[#F1F5F9] bg-[#0B0F17] border border-[#243045] rounded-md focus:outline-none focus:border-[#C8A252]"
                >
                  {VOICE_PERSONA_OPTIONS.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="space-y-2">
              <label htmlFor="voice-style" className="block text-sm font-medium text-[#E2E8F0]">
                Chỉ đạo cảm xúc giọng đọc (TTS_VOICE_STYLE)
              </label>
              <input
                id="voice-style"
                type="text"
                value={config.ttsVoiceStyle}
                onChange={(e) => onChange({ ...config, ttsVoiceStyle: e.target.value })}
                className="w-full px-3.5 py-2 text-xs font-mono text-[#CBD5E1] bg-[#0B0F17] border border-[#243045] rounded-md focus:outline-none focus:border-[#C8A252]"
              />
            </div>
          </div>

          {/* Row 6: Visual Animation Mode */}
          <div className="p-6 grid grid-cols-1 sm:grid-cols-2 gap-6">
            <div className="space-y-2.5 sm:col-span-2">
              <label className="block text-sm font-medium text-[#E2E8F0]">
                Hiệu ứng diễn hoạt hình ảnh (VIDEO_VISUAL_MODE)
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-1.5 p-1 bg-[#0B0F17] border border-[#1E2738] rounded-md">
                <button
                  type="button"
                  onClick={() =>
                    onChange({
                      ...config,
                      videoVisualMode: 'stickman_whiteboard' as VideoVisualMode,
                    })
                  }
                  className={`py-2 px-2.5 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                    config.videoVisualMode === 'stickman_whiteboard'
                      ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                      : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                  }`}
                >
                  Whiteboard nhiều ảnh (Không bút)
                </button>
                <button
                  type="button"
                  onClick={() =>
                    onChange({
                      ...config,
                      videoVisualMode: 'pen_sketch' as VideoVisualMode,
                    })
                  }
                  className={`py-2 px-2.5 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                    config.videoVisualMode === 'pen_sketch'
                      ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                      : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                  }`}
                >
                  Bút vẽ nét hiện hình
                </button>
                <button
                  type="button"
                  onClick={() =>
                    onChange({
                      ...config,
                      videoVisualMode: 'ken_burns_2d' as VideoVisualMode,
                    })
                  }
                  className={`py-2 px-2.5 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                    config.videoVisualMode === 'ken_burns_2d'
                      ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                      : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                  }`}
                >
                  2D Ken Burns
                </button>
              </div>
              <p className="text-xs text-[#7C8DA6]">
                {config.videoVisualMode === 'stickman_whiteboard'
                  ? 'Tạo 24 ảnh minh họa theo từng ý content, chuyển cảnh mượt mà (không dùng cây bút di chuyển) + tốc độ 1.25x.'
                  : config.videoVisualMode === 'pen_sketch'
                    ? 'Cây bút máy vẽ nét trực tiếp theo đường biên tranh rồi đổ bóng hiện hình.'
                    : 'Ảnh tĩnh 2D kết hợp chuyển động zoom/pan điện ảnh.'}
              </p>
            </div>

            {config.videoVisualMode === 'stickman_whiteboard' && (
              <div className="space-y-2.5 sm:col-span-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <label className="block text-sm font-medium text-[#E2E8F0]">
                    Màu nền thương hiệu kênh (WHITEBOARD_BG_COLOR)
                  </label>
                  <span className="text-xs font-mono text-[#7C8DA6]">
                    {activeTheme.bgColor} · {activeTheme.inkColor} · {activeTheme.accentColor}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {WHITEBOARD_THEME_PRESETS.map((preset) => {
                    const isSelected = activeTheme.id === preset.id;
                    return (
                      <button
                        key={preset.id}
                        type="button"
                        onClick={() => applyConfigTheme(preset)}
                        className={`inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-md border transition-colors cursor-pointer ${
                          isSelected
                            ? 'bg-[#1D2536] border-[#C8A252] text-[#F1F5F9]'
                            : 'bg-[#0B0F17] border-[#222B3B] text-[#94A3B8] hover:text-[#E2E8F0]'
                        }`}
                      >
                        <span
                          className="w-3.5 h-3.5 rounded-sm border border-white/20 shrink-0"
                          style={{ backgroundColor: preset.bgColor }}
                        />
                        {preset.label}
                      </button>
                    );
                  })}
                  <label className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-md border bg-[#0B0F17] border-[#222B3B] text-[#CBD5E1] hover:border-[#C8A252] cursor-pointer">
                    <input
                      type="color"
                      aria-label="Chọn mã màu nền riêng cho kênh"
                      value={activeTheme.bgColor}
                      onChange={(e) =>
                        applyConfigTheme(buildCustomWhiteboardTheme(e.target.value))
                      }
                      className="w-4 h-4 p-0 border-0 bg-transparent cursor-pointer"
                    />
                    Tự chọn màu
                  </label>
                </div>
              </div>
            )}

            {config.videoVisualMode === 'pen_sketch' && (
              <div className="space-y-2.5 sm:col-span-2">
                <label className="block text-sm font-medium text-[#E2E8F0]">
                  Nền giấy vẽ (PEN_SKETCH_PAPER_THEME)
                </label>
                <div className="grid grid-cols-2 gap-1.5 p-1 bg-[#0B0F17] border border-[#1E2738] rounded-md">
                  <button
                    type="button"
                    onClick={() =>
                      onChange({
                        ...config,
                        penSketchPaperTheme: 'classic_parchment' as PenSketchPaperTheme,
                      })
                    }
                    className={`py-2 px-2.5 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                      config.penSketchPaperTheme === 'classic_parchment'
                        ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                        : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                    }`}
                  >
                    Giấy da cừu · Mực đen
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      onChange({
                        ...config,
                        penSketchPaperTheme: 'dark_slate' as PenSketchPaperTheme,
                      })
                    }
                    className={`py-2 px-2.5 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                      config.penSketchPaperTheme === 'dark_slate'
                        ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                        : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                    }`}
                  >
                    Than chì · Ngòi vàng
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right: Live 2D Animated Preview */}
        <div className="xl:col-span-5 bg-[#111722] border border-[#1E2738] rounded-lg p-6 space-y-4">
          <div className="flex items-center justify-between gap-2 pb-3 border-b border-[#1E2738]">
            <div>
              <h2 className="text-base font-semibold text-[#F1F5F9]">
                {config.videoVisualMode === 'stickman_whiteboard'
                  ? `Mô phỏng trực tiếp: ${activeTheme.label} (${activeTheme.bgColor})`
                  : config.videoVisualMode === 'pen_sketch'
                    ? 'Mô phỏng trực tiếp: Bút vẽ nét hiện hình'
                    : 'Mô phỏng khung hình 2D & Lớp phủ Pillow'}
              </h2>
              <p className="text-[11px] font-mono text-[#C8A252] mt-0.5">
                {config.videoVisualMode === 'stickman_whiteboard' ||
                config.videoVisualMode === 'pen_sketch'
                  ? previewPhase
                  : isVertical
                    ? '9:16 · 1080×1920 · Ken Burns'
                    : '16:9 · 1920×1080 · Ken Burns'}
              </p>
            </div>
            {(config.videoVisualMode === 'stickman_whiteboard' ||
              config.videoVisualMode === 'pen_sketch') && (
              <button
                type="button"
                onClick={() => setReplayNonce((n) => n + 1)}
                className="px-2.5 py-1 text-xs font-medium text-[#E2E8F0] bg-[#182233] border border-[#2A3852] hover:border-[#C8A252] rounded transition-colors whitespace-nowrap cursor-pointer"
              >
                Xem lại
              </button>
            )}
          </div>

          <div className="flex justify-center py-2">
            <div
              style={
                config.videoVisualMode === 'stickman_whiteboard'
                  ? { backgroundColor: activeTheme.bgColor }
                  : undefined
              }
              className={`relative overflow-hidden border border-[#283347] rounded-md w-full ${
                config.videoVisualMode === 'stickman_whiteboard' ? '' : 'bg-[#0A0D14]'
              } ${isVertical ? 'max-w-[280px] aspect-[9/16]' : 'aspect-video'}`}
            >
              {config.videoVisualMode === 'stickman_whiteboard' ||
              config.videoVisualMode === 'pen_sketch' ? (
                <canvas
                  ref={previewCanvasRef}
                  className="w-full h-full block object-cover"
                />
              ) : (
                <img
                  src={isVertical ? VERTICAL_IMG : LANDSCAPE_IMG}
                  alt="Minh họa 2D phong cách Khắc kỷ"
                  referrerPolicy="no-referrer"
                  className="w-full h-full object-cover"
                />
              )}

              {/* Chỉ hiện scrim tối + khung vàng ở chế độ Ken Burns / Pen Sketch; Whiteboard giữ nguyên sáng thoáng */}
              {config.videoVisualMode !== 'stickman_whiteboard' && (
                <>
                  <div className="absolute inset-0 bg-gradient-to-t from-[#0A0D13]/85 via-transparent to-transparent pointer-events-none" />
                  <div className="absolute inset-3 border border-[#C5A059]/45 pointer-events-none">
                    <div className="absolute top-0 left-0 w-3.5 h-3.5 border-t-2 border-l-2 border-[#C5A059]" />
                    <div className="absolute top-0 right-0 w-3.5 h-3.5 border-t-2 border-r-2 border-[#C5A059]" />
                    <div className="absolute bottom-0 left-0 w-3.5 h-3.5 border-b-2 border-l-2 border-[#C5A059]" />
                    <div className="absolute bottom-0 right-0 w-3.5 h-3.5 border-b-2 border-r-2 border-[#C5A059]" />
                  </div>

                  <div className="absolute inset-x-6 bottom-6 space-y-3 pointer-events-none">
                    <div className="bg-[#0B0E14]/80 border border-[#C5A059]/40 px-3.5 py-2.5 text-center">
                      <p
                        className={`font-medium text-[#F2EEE4] leading-snug ${
                          isVertical ? 'text-xs' : 'text-sm'
                        }`}
                      >
                        {sampleQuote}
                      </p>
                    </div>
                    <div className="space-y-1.5">
                      <div className="h-1 w-full bg-white/15 overflow-hidden">
                        <div className="h-full w-[28%] bg-[#C5A059]" />
                      </div>
                      <p className="text-[10px] font-mono text-[#CBD5E1]/80 text-center">
                        {sampleAttribution}
                      </p>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>

          <div className="pt-2 space-y-2 text-xs text-[#94A3B8] border-t border-[#1E2738]">
            <div className="flex justify-between">
              <span>Động cơ hình ảnh</span>
              <span className="font-mono text-[#E2E8F0]">
                {config.videoVisualMode === 'stickman_whiteboard'
                  ? 'Whiteboard 3-Beat Stickman (#F3E8C8)'
                  : config.videoVisualMode === 'pen_sketch'
                    ? 'sketch_animator.py (Bút vẽ nét -> Đổ bóng)'
                    : 'video_renderer.py (Ken Burns 2D)'}
              </span>
            </div>
            <div className="flex justify-between">
              <span>Bảng màu chủ đạo</span>
              <span className="font-mono text-[#E2E8F0]">
                {config.videoVisualMode === 'stickman_whiteboard'
                  ? `${activeTheme.bgColor} · ${activeTheme.inkColor} · ${activeTheme.accentColor}`
                  : 'Imagen 4 Fast / Editorial 2D'}
              </span>
            </div>
            <div className="flex justify-between">
              <span>Độ dài &amp; tốc độ</span>
              <span className="font-mono text-[#E2E8F0]">~5 phút (24 ảnh · 1.25x MP4)</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
