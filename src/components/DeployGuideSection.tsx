import { useEffect, useState } from 'react';
import { Check, Copy, Download, FileJson } from 'lucide-react';

interface DeployGuideSectionProps {
  onDownloadZip: () => void;
}

interface GcpStatusPayload {
  connected: boolean;
  mode: 'service_account_json' | 'sandbox_fallback' | 'unconfigured' | 'error';
  projectId: string | null;
  clientEmail: string | null;
  source: string | null;
  error?: string;
}

const GITHUB_SECRETS = [
  {
    name: 'GCP_SA_KEY',
    example: '{"type": "service_account", "project_id": "...", ...}',
    desc: 'BẮT BUỘC — Dán toàn bộ nội dung file JSON Service Account (tải từ IAM -> Service Accounts -> Keys). Hệ thống tự động trích xuất project_id và client_email từ file này.',
  },
  {
    name: 'GDRIVE_FOLDER_ID',
    example: '1aBcDeFgHiJkLmNoPqRsTuVwXyZ',
    desc: 'BẮT BUỘC — Chuỗi ID phía sau /folders/ của thư mục Google Drive đã cấp quyền Editor cho client_email nằm trong file JSON.',
  },
  {
    name: 'GCP_PROJECT_ID',
    example: '(Tùy chọn — tự đọc từ file JSON)',
    desc: 'TÙY CHỌN — Chỉ cần khai báo nếu bạn muốn ghi đè Project ID khác với trường project_id sẵn có trong file Service Account JSON.',
  },
];

const STEPS = [
  {
    id: 'step1',
    title: '01. Bật 3 API bắt buộc trên Google Cloud Console',
    detail:
      'Vào APIs & Services -> Enable APIs and Services và bật: Vertex AI API (aiplatform.googleapis.com), Cloud Text-to-Speech API (texttospeech.googleapis.com) và Google Drive API (drive.googleapis.com).',
  },
  {
    id: 'step2',
    title: '02. Tạo Service Account & tải 1 file khóa JSON duy nhất',
    detail:
      'Tạo Service Account mới (ví dụ stoic-pipeline-bot), gán vai trò Vertex AI User (roles/aiplatform.user), sau đó vào tab Keys -> Add Key -> JSON để tải file khóa. Đổi tên thành service-account-key.json khi chạy local.',
  },
  {
    id: 'step3',
    title: '03. Chia sẻ thư mục Google Drive cho client_email trong file JSON',
    detail:
      'Mở file JSON vừa tải, chép địa chỉ client_email và nhấn Chia sẻ (Share) thư mục trống trên Google Drive với quyền Người chỉnh sửa (Editor). Thư mục này sẽ tự chứa cả history_log.json và toàn bộ video .mp4 hằng ngày.',
  },
  {
    id: 'step4',
    title: '04. Giải nén dự án, thả file service-account-key.json (khi test local) và push lên GitHub',
    detail:
      'Khi test trên máy cá nhân, chỉ cần đặt file service-account-key.json vào thư mục gốc (đã được .gitignore chặn để không bao giờ lộ lên Git). Hệ thống tự quét file JSON mà không cần nhập thêm API key.',
  },
  {
    id: 'step5',
    title: '05. Thêm GitHub Secrets (GCP_SA_KEY + GDRIVE_FOLDER_ID) & chạy thử',
    detail:
      'Dán nội dung file JSON vào secret GCP_SA_KEY và ID thư mục Drive vào GDRIVE_FOLDER_ID tại Settings -> Secrets and variables -> Actions. Sau đó vào tab Actions -> Run workflow để kiểm tra ngay.',
  },
];

