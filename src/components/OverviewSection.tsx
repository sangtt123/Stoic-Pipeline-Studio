import { ArrowRight, Code2, Download, Layers, SlidersHorizontal } from 'lucide-react';
import type { NavSectionId, PipelineConfig } from '../types/pipeline';

interface OverviewSectionProps {
  config: PipelineConfig;
  onNavigate: (section: NavSectionId) => void;
  onDownloadZip: () => void;
}

export function OverviewSection({
  config,
  onNavigate,
  onDownloadZip,
}: OverviewSectionProps) {
  const resolutionText = config.aspectRatio === '16:9' ? '1920 × 1080' : '1080 × 1920';
  const languageText = config.language === 'vi-VN' ? 'Tiếng Việt (vi-VN)' : 'Tiếng Anh (en-US)';
  const cronText = config.cronTimezone === 'ICT_0200' ? '02:00 UTC+7 (19:00 UTC)' : '02:00 UTC';

  const stage1Steps = [
    {
      step: '01',
      module: 'drive_manager.py',
      title: 'Tải history_log.json (90 ngày)',
      detail: 'Tự động tải lịch sử các video gần đây từ thư mục Google Drive; khởi tạo file mới nếu lần đầu chạy.',
    },
    {
      step: '02',
      module: 'dedup_manager.py',
      title: 'Sinh Ma trận trực giao + Lọc ngữ nghĩa',
      detail: `Chọn ${config.dailyVideoCount} tổ hợp (Triết gia × Bối cảnh × Hook) không trùng nhau và kiểm tra Cosine Similarity ≤ ${Math.round(config.similarityThreshold * 100)}% qua text-embedding-004.`,
    },
    {
      step: '03',
      module: 'step1_script_planner.py',
      title: 'Viết kịch bản & AI Giám đốc Sáng tạo duyệt',
      detail: `Mỗi video 15–20 phân cảnh (~5 phút). Chấm điểm trên thang 10; dưới ${config.criticMinScore.toFixed(1)} tự động viết lại tối đa 2 lần rồi xuất scripts.json.`,
    },
  ];

  const stage2Steps = [
    {
      step: '01',
      module: 'tts_generator.py',
      title: 'Cloud TTS từng phân cảnh',
      detail: 'Tạo giọng nam trầm (Studio/Chirp3-HD/Neural2) cho từng câu thoại và đo chính xác duration bằng ffprobe.',
    },
    {
      step: '02',
      module: 'vertex_client.py + graphics_2d.py',
      title: 'Imagen 2D + Lớp phủ Pillow RGBA',
      detail: 'Sinh ảnh 2D tĩnh với seed ngẫu nhiên (không dùng Veo); Pillow vẽ viền tối giản, thanh tiến trình, trích dẫn và hạt bụi phim.',
    },
    {
      step: '03',
      module: 'sketch_animator.py + video_renderer.py',
      title: 'Bút mực vẽ nét hiện hình & Render FFmpeg',
      detail: 'Tách đường nét OpenCV cho cây bút máy chuyển động vẽ phác họa rồi đổ bóng hiện hình khớp lời thoại (hoặc 2D Ken Burns), xuất FFmpeg ultrafast + BGM (-22dB).',
    },
    {
      step: '04',
      module: 'video_reviewer.py + drive_manager.py',
      title: 'QA Contact Sheet & Upload Drive',
      detail: 'Kiểm tra khoảng lặng, gửi 1 ảnh lưới (15s/frame) cho Gemini Vision duyệt (tối đa 2 lần sửa), gắn [CHECK_REQUIRED]_ nếu chưa đạt, upload & xóa tạm.',
    },
  ];

  const operationalSpecs = [
    {
      metric: 'Sản lượng tự động',
      value: `${config.dailyVideoCount} video / ngày`,
      note: `${config.dailyVideoCount * 30} video / tháng (~5 phút mỗi video)`,
    },
    {
      metric: 'Thời gian chạy thực tế (Wall-clock)',
      value: '~11 – 14 phút / ngày',
      note: 'Nhờ Stage 2 chạy song song Matrix thay vì chạy tuần tự 5 video',
    },
    {
      metric: 'Quỹ phút GitHub Actions',
      value: '~1.050 – 1.250 phút / tháng',
      note: 'Nằm gọn trong hạn mức miễn phí 2.000 phút/tháng (Ubuntu runner)',
    },
    {
      metric: 'Chi phí hạ tầng Server / VPS',
      value: '$0 / tháng',
      note: '100% serverless headless trên GitHub Actions + Google Drive',
    },
    {
      metric: 'Cấu hình hiện tại',
      value: `${config.aspectRatio} (${resolutionText})`,
      note: `${languageText} · Lịch chạy ${cronText}`,
    },
  ];

  return (
    <div className="space-y-10">
      {/* Hero Summary Block */}
      <section className="flex flex-col lg:flex-row lg:items-end justify-between gap-6 pb-8 border-b border-[#1E2738]">
        <div className="space-y-3 max-w-3xl">
          <div className="flex flex-wrap items-center gap-2 text-xs text-[#94A3B8]">
            <span>GitHub Actions Headless Ubuntu</span>
            <span aria-hidden="true">·</span>
            <span>Vertex AI Auto-Fallback</span>
            <span aria-hidden="true">·</span>
            <span>Anti-Duplication 3 tầng</span>
            <span aria-hidden="true">·</span>
            <span>Google Drive Storage</span>
          </div>
          <h1 className="text-3xl lg:text-4xl font-semibold tracking-tight text-[#F1F5F9] [text-wrap:balance]">
            Hệ thống Python tự động hóa 5 video Triết lý Khắc kỷ 2D mỗi ngày
          </h1>
          <p className="text-[15px] leading-relaxed text-[#94A3B8]">
            Kiến trúc tách 2 giai đoạn khai thác Matrix song song trên GitHub Actions lúc 02:00 sáng,
            kết hợp Google Cloud TTS, Imagen 2D (không dùng Veo), Pillow, FFmpeg ultrafast và Gemini
            Vision Contact Sheet để tối ưu tuyệt đối chi phí Vertex AI.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3 shrink-0">
          <button
            type="button"
            onClick={() => onNavigate('studio')}
            className="inline-flex items-center gap-2 px-4 py-2.5 text-sm font-semibold text-[#0B0F17] bg-[#C8A252] hover:bg-[#D7B366] rounded-md transition-colors whitespace-nowrap shrink-0 cursor-pointer"
          >
            <Layers className="w-4 h-4" />
            Tạo thử Video có giọng
          </button>
          <button
            type="button"
            onClick={() => onNavigate('config')}
            className="inline-flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-[#E2E8F0] bg-[#151D2B] border border-[#263248] rounded-md hover:border-[#3B4D6B] hover:bg-[#1B2536] transition-colors whitespace-nowrap shrink-0 cursor-pointer"
          >
            <SlidersHorizontal className="w-4 h-4 text-[#C8A252]" />
            Tùy chỉnh cấu hình
          </button>
          <button
            type="button"
            onClick={() => onNavigate('code')}
            className="inline-flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-[#E2E8F0] bg-[#151D2B] border border-[#263248] rounded-md hover:border-[#3B4D6B] hover:bg-[#1B2536] transition-colors whitespace-nowrap shrink-0 cursor-pointer"
          >
            <Code2 className="w-4 h-4 text-[#C8A252]" />
            Xem 17 tệp mã nguồn
          </button>
        </div>
      </section>

      {/* 2-Stage Pipeline Architecture */}
      <section className="space-y-5">
        <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-2">
          <h2 className="text-xl font-semibold text-[#F1F5F9]">
            Kiến trúc 2 giai đoạn song song trên GitHub Actions
          </h2>
          <span className="text-xs font-mono tabular-nums text-[#8B9BB4]">
            Cron {cronText} → Stage 1 (1 Runner) → Stage 2 ({config.dailyVideoCount} Parallel Runners)
          </span>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-stretch">
          {/* Stage 1 Column */}
          <div className="xl:col-span-5 bg-[#111722] border border-[#1E2738] rounded-lg p-6 flex flex-col justify-between">
            <div className="space-y-5">
              <div className="pb-4 border-b border-[#1E2738]">
                <div className="flex items-center justify-between text-xs text-[#C8A252] font-medium mb-1">
                  <span>Giai đoạn 1 · Job 1</span>
                  <span className="font-mono tabular-nums text-[#8B9BB4]">1 Ubuntu Runner · ~3 phút</span>
                </div>
                <h3 className="text-lg font-semibold text-[#F1F5F9]">
                  Lập kế hoạch, Lọc trùng & AI Critic
                </h3>
              </div>

              <ol className="divide-y divide-[#1A2232]">
                {stage1Steps.map((item) => (
                  <li key={item.step} className="py-3.5 first:pt-0 last:pb-0">
                    <div className="flex items-baseline justify-between gap-3 mb-1">
                      <span className="text-sm font-medium text-[#E2E8F0]">
                        {item.step}. {item.title}
                      </span>
                      <span className="text-xs font-mono text-[#7C8DA6] shrink-0">
                        {item.module}
                      </span>
                    </div>
                    <p className="text-[13px] leading-relaxed text-[#94A3B8]">{item.detail}</p>
                  </li>
                ))}
              </ol>
            </div>

            <div className="mt-6 pt-4 border-t border-[#1E2738] flex items-center justify-between text-xs text-[#94A3B8]">
              <span>Đầu ra chuyển tiếp Artifact</span>
              <span className="font-mono text-[#E2E8F0]">output/scripts.json + Drive history_log.json</span>
            </div>
          </div>

          {/* Center Flow Bridge */}
          <div className="xl:col-span-1 flex xl:flex-col items-center justify-center gap-2 py-1 text-[#64748B]">
            <div className="h-px w-10 xl:w-px xl:h-12 bg-[#263248]" />
            <div className="flex items-center justify-center w-9 h-9 rounded-md bg-[#111722] border border-[#263248] text-[#C8A252]">
              <ArrowRight className="w-4 h-4 rotate-90 xl:rotate-0" />
            </div>
            <span className="text-[11px] font-mono text-center text-[#8B9BB4]">
              Matrix ×{config.dailyVideoCount}
            </span>
            <div className="h-px w-10 xl:w-px xl:h-12 bg-[#263248]" />
          </div>

          {/* Stage 2 Column */}
          <div className="xl:col-span-6 bg-[#111722] border border-[#1E2738] rounded-lg p-6 flex flex-col justify-between">
            <div className="space-y-5">
              <div className="pb-4 border-b border-[#1E2738]">
                <div className="flex items-center justify-between text-xs text-[#C8A252] font-medium mb-1">
                  <span>Giai đoạn 2 · Job 2 (Parallel Matrix)</span>
                  <span className="font-mono tabular-nums text-[#8B9BB4]">
                    VIDEO_INDEX [0..{config.dailyVideoCount - 1}] · ~7 phút/worker
                  </span>
                </div>
                <h3 className="text-lg font-semibold text-[#F1F5F9]">
                  Sản xuất Video 2D, Review Vision & Upload Drive
                </h3>
              </div>

              <ol className="divide-y divide-[#1A2232]">
                {stage2Steps.map((item) => (
                  <li key={item.step} className="py-3.5 first:pt-0 last:pb-0">
                    <div className="flex items-baseline justify-between gap-3 mb-1">
                      <span className="text-sm font-medium text-[#E2E8F0]">
                        {item.step}. {item.title}
                      </span>
                      <span className="text-xs font-mono text-[#7C8DA6] shrink-0">
                        {item.module}
                      </span>
                    </div>
                    <p className="text-[13px] leading-relaxed text-[#94A3B8]">{item.detail}</p>
                  </li>
                ))}
              </ol>
            </div>

            <div className="mt-6 pt-4 border-t border-[#1E2738] flex items-center justify-between text-xs text-[#94A3B8]">
              <span>Thành phẩm cuối cùng</span>
              <span className="font-mono text-[#E2E8F0]">
                {config.dailyVideoCount} tệp .mp4 trên Google Drive (tự xóa tạm)
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* Operational Specs Data Grid */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-[#F1F5F9]">
            Thông số vận hành và tối ưu tài nguyên
          </h2>
          <button
            type="button"
            onClick={() => onNavigate('fallback')}
            className="inline-flex items-center gap-1.5 text-sm text-[#C8A252] hover:text-[#DFBE73] transition-colors cursor-pointer whitespace-nowrap"
          >
            <Layers className="w-4 h-4" />
            Xem chi tiết Fallback & Chi phí
          </button>
        </div>

        <div className="bg-[#111722] border border-[#1E2738] rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-[#1E2738] text-xs font-medium text-[#8B9BB4] bg-[#0E131D]">
                  <th className="py-3 px-5">Chỉ số hệ thống</th>
                  <th className="py-3 px-5">Giá trị thiết kế</th>
                  <th className="py-3 px-5">Cơ chế kỹ thuật đảm bảo</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1A2232] text-sm">
                {operationalSpecs.map((row) => (
                  <tr key={row.metric} className="hover:bg-[#151D2B]/60 transition-colors">
                    <td className="py-3.5 px-5 font-medium text-[#E2E8F0] whitespace-nowrap">
                      {row.metric}
                    </td>
                    <td className="py-3.5 px-5 font-mono tabular-nums text-[#C8A252] whitespace-nowrap">
                      {row.value}
                    </td>
                    <td className="py-3.5 px-5 text-[#94A3B8]">{row.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* Quick Action Footer Callout */}
      <section className="bg-[#111722] border border-[#1E2738] rounded-lg p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="space-y-1">
          <h3 className="text-base font-semibold text-[#F1F5F9]">
            Sẵn sàng đẩy thẳng lên GitHub Repository
          </h3>
          <p className="text-sm text-[#94A3B8]">
            Gói tải xuống chứa đầy đủ toàn bộ mã nguồn Python, file workflow GitHub Actions và{' '}
            <code className="text-[#E2E8F0]">config.py</code> đã đồng bộ theo tùy chỉnh của bạn.
          </p>
        </div>
        <button
          type="button"
          onClick={onDownloadZip}
          className="inline-flex items-center justify-center gap-2 px-5 py-2.5 text-sm font-semibold text-[#0B0F17] bg-[#C8A252] hover:bg-[#D7B366] rounded-md transition-colors whitespace-nowrap shrink-0 cursor-pointer"
        >
          <Download className="w-4 h-4" />
          Tải trọn bộ dự án (.zip)
        </button>
      </section>
    </div>
  );
}
