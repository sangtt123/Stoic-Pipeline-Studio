export interface WhiteboardTheme {
  id: string;
  label: string;
  tagline: string;
  bgColor: string;
  inkColor: string;
  accentColor: string;
  surfaceFill: string;
  isDark: boolean;
  promptDescription: string;
}

export const WHITEBOARD_THEME_PRESETS: WhiteboardTheme[] = [
  {
    id: 'cool_studio',
    label: 'Xám băng tối giản',
    tagline: 'Sáng sạch · Hiện đại · Khác biệt hẳn nền kem cũ',
    bgColor: '#EEF2F7',
    inkColor: '#0F172A',
    accentColor: '#2563EB',
    surfaceFill: '#FFFFFF',
    isDark: false,
    promptDescription:
      'clean cool ice-gray #EEF2F7 flat studio background, crisp deep navy-black #0F172A ink stickman and icons, vivid cobalt blue #2563EB arrows and highlight boxes, pure white #FFFFFF interior fills',
  },
  {
    id: 'midnight_chalk',
    label: 'Bảng xanh đêm',
    tagline: 'Tương phản cao · Nổi bật trên Feed YouTube',
    bgColor: '#111927',
    inkColor: '#F3F6FA',
    accentColor: '#F59E0B',
    surfaceFill: '#1D293D',
    isDark: true,
    promptDescription:
      'clean deep midnight-navy #111927 flat chalkboard background, crisp bright off-white #F3F6FA chalk-ink stickman and icons, vivid amber-gold #F59E0B arrows and emphasis marks, slate #1D293D interior fills',
  },
  {
    id: 'sage_mist',
    label: 'Xanh bạc hà trầm',
    tagline: 'Dịu mắt · Phong cách kênh Tâm lý học',
    bgColor: '#E8F0EC',
    inkColor: '#13221C',
    accentColor: '#D94E2A',
    surfaceFill: '#FFFFFF',
    isDark: false,
    promptDescription:
      'clean muted sage-mist #E8F0EC flat background, crisp deep forest-charcoal #13221C ink stickman and icons, vivid terracotta-vermilion #D94E2A arrows and X-marks, pure white #FFFFFF interior fills',
  },
  {
    id: 'obsidian_crimson',
    label: 'Đen nhám · Đỏ san hô',
    tagline: 'Mạnh mẽ · Chuẩn kênh Khắc kỷ & Kỷ luật',
    bgColor: '#15161A',
    inkColor: '#F4F1EA',
    accentColor: '#EF4444',
    surfaceFill: '#22242C',
    isDark: true,
    promptDescription:
      'clean matte obsidian-charcoal #15161A flat background, crisp warm ivory #F4F1EA ink stickman and icons, vivid coral-red #EF4444 arrows and X-marks, dark graphite #22242C interior fills',
  },
  {
    id: 'soft_lilac',
    label: 'Trắng ánh tím nhạt',
    tagline: 'Tươi mới · Dễ đọc trên màn hình điện thoại',
    bgColor: '#F3F1F8',
    inkColor: '#1E1B2E',
    accentColor: '#7C3AED',
    surfaceFill: '#FFFFFF',
    isDark: false,
    promptDescription:
      'clean soft alabaster-lilac #F3F1F8 flat background, crisp deep indigo-black #1E1B2E ink stickman and icons, vivid royal-violet #7C3AED arrows and highlight boxes, pure white #FFFFFF interior fills',
  },
];

export const DEFAULT_WHITEBOARD_THEME: WhiteboardTheme = WHITEBOARD_THEME_PRESETS[0];