export function DeployGuideSection({ onDownloadZip }: DeployGuideSectionProps) {
  const [checkedSteps, setCheckedSteps] = useState<Record<string, boolean>>({});
  const [copiedSecret, setCopiedSecret] = useState<string | null>(null);
  const [gcpStatus, setGcpStatus] = useState<GcpStatusPayload | null>(null);

  useEffect(() => {
    let active = true;
    fetch('/api/gcp/status')
      .then((res) => res.json())
      .then((data: GcpStatusPayload) => {
        if (active) setGcpStatus(data);
      })
      .catch(() => {
        // Ignore read-only check errors
      });
    return () => {
      active = false;
    };
  }, []);

  const toggleStep = (id: string) => {
    setCheckedSteps((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const completedCount = Object.values(checkedSteps).filter(Boolean).length;

  const copySecretName = async (name: string) => {
    try {
      await navigator.clipboard.writeText(name);
      setCopiedSecret(name);
      setTimeout(() => setCopiedSecret(null), 1500);
    } catch {
      // Ignore if clipboard blocked
    }
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 pb-6 border-b border-[#1E2738]">
        <div className="space-y-1.5">
          <h1 className="text-2xl font-semibold text-[#F1F5F9]">
            Kết nối bằng File JSON &amp; Triển khai GitHub Actions
          </h1>
          <p className="text-sm text-[#94A3B8]">
            Tiến độ hoàn thành:{' '}
            <span className="font-mono tabular-nums text-[#C8A252]">
              {completedCount} / {STEPS.length} bước
            </span>{' '}
            · Xác thực đồng bộ 100% qua Service Account JSON (`src/gcp_auth.py`).
          </p>
        </div>

        <button
          type="button"
          onClick={onDownloadZip}
          className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-[#0B0F17] bg-[#C8A252] hover:bg-[#D7B366] rounded-md transition-colors whitespace-nowrap shrink-0 cursor-pointer"
        >
          <Download className="w-3.5 h-3.5" />
          Tải dự án (.zip)
        </button>
      </div>

      {/* Unified Service Account JSON Summary */}
      <section className="bg-[#111722] border border-[#1E2738] rounded-lg p-5 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-[#F1F5F9]">
            <FileJson className="w-4 h-4 text-[#C8A252]" />
            <span>Trạng thái nhận diện Service Account JSON (Server-side)</span>
          </div>
          <span className="text-xs font-mono text-[#C8A252]">
            {gcpStatus?.mode === 'service_account_json'
              ? `Đã nạp từ ${gcpStatus.source}`
              : 'Tự động tìm service-account-key.json / GOOGLE_APPLICATION_CREDENTIALS / GCP_SA_KEY'}
          </span>
        </div>

        {gcpStatus?.mode === 'service_account_json' ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs font-mono bg-[#0D121B] border border-[#1E2738] rounded-md p-3.5">
            <div>
              <span className="text-[#7C8DA6]">project_id: </span>
              <span className="text-[#E2E8F0]">{gcpStatus.projectId}</span>
            </div>
            <div className="truncate">
              <span className="text-[#7C8DA6]">client_email: </span>
              <span className="text-[#E2E8F0]">{gcpStatus.clientEmail}</span>
            </div>
          </div>
        ) : (
          <p className="text-xs leading-relaxed text-[#94A3B8]">
            Cả backend Node.js (<code className="font-mono text-[#CBD5E1]">server.ts</code>) lẫn toàn bộ
            pipeline Python (<code className="font-mono text-[#CBD5E1]">src/gcp_auth.py</code>) đều tự
            động nạp file khóa theo thứ tự:{' '}
            <code className="font-mono text-[#CBD5E1]">GOOGLE_APPLICATION_CREDENTIALS</code> →{' '}
            <code className="font-mono text-[#CBD5E1]">GCP_SA_KEY</code> → file{' '}
            <code className="font-mono text-[#CBD5E1]">./service-account-key.json</code>. File khóa luôn
            được đọc hoàn toàn phía server để đảm bảo bảo mật tuyệt đối.
          </p>
        )}
      </section>

      {/* Checklist */}
      <div className="bg-[#111722] border border-[#1E2738] rounded-lg divide-y divide-[#1A2232]">
        {STEPS.map((step) => {
          const done = Boolean(checkedSteps[step.id]);
          return (
            <label
              key={step.id}
              className="p-5 flex items-start gap-4 hover:bg-[#151D2B]/50 transition-colors cursor-pointer"
            >
              <input
                type="checkbox"
                checked={done}
                onChange={() => toggleStep(step.id)}
                className="mt-1 h-4 w-4 rounded border-[#334155] accent-[#C8A252] cursor-pointer"
              />
              <div className="space-y-1">
                <div
                  className={`text-sm font-semibold ${
                    done ? 'line-through text-[#64748B]' : 'text-[#F1F5F9]'
                  }`}
                >
                  {step.title}
                </div>
                <p className="text-sm leading-relaxed text-[#94A3B8]">{step.detail}</p>
              </div>
            </label>
          );
        })}
      </div>

      {/* Google Cloud Console Quick Commands */}
      <section className="bg-[#111722] border border-[#1E2738] rounded-lg overflow-hidden">
        <div className="px-5 py-3.5 border-b border-[#1E2738] flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm font-semibold text-[#F1F5F9]">
            Lệnh bật API trên Google Cloud Console &amp; Kiểm thử file JSON (10 giây)
          </span>
          <span className="text-xs font-mono text-[#C8A252]">
            100% Google Cloud Console · 1 file JSON duy nhất
          </span>
        </div>
        <pre className="p-5 text-xs font-mono leading-relaxed text-[#CBD5E1] overflow-x-auto bg-[#0D121B]">{`# 1. Bật đủ 3 API trên Google Cloud Console (Cloud Shell hoặc gcloud CLI)
gcloud services enable \\
  aiplatform.googleapis.com \\
  texttospeech.googleapis.com \\
  drive.googleapis.com

# 2. Đặt file khóa vừa tải tại ./service-account-key.json rồi kiểm thử toàn bộ kết nối
# (Tự đọc project_id từ file JSON -> test Vertex LLM, Embedding, Cloud TTS, Drive, FFmpeg/OpenCV)
python -m src.test_gcp_connection

# (Tùy chọn) Test thêm tạo 1 ảnh 2D mẫu bằng Vertex AI Imagen (~$0.02)
python -m src.test_gcp_connection --with-imagen`}</pre>
      </section>

      {/* GitHub Secrets Table */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-[#F1F5F9]">
          Danh sách GitHub Repository Secrets cần khai báo
        </h2>
        <div className="bg-[#111722] border border-[#1E2738] rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-[#1E2738] text-xs font-medium text-[#8B9BB4] bg-[#0E131D]">
                  <th className="py-3 px-5">Tên Secret</th>
                  <th className="py-3 px-5">Định dạng mẫu</th>
                  <th className="py-3 px-5">Ý nghĩa</th>
                  <th className="py-3 px-5 text-right">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1A2232] text-sm">
                {GITHUB_SECRETS.map((sec) => (
                  <tr key={sec.name} className="hover:bg-[#151D2B]/50">
                    <td className="py-3.5 px-5 font-mono text-xs text-[#C8A252] whitespace-nowrap">
                      {sec.name}
                    </td>
                    <td className="py-3.5 px-5 font-mono text-xs text-[#7C8DA6] max-w-[220px] truncate">
                      {sec.example}
                    </td>
                    <td className="py-3.5 px-5 text-[#94A3B8]">{sec.desc}</td>
                    <td className="py-3.5 px-5 text-right">
                      <button
                        type="button"
                        onClick={() => copySecretName(sec.name)}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-[#CBD5E1] bg-[#172030] border border-[#26334A] hover:border-[#3D5070] rounded transition-colors whitespace-nowrap cursor-pointer"
                      >
                        {copiedSecret === sec.name ? (
                          <>
                            <Check className="w-3 h-3 text-[#4ADE80]" />
                            Đã chép
                          </>
                        ) : (
                          <>
                            <Copy className="w-3 h-3" />
                            Chép tên
                          </>
                        )}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  );
}
