import { useState } from 'react';
import {
  CheckCircle2,
  Code2,
  Download,
  Film,
  GitBranch,
  Menu,
  Rocket,
  ShieldCheck,
  SlidersHorizontal,
  Workflow,
  X,
} from 'lucide-react';
import { CodeExplorerSection } from './components/CodeExplorerSection';
import { ConfigSection } from './components/ConfigSection';
import { DedupSection } from './components/DedupSection';
import { DeployGuideSection } from './components/DeployGuideSection';
import { FallbackSection } from './components/FallbackSection';
import { LiveStudioSection } from './components/LiveStudioSection';
import { OverviewSection } from './components/OverviewSection';
import {
  DEFAULT_PIPELINE_CONFIG,
  downloadProjectZip,
} from './data/projectFiles';
import type { NavSectionId, PipelineConfig } from './types/pipeline';

interface NavItem {
  id: NavSectionId;
  label: string;
  breadcrumb: string;
  icon: typeof Workflow;
}

const NAV_ITEMS: NavItem[] = [
  {
    id: 'overview',
    label: 'Kiến trúc Pipeline',
    breadcrumb: 'Tổng quan Kiến trúc 2 Giai đoạn',
    icon: Workflow,
  },
  {
    id: 'studio',
    label: 'Tạo Video có Giọng',
    breadcrumb: 'Tạo thử Video 2D có Giọng đọc AI',
    icon: Film,
  },
  {
    id: 'config',
    label: 'Cấu hình Cá nhân',
    breadcrumb: 'Cấu hình Cá nhân & Giọng đọc (config.py)',
    icon: SlidersHorizontal,
  },
  {
    id: 'dedup',
    label: 'Chống trùng 3 tầng',
    breadcrumb: 'Anti-Duplication Engine 3 Tầng',
    icon: ShieldCheck,
  },
  {
    id: 'fallback',
    label: 'Model & Auto-Fallback',
    breadcrumb: 'Hệ thống Model, Auto-Fallback & Chi phí',
    icon: GitBranch,
  },
  {
    id: 'code',
    label: 'Mã nguồn Dự án',
    breadcrumb: 'Trình duyệt Mã nguồn (20 tệp)',
    icon: Code2,
  },
  {
    id: 'deploy',
    label: 'Triển khai GitHub',
    breadcrumb: 'Hướng dẫn Triển khai 5 Bước',
    icon: Rocket,
  },
];