function hexToRgb(hex: string): { r: number; g: number; b: number } | null {
  const clean = hex.trim().replace(/^#/, '');
  if (!/^[0-9a-fA-F]{6}$/.test(clean)) return null;
  return {
    r: parseInt(clean.slice(0, 2), 16),
    g: parseInt(clean.slice(2, 4), 16),
    b: parseInt(clean.slice(4, 6), 16),
  };
}

export function buildCustomWhiteboardTheme(
  bgHex: string,
  customAccentHex?: string
): WhiteboardTheme {
  const normalizedBg = /^#[0-9a-fA-F]{6}$/.test(bgHex.trim())
    ? bgHex.trim().toUpperCase()
    : DEFAULT_WHITEBOARD_THEME.bgColor;
  const rgb = hexToRgb(normalizedBg) ?? { r: 238, g: 242, b: 247 };
  const luminance = (0.299 * rgb.r + 0.587 * rgb.g + 0.114 * rgb.b) / 255;
  const isDark = luminance < 0.46;

  const inkColor = isDark ? '#F4F7FB' : '#0F172A';
  const surfaceFill = isDark ? '#1E293B' : '#FFFFFF';
  const accentColor =
    customAccentHex && /^#[0-9a-fA-F]{6}$/.test(customAccentHex.trim())
      ? customAccentHex.trim().toUpperCase()
      : isDark
        ? '#F59E0B'
        : '#E11D48';

  return {
    id: 'custom',
    label: `Tùy chỉnh (${normalizedBg})`,
    tagline: 'Màu thương hiệu riêng của kênh bạn',
    bgColor: normalizedBg,
    inkColor,
    accentColor,
    surfaceFill,
    isDark,
    promptDescription: `clean flat ${normalizedBg} background, crisp bold ${inkColor} ink stickman and icons, vivid ${accentColor} arrows and emphasis marks, ${surfaceFill} interior fills`,
  };
}

export function resolveWhiteboardTheme(
  themeId: string,
  bgColor?: string,
  accentColor?: string
): WhiteboardTheme {
  const found = WHITEBOARD_THEME_PRESETS.find((t) => t.id === themeId);
  if (found) return found;
  if (bgColor) return buildCustomWhiteboardTheme(bgColor, accentColor);
  return DEFAULT_WHITEBOARD_THEME;
}

/**
 * Đổi màu nền / nét mực / màu nhấn ngay lập tức trên SVG đã tạo (không cần gọi AI vẽ lại)
 * giúp người dùng thử nhiều màu background khác nhau trong 1 giây trước khi xuất MP4.
 */
export function rethemeStickmanSvg(
  svgMarkup: string,
  targetTheme: WhiteboardTheme,
  sourceTheme?: { bgColor: string; inkColor: string; accentColor: string; surfaceFill: string }
): string {
  const prevBg = (sourceTheme?.bgColor || '#F3E8C8').toUpperCase();
  const prevInk = (sourceTheme?.inkColor || '#141414').toUpperCase();
  const prevAccent = (sourceTheme?.accentColor || '#D92323').toUpperCase();
  const prevSurface = (sourceTheme?.surfaceFill || '#FFFFFF').toUpperCase();

  // Dùng placeholder tạm để tránh va chạm khi hoán đổi màu sáng <-> tối
  const replacements: [RegExp, string][] = [
    [new RegExp(prevBg, 'gi'), '__WB_BG__'],
    [new RegExp('#F3E8C8', 'gi'), '__WB_BG__'],
    [new RegExp(prevInk, 'gi'), '__WB_INK__'],
    [new RegExp('#141414', 'gi'), '__WB_INK__'],
    [new RegExp(prevAccent, 'gi'), '__WB_ACCENT__'],
    [new RegExp('#D92323', 'gi'), '__WB_ACCENT__'],
    [new RegExp(prevSurface, 'gi'), '__WB_SURFACE__'],
  ];

  let out = svgMarkup;
  for (const [pattern, token] of replacements) {
    out = out.replace(pattern, token);
  }

  return out
    .replace(/__WB_BG__/g, targetTheme.bgColor)
    .replace(/__WB_INK__/g, targetTheme.inkColor)
    .replace(/__WB_ACCENT__/g, targetTheme.accentColor)
    .replace(/__WB_SURFACE__/g, targetTheme.surfaceFill);
}

export function svgMarkupToDataUrl(svg: string): string {
  const bytes = new TextEncoder().encode(svg);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return `data:image/svg+xml;base64,${btoa(binary)}`;
}
