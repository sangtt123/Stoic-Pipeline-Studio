import { useMemo, useState } from 'react';
import { Check, Copy, FileCode2, FileText, Search } from 'lucide-react';
import { buildProjectFiles } from '../data/projectFiles';
import type { PipelineConfig } from '../types/pipeline';

interface CodeExplorerSectionProps {
  config: PipelineConfig;
}

export function CodeExplorerSection({ config }: CodeExplorerSectionProps) {
  const files = useMemo(() => buildProjectFiles(config), [config]);
  const [selectedPath, setSelectedPath] = useState<string>(files[0].path);
  const [searchQuery, setSearchQuery] = useState('');
  const [copiedPath, setCopiedPath] = useState<string | null>(null);

  const filteredFiles = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return files;
    return files.filter(
      (f) =>
        f.path.toLowerCase().includes(q) || f.summary.toLowerCase().includes(q)
    );
  }, [files, searchQuery]);

  const activeFile =
    files.find((f) => f.path === selectedPath) ?? files[0];

  const lines = useMemo(() => activeFile.content.split('\n'), [activeFile.content]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(activeFile.content);
      setCopiedPath(activeFile.path);
      setTimeout(() => setCopiedPath(null), 1800);
    } catch {
      // Fallback safely if clipboard unavailable
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3 pb-5 border-b border-[#1E2738]">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold text-[#F1F5F9]">
            Trình duyệt mã nguồn dự án Python
          </h1>
          <p className="text-sm text-[#94A3B8]">
            {files.length} tệp hoàn chỉnh, chạy không giao diện trên GitHub Actions Ubuntu ·{' '}
            <code className="text-[#C8A252]">config.py</code> và{' '}
            <code className="text-[#C8A252]">daily_stoic_pipeline.yml</code> tự cập nhật theo cấu hình của bạn.
          </p>
        </div>
      </div>

      {/* Split Explorer + Code Pane */}
      <div className="grid grid-cols-1 lg:grid-cols-12 border border-[#1E2738] rounded-lg overflow-hidden bg-[#111722] min-h-[640px]">
        {/* File Tree Sidebar */}
        <div className="lg:col-span-4 xl:col-span-3 border-b lg:border-b-0 lg:border-r border-[#1E2738] flex flex-col">
          <div className="p-3 border-b border-[#1E2738]">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-[#64748B] absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Lọc tệp theo tên..."
                className="w-full pl-8 pr-3 py-1.5 text-xs text-[#E2E8F0] placeholder:text-[#64748B] bg-[#0B0F17] border border-[#222B3B] rounded focus:outline-none focus:border-[#C8A252]"
              />
            </div>
          </div>

          <div className="overflow-y-auto max-h-[300px] lg:max-h-[600px] divide-y divide-[#171F2E]">
            {filteredFiles.length === 0 ? (
              <div className="p-4 text-xs text-[#7C8DA6]">
                Không tìm thấy tệp phù hợp với từ khóa &quot;{searchQuery}&quot;.
              </div>
            ) : (
              filteredFiles.map((file) => {
                const isSelected = file.path === activeFile.path;
                const Icon = file.language === 'python' || file.language === 'yaml' ? FileCode2 : FileText;
                return (
                  <button
                    key={file.path}
                    type="button"
                    onClick={() => setSelectedPath(file.path)}
                    className={`w-full text-left px-3.5 py-2.5 flex items-start gap-2.5 transition-colors cursor-pointer ${
                      isSelected
                        ? 'bg-[#192334] text-[#F1F5F9]'
                        : 'text-[#94A3B8] hover:bg-[#151D2B] hover:text-[#E2E8F0]'
                    }`}
                  >
                    <Icon
                      className={`w-4 h-4 mt-0.5 shrink-0 ${
                        isSelected ? 'text-[#C8A252]' : 'text-[#64748B]'
                      }`}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-mono truncate">{file.path}</span>
                      </div>
                      {file.isDynamic && (
                        <span className="block text-[10px] text-[#C8A252] mt-0.5">
                          Đồng bộ theo Cấu hình cá nhân
                        </span>
                      )}
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Code Viewer Pane */}
        <div className="lg:col-span-8 xl:col-span-9 flex flex-col min-w-0 bg-[#0D121B]">
          {/* Active File Header */}
          <div className="px-5 py-3.5 bg-[#111722] border-b border-[#1E2738] flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm font-mono text-[#F1F5F9] truncate">
                <span>{activeFile.path}</span>
                <span className="text-xs text-[#64748B] tabular-nums">
                  · {lines.length} dòng
                </span>
              </div>
              <p className="text-xs text-[#8B9BB4] mt-0.5">{activeFile.summary}</p>
            </div>

            <button
              type="button"
              onClick={handleCopy}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-[#E2E8F0] bg-[#172030] border border-[#28364E] hover:border-[#3E5172] rounded transition-colors whitespace-nowrap shrink-0 cursor-pointer"
            >
              {copiedPath === activeFile.path ? (
                <>
                  <Check className="w-3.5 h-3.5 text-[#4ADE80]" />
                  Đã sao chép
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5 text-[#C8A252]" />
                  Sao chép mã
                </>
              )}
            </button>
          </div>

          {/* Code Body with Line Numbers */}
          <div className="flex-1 overflow-auto max-h-[600px] p-4">
            <table className="w-full border-collapse font-mono text-xs leading-6">
              <tbody>
                {lines.map((line, idx) => (
                  <tr key={idx} className="hover:bg-[#141C2A]/70">
                    <td className="select-none pr-4 text-right text-[#4B5B75] tabular-nums w-10 align-top">
                      {idx + 1}
                    </td>
                    <td className="text-[#D8E1EE] whitespace-pre">{line || ' '}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