export default function App() {
  const [activeSection, setActiveSection] = useState<NavSectionId>('overview');
  const [config, setConfig] = useState<PipelineConfig>(DEFAULT_PIPELINE_CONFIG);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadSuccess, setDownloadSuccess] = useState(false);

  const currentNav = NAV_ITEMS.find((item) => item.id === activeSection) ?? NAV_ITEMS[0];

  const handleDownloadZip = async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      await downloadProjectZip(config);
      setDownloadSuccess(true);
      setTimeout(() => setDownloadSuccess(false), 2600);
    } finally {
      setDownloading(false);
    }
  };

  const handleSelectNav = (id: NavSectionId) => {
    setActiveSection(id);
    setMobileMenuOpen(false);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <div className="min-h-screen bg-[#0B0F17] text-[#E8ECF2] flex">
      {/* Desktop Sidebar Navigation */}
      <aside className="hidden lg:flex lg:flex-col lg:w-64 lg:shrink-0 border-r border-[#1E2738] bg-[#0D121B] sticky top-0 h-screen">
        <div className="h-16 px-6 flex items-center border-b border-[#1E2738]">
          <button
            type="button"
            onClick={() => handleSelectNav('overview')}
            className="text-base font-semibold tracking-tight text-[#F1F5F9] whitespace-nowrap cursor-pointer"
          >
            Stoic Pipeline Studio
          </button>
        </div>

        <nav aria-label="Điều hướng chính" className="flex-1 p-3 space-y-1 overflow-y-auto">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = item.id === activeSection;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => handleSelectNav(item.id)}
                className={`w-full flex items-center gap-3 px-3.5 py-2.5 text-sm font-medium rounded-md transition-colors whitespace-nowrap cursor-pointer ${
                  active
                    ? 'bg-[#172031] text-[#F1F5F9]'
                    : 'text-[#94A3B8] hover:text-[#E2E8F0] hover:bg-[#121926]'
                }`}
              >
                <Icon
                  className={`w-4 h-4 shrink-0 ${
                    active ? 'text-[#C8A252]' : 'text-[#64748B]'
                  }`}
                />
                <span className="truncate">{item.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Quiet Active Config Summary */}
        <div className="p-4 border-t border-[#1E2738] text-xs text-[#7C8DA6] space-y-1.5">
          <div className="flex justify-between">
            <span>Ngôn ngữ</span>
            <span className="font-mono text-[#CBD5E1]">{config.language}</span>
          </div>
          <div className="flex justify-between">
            <span>Khung hình</span>
            <span className="font-mono text-[#CBD5E1]">{config.aspectRatio}</span>
          </div>
          <div className="flex justify-between">
            <span>Giọng đọc</span>
            <span className="font-mono text-[#CBD5E1]">{config.ttsVoicePersona}</span>
          </div>
          <div className="flex justify-between">
            <span>Sản lượng</span>
            <span className="font-mono tabular-nums text-[#CBD5E1]">
              {config.dailyVideoCount} video/ngày
            </span>
          </div>
        </div>
      </aside>

      {/* Mobile Drawer Overlay */}
      {mobileMenuOpen && (
        <div className="fixed inset-0 z-40 lg:hidden flex">
          <div
            className="fixed inset-0 bg-black/60"
            onClick={() => setMobileMenuOpen(false)}
            aria-hidden="true"
          />
          <div className="relative z-50 w-64 max-w-[80vw] bg-[#0D121B] border-r border-[#1E2738] flex flex-col h-full">
            <div className="h-14 px-5 flex items-center justify-between border-b border-[#1E2738]">
              <span className="text-sm font-semibold text-[#F1F5F9]">Stoic Pipeline Studio</span>
              <button
                type="button"
                onClick={() => setMobileMenuOpen(false)}
                aria-label="Đóng menu"
                className="p-1.5 text-[#94A3B8] hover:text-[#F1F5F9] cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <nav className="p-3 space-y-1 flex-1 overflow-y-auto">
              {NAV_ITEMS.map((item) => {
                const Icon = item.icon;
                const active = item.id === activeSection;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => handleSelectNav(item.id)}
                    className={`w-full flex items-center gap-3 px-3.5 py-2.5 text-sm font-medium rounded-md transition-colors whitespace-nowrap cursor-pointer ${
                      active
                        ? 'bg-[#172031] text-[#F1F5F9]'
                        : 'text-[#94A3B8] hover:text-[#E2E8F0] hover:bg-[#121926]'
                    }`}
                  >
                    <Icon
                      className={`w-4 h-4 shrink-0 ${
                        active ? 'text-[#C8A252]' : 'text-[#64748B]'
                      }`}
                    />
                    <span>{item.label}</span>
                  </button>
                );
              })}
            </nav>
          </div>
        </div>
      )}

      {/* Main Content Column */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Bar Contract: Breadcrumb on left, 1 Primary Action on right */}
        <header className="h-16 px-4 sm:px-8 border-b border-[#1E2738] bg-[#0B0F17]/95 backdrop-blur-sm sticky top-0 z-30 flex items-center justify-between gap-6">
          <div className="flex items-center gap-3 min-w-0">
            <button
              type="button"
              onClick={() => setMobileMenuOpen(true)}
              aria-label="Mở điều hướng"
              className="lg:hidden p-2 -ml-2 text-[#94A3B8] hover:text-[#F1F5F9] cursor-pointer"
            >
              <Menu className="w-5 h-5" />
            </button>
            <div className="flex items-center gap-2 text-sm min-w-0">
              <span className="text-[#7C8DA6] hidden sm:inline whitespace-nowrap">
                Python &amp; GitHub Actions
              </span>
              <span className="text-[#475569] hidden sm:inline" aria-hidden="true">
                /
              </span>
              <span className="font-medium text-[#F1F5F9] truncate">
                {currentNav.breadcrumb}
              </span>
            </div>
          </div>

          <div className="flex items-center shrink-0">
            <button
              type="button"
              onClick={handleDownloadZip}
              disabled={downloading}
              className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-[#0B0F17] bg-[#C8A252] hover:bg-[#D7B366] disabled:opacity-60 rounded-md transition-colors whitespace-nowrap shrink-0 cursor-pointer"
            >
              {downloadSuccess ? (
                <>
                  <CheckCircle2 className="w-4 h-4" />
                  Đã tải gói ZIP
                </>
              ) : (
                <>
                  <Download className="w-4 h-4" />
                  {downloading ? 'Đang đóng gói...' : 'Tải dự án (.zip)'}
                </>
              )}
            </button>
          </div>
        </header>

        {/* Main Workspace Container */}
        <main className="flex-1 w-full max-w-[1200px] mx-auto px-4 sm:px-8 py-8">
          {activeSection === 'overview' && (
            <OverviewSection
              config={config}
              onNavigate={handleSelectNav}
              onDownloadZip={handleDownloadZip}
            />
          )}
          {activeSection === 'studio' && <LiveStudioSection config={config} />}
          {activeSection === 'config' && (
            <ConfigSection
              config={config}
              onChange={setConfig}
              onNavigate={handleSelectNav}
            />
          )}
          {activeSection === 'dedup' && <DedupSection config={config} />}
          {activeSection === 'fallback' && <FallbackSection config={config} />}
          {activeSection === 'code' && <CodeExplorerSection config={config} />}
          {activeSection === 'deploy' && (
            <DeployGuideSection onDownloadZip={handleDownloadZip} />
          )}
        </main>
      </div>
    </div>
  );
}
