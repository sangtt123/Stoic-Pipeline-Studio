import { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import {
  MODERN_CONTEXTS_LIST,
  NARRATIVE_HOOKS_LIST,
  PHILOSOPHERS_LIST,
} from '../data/projectFiles';
import type { MatrixComboItem, PipelineConfig } from '../types/pipeline';

interface DedupSectionProps {
  config: PipelineConfig;
}

function shuffle<T>(arr: T[]): T[] {
  const copy = [...arr];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

const SAMPLE_QUOTES = [
  'Trở ngại trên đường đi chính là con đường.',
  'Chúng ta đau khổ trong trí tưởng tượng nhiều hơn thực tế.',
  'Đừng mong mọi việc xảy ra theo ý bạn; hãy muốn chúng xảy ra đúng như bản chất.',
  'Người làm chủ được cơn giận của mình mạnh hơn kẻ chiếm được một thành phố.',
  'Kỷ luật tự do là tự do cao nhất mà con người có thể đạt tới.',
  'Không ai có thể làm tổn thương bạn trừ khi bạn cho phép tâm trí mình đồng thuận.',
  'Đừng giải thích triết lý của bạn — hãy sống đúng với nó.',
];

function sampleOrthogonalMatrix(count: number, language: PipelineConfig['language']): MatrixComboItem[] {
  const phils = shuffle(PHILOSOPHERS_LIST);
  const ctxs = shuffle(MODERN_CONTEXTS_LIST);
  const hooks = shuffle(NARRATIVE_HOOKS_LIST);
  const quotes = shuffle(SAMPLE_QUOTES);
  const wordTarget = language === 'vi-VN' ? '~1.100 từ' : '~780 words';

  return Array.from({ length: count }, (_, idx) => ({
    slot: idx + 1,
    philosopher: phils[idx % phils.length],
    modernContext: ctxs[idx % ctxs.length],
    narrativeHook: hooks[idx % hooks.length],
    estimatedWords: wordTarget,
    sampleQuote: quotes[idx % quotes.length],
  }));
}

const HISTORY_JSON_SCHEMA = `{
  "updated_at": "2026-11-22T19:03:18+00:00",
  "retention_days": 90,
  "total_records": 450,
  "videos": [
    {
      "created_at": "2026-11-21T19:02:11+00:00",
      "title": "Nghịch lý của sự cô độc chủ động trong thời đại ồn ào",
      "angle": "Tách biệt giữa cô đơn thụ động và tĩnh lặng chiến lược của Seneca",
      "philosopher": "Seneca (Letters from a Stoic)",
      "modern_context": "Cô độc chủ động, tự lập tài chính",
      "narrative_hook": "Nghịch lý tâm lý ngược đời",
      "core_quote": "Đám đông càng đông đúc, bản lĩnh càng dễ bị bào mòn.",
      "summary": "Phân tích vì sao việc tự tách mình 90 phút mỗi ngày giúp khôi phục sự sáng suốt.",
      "embedding": [0.0184, -0.0412, 0.0297, "... 768 chiều (text-embedding-004)"]
    }
  ]
}`;

export function DedupSection({ config }: DedupSectionProps) {
  const [combos, setCombos] = useState<MatrixComboItem[]>(() =>
    sampleOrthogonalMatrix(config.dailyVideoCount, config.language)
  );
  const [generationCount, setGenerationCount] = useState(1);

  const handleResample = () => {
    setCombos(sampleOrthogonalMatrix(config.dailyVideoCount, config.language));
    setGenerationCount((c) => c + 1);
  };

  const totalTheoreticalCombos =
    PHILOSOPHERS_LIST.length * MODERN_CONTEXTS_LIST.length * NARRATIVE_HOOKS_LIST.length;

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="space-y-1.5 pb-6 border-b border-[#1E2738]">
        <h1 className="text-2xl font-semibold text-[#F1F5F9]">
          Cơ chế chống trùng lặp nội dung 3 tầng (Anti-Duplication Engine)
        </h1>
        <p className="text-sm text-[#94A3B8] max-w-3xl">
          Được cài đặt trong <code className="text-[#E2E8F0]">src/dedup_manager.py</code> để bảo
          đảm {config.dailyVideoCount * 30} video/tháng không bao giờ lặp ý tưởng, góc nhìn hay
          câu trích dẫn trong cửa sổ trượt {config.historyRetentionDays} ngày.
        </p>
      </div>

      {/* 3 Tiers Summary Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="bg-[#111722] border border-[#1E2738] rounded-lg p-6 space-y-2.5">
          <div className="text-xs font-mono text-[#C8A252]">Tầng 1 · Google Drive Memory</div>
          <h2 className="text-base font-semibold text-[#F1F5F9]">
            Bộ nhớ lịch sử 90 ngày (history_log.json)
          </h2>
          <p className="text-sm leading-relaxed text-[#94A3B8]">
            Tải tự động từ thư mục Drive trước khi lên ý tưởng, tự động cắt bỏ các bản ghi quá{' '}
            <span className="font-mono tabular-nums text-[#E2E8F0]">
              {config.historyRetentionDays}
            </span>{' '}
            ngày và cập nhật ghi đè lên cùng 1 File ID (không sinh tệp rác) sau khi duyệt xong.
          </p>
        </div>

        <div className="bg-[#111722] border border-[#1E2738] rounded-lg p-6 space-y-2.5">
          <div className="text-xs font-mono text-[#C8A252]">Tầng 2 · Angle & Persona Matrix</div>
          <h2 className="text-base font-semibold text-[#F1F5F9]">
            Ma trận trực giao {totalTheoreticalCombos} tổ hợp
          </h2>
          <p className="text-sm leading-relaxed text-[#94A3B8]">
            Ghép ngẫu nhiên có kiểm soát trên 3 trục ({PHILOSOPHERS_LIST.length} Triết gia ×{' '}
            {MODERN_CONTEXTS_LIST.length} Bối cảnh × {NARRATIVE_HOOKS_LIST.length} Hook), ép 5
            video trong cùng ngày không trùng bất kỳ trục nào và đưa danh sách lịch sử vào System Prompt.
          </p>
        </div>

        <div className="bg-[#111722] border border-[#1E2738] rounded-lg p-6 space-y-2.5">
          <div className="text-xs font-mono text-[#C8A252]">Tầng 3 · Semantic Similarity</div>
          <h2 className="text-base font-semibold text-[#F1F5F9]">
            Embedding text-embedding-004 + LLM Cross-Check
          </h2>
          <p className="text-sm leading-relaxed text-[#94A3B8]">
            Tính Cosine Similarity giữa kịch bản mới và toàn bộ lịch sử 90 ngày + các kịch bản đã
            duyệt hôm nay. Nếu <span className="font-mono tabular-nums text-[#E2E8F0]">&gt; {Math.round(config.similarityThreshold * 100)}%</span>{' '}
            sẽ tự động hủy và đổi sang tổ hợp ma trận hoàn toàn mới; vùng 65%–75% kiểm tra chéo bằng LLM.
          </p>
        </div>
      </div>

      {/* Interactive Tier 2 Matrix Simulator */}
      <section className="bg-[#111722] border border-[#1E2738] rounded-lg overflow-hidden">
        <div className="px-6 py-4 border-b border-[#1E2738] flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-[#F1F5F9]">
              Mô phỏng Ma trận góc nhìn hôm nay (Tầng 2)
            </h2>
            <p className="text-xs text-[#8B9BB4] mt-0.5">
              Lượt sinh #{generationCount} · {config.dailyVideoCount} tổ hợp trực giao hoàn toàn không lặp Triết gia, Bối cảnh hoặc Hook
            </p>
          </div>
          <button
            type="button"
            onClick={handleResample}
            className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-[#0B0F17] bg-[#C8A252] hover:bg-[#D7B366] rounded-md transition-colors whitespace-nowrap shrink-0 cursor-pointer"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Sinh {config.dailyVideoCount} tổ hợp ngẫu nhiên
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-[#1E2738] text-xs font-medium text-[#8B9BB4] bg-[#0E131D]">
                <th className="py-3 px-5 whitespace-nowrap">Worker</th>
                <th className="py-3 px-5">Trục 1: Triết gia / Trường phái</th>
                <th className="py-3 px-5">Trục 2: Bối cảnh đời thực</th>
                <th className="py-3 px-5">Trục 3: Cấu trúc kể chuyện (Hook)</th>
                <th className="py-3 px-5 text-right whitespace-nowrap">Độ dài mục tiêu</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1A2232] text-sm">
              {combos.slice(0, config.dailyVideoCount).map((row) => (
                <tr key={row.slot} className="hover:bg-[#151D2B]/60 transition-colors">
                  <td className="py-3.5 px-5 font-mono tabular-nums text-[#C8A252] whitespace-nowrap">
                    VIDEO_INDEX={row.slot - 1}
                  </td>
                  <td className="py-3.5 px-5 text-[#E2E8F0]">{row.philosopher}</td>
                  <td className="py-3.5 px-5 text-[#CBD5E1]">{row.modernContext}</td>
                  <td className="py-3.5 px-5 text-[#94A3B8]">{row.narrativeHook}</td>
                  <td className="py-3.5 px-5 font-mono tabular-nums text-right text-[#8B9BB4] whitespace-nowrap">
                    {row.estimatedWords}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Tier 1 Schema & Tier 3 Similarity Decision Rules */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
        <div className="xl:col-span-7 bg-[#111722] border border-[#1E2738] rounded-lg overflow-hidden">
          <div className="px-5 py-3.5 border-b border-[#1E2738] flex items-center justify-between">
            <span className="text-sm font-semibold text-[#F1F5F9]">
              Cấu trúc tệp history_log.json trên Google Drive
            </span>
            <span className="text-xs font-mono text-[#7C8DA6]">Lưu sẵn vector 768 chiều</span>
          </div>
          <pre className="p-5 text-xs font-mono leading-relaxed text-[#CBD5E1] overflow-x-auto bg-[#0D121B]">
            {HISTORY_JSON_SCHEMA}
          </pre>
        </div>

        <div className="xl:col-span-5 bg-[#111722] border border-[#1E2738] rounded-lg p-6 space-y-4">
          <h3 className="text-base font-semibold text-[#F1F5F9]">
            Quy tắc ra quyết định của Tầng 3 (Semantic Check)
          </h3>
          <div className="divide-y divide-[#1A2232] text-sm">
            <div className="py-3 first:pt-0">
              <div className="flex items-center justify-between font-mono tabular-nums text-xs mb-1">
                <span className="text-[#4ADE80]">Cosine Similarity &lt; 0.65</span>
                <span className="text-[#8B9BB4]">Chấp nhận ngay</span>
              </div>
              <p className="text-[13px] text-[#94A3B8]">
                Ý tưởng khác biệt rõ rệt với 90 ngày lịch sử; chuyển thẳng sang vòng AI Giám đốc
                Sáng tạo chấm điểm.
              </p>
            </div>

            <div className="py-3">
              <div className="flex items-center justify-between font-mono tabular-nums text-xs mb-1">
                <span className="text-[#FBBF24]">
                  0.65 ≤ Similarity ≤ {config.similarityThreshold.toFixed(2)}
                </span>
                <span className="text-[#8B9BB4]">LLM kiểm tra chéo</span>
              </div>
              <p className="text-[13px] text-[#94A3B8]">
                Gửi tiêu đề + góc tiếp cận + tóm tắt 1 câu của 2 video cho LLM đối chiếu xem có bị
                trùng thông điệp cốt lõi hay chỉ trùng từ khóa triết học.
              </p>
            </div>

            <div className="py-3 last:pb-0">
              <div className="flex items-center justify-between font-mono tabular-nums text-xs mb-1">
                <span className="text-[#F87171]">
                  Similarity &gt; {config.similarityThreshold.toFixed(2)}
                </span>
                <span className="text-[#8B9BB4]">Hủy & đổi ma trận</span>
              </div>
              <p className="text-[13px] text-[#94A3B8]">
                Từ chối ngay kịch bản ứng viên, tự động rút một tổ hợp (Triết gia × Bối cảnh × Hook)
                hoàn toàn mới và yêu cầu AI viết lại từ đầu.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
