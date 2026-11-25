/**
 * stickmanBeatRenderer.ts
 * Bộ dựng hoạt ảnh bảng trắng Stickman (#F3E8C8) theo từng nhịp (Beat 1 -> Beat 2 -> Beat 3)
 * chuyển cảnh bằng hiệu ứng hiện hình mượt mà (fade + trượt nhẹ), KHÔNG dùng cây bút di chuyển giật cục.
 */

export interface StickmanBeatAsset {
  hasBeats: boolean;
  beat1Img: HTMLImageElement;
  beat2Img: HTMLImageElement;
  beat3Img: HTMLImageElement;
  width: number;
  height: number;
}

export const STICKMAN_CREAM_BG = '#F3E8C8';
export const STICKMAN_INK = '#141414';
export const STICKMAN_RED = '#D92323';

function svgToDataUrl(svg: string): string {
  const bytes = new TextEncoder().encode(svg);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return `data:image/svg+xml;base64,${btoa(binary)}`;
}

function loadImageElement(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Không thể nạp khung hình bảng trắng Stickman.'));
    img.src = src;
  });
}

function injectBeatVisibilityStyle(svgMarkup: string, hideIds: string[]): string {
  if (hideIds.length === 0) return svgMarkup;
  const rules = hideIds.map((id) => `#${id} { opacity: 0; visibility: hidden; }`).join(' ');
  const styleTag = `<style>${rules}</style>`;
  const match = svgMarkup.match(/^<svg\b[^>]*>/i);
  if (!match) return svgMarkup;
  const openTag = match[0];
  return `${openTag}${styleTag}${svgMarkup.slice(openTag.length)}`;
}

/**
 * Chuẩn bị 3 lớp ảnh (Beat 1 / Beat 1+2 / Toàn cảnh Beat 1+2+3) từ SVG để dựng mượt mà trên Canvas.
 */
export async function prepareStickmanBeatAsset(
  svgMarkup: string | undefined,
  fallbackImageUrl: string,
  width: number,
  height: number
): Promise<StickmanBeatAsset> {
  const hasBeatLayers =
    Boolean(svgMarkup) &&
    /id\s*=\s*["']beat-1["']/i.test(svgMarkup!) &&
    /id\s*=\s*["']beat-2["']/i.test(svgMarkup!);

  if (hasBeatLayers && svgMarkup) {
    try {
      const svgB1 = injectBeatVisibilityStyle(svgMarkup, ['beat-2', 'beat-3']);
      const svgB2 = injectBeatVisibilityStyle(svgMarkup, ['beat-3']);
      const svgB3 = svgMarkup;

      const [beat1Img, beat2Img, beat3Img] = await Promise.all([
        loadImageElement(svgToDataUrl(svgB1)),
        loadImageElement(svgToDataUrl(svgB2)),
        loadImageElement(svgToDataUrl(svgB3)),
      ]);

      return {
        hasBeats: true,
        beat1Img,
        beat2Img,
        beat3Img,
        width,
        height,
      };
    } catch {
      // Fallback sang ảnh đầy đủ
    }
  }

  const fullImg = await loadImageElement(fallbackImageUrl);
  return {
    hasBeats: false,
    beat1Img: fullImg,
    beat2Img: fullImg,
    beat3Img: fullImg,
    width,
    height,
  };
}

function drawContained(
  ctx: CanvasRenderingContext2D,
  img: HTMLImageElement,
  width: number,
  height: number,
  offsetY = 0,
  scaleBoost = 1
) {
  const srcW = img.naturalWidth || img.width || width;
  const srcH = img.naturalHeight || img.height || height;
  if (srcW <= 0 || srcH <= 0) return;

  const baseScale = Math.min(width / srcW, height / srcH);
  const scale = baseScale * scaleBoost;
  const drawW = srcW * scale;
  const drawH = srcH * scale;
  const dx = (width - drawW) / 2;
  const dy = (height - drawH) / 2 + offsetY;
  ctx.drawImage(img, dx, dy, drawW, drawH);
}

function easeOutCubic(t: number): number {
  const clamped = Math.max(0, Math.min(1, t));
  return 1 - Math.pow(1 - clamped, 3);
}

/**
 * Render từng khung hình bảng trắng Stickman mượt mà KHÔNG dùng bút di chuyển:
 * - Chuyển cảnh sạch bằng fade-in êm và hiện từng lớp ý chính (Beat 1 -> Beat 2 -> Beat 3)
 *   giúp người xem tập trung 100% vào hình minh họa và thay ảnh liên tục theo lời thoại.
 */
export function renderStickmanBeatFrame(
  ctx: CanvasRenderingContext2D,
  asset: StickmanBeatAsset,
  localP: number,
  bgColor = '#EEF2F7'
) {
  const { width, height } = asset;
  const p = Math.max(0, Math.min(1, localP));

  // Nền bảng trắng theo đúng bảng màu người dùng chọn (tránh trùng lặp nền kem YouTube)
  ctx.fillStyle = bgColor;
  ctx.fillRect(0, 0, width, height);

  if (!asset.hasBeats) {
    // Ảnh đơn (vd: Vertex AI Imagen) -> hiện mượt bằng fade-in + zoom cực nhẹ 1.00 -> 1.03
    const enterAlpha = easeOutCubic(p / 0.14);
    const subtleZoom = 1.0 + 0.03 * p;
    ctx.save();
    ctx.globalAlpha = enterAlpha;
    drawContained(ctx, asset.beat3Img, width, height, 0, subtleZoom);
    ctx.restore();
    return;
  }

  // Nhịp 1 (0.00 -> 0.30): Hiện Beat 1 bằng fade-in + trượt nhẹ 10px lên
  if (p < 0.30) {
    const t1 = easeOutCubic(p / 0.14);
    const slideY = (1 - t1) * 10;
    ctx.save();
    ctx.globalAlpha = t1;
    drawContained(ctx, asset.beat1Img, width, height, slideY, 1);
    ctx.restore();
    return;
  }

  // Nhịp 2 (0.30 -> 0.62): Giữ Beat 1 rõ nét + hiện mượt Beat 2 (mũi tên đỏ / dấu X gạch sai)
  if (p < 0.62) {
    drawContained(ctx, asset.beat1Img, width, height, 0, 1);

    const t2 = easeOutCubic((p - 0.30) / 0.14);
    ctx.save();
    ctx.globalAlpha = t2;
    drawContained(ctx, asset.beat2Img, width, height, 0, 1);
    ctx.restore();
    return;
  }

  // Nhịp 3 (0.62 -> 1.00): Giữ Beat 1+2 + hiện mượt Beat 3 (giải pháp / từ khóa chốt)
  drawContained(ctx, asset.beat2Img, width, height, 0, 1);

  const t3 = easeOutCubic((p - 0.62) / 0.14);
  ctx.save();
  ctx.globalAlpha = t3;
  drawContained(ctx, asset.beat3Img, width, height, 0, 1);
  ctx.restore();
}

/**
 * SVG mẫu minh họa trực tiếp phong cách Studio Vector Explainer (dùng cho màn hình Cấu hình).
 */
export const SAMPLE_STICKMAN_EXPLAINER_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">
  <rect width="1280" height="720" fill="#F3E8C8"/>
  <circle cx="180" cy="130" r="190" fill="#D92323" fill-opacity="0.06"/>
  <circle cx="1100" cy="560" r="210" fill="#141414" fill-opacity="0.04"/>
  <rect x="320" y="22" width="640" height="50" rx="25" fill="#FFFFFF" stroke="#141414" stroke-width="3"/>
  <text x="640" y="55" text-anchor="middle" font-family="'DejaVu Sans', 'Segoe UI', Arial, sans-serif" font-size="24" font-weight="700" fill="#141414">#1 Kiểm soát phản ứng – Tâm trí vững như đá tảng</text>

  <rect x="76" y="102" width="1144" height="482" rx="28" fill="#141414" fill-opacity="0.08"/>
  <rect x="68" y="94" width="1144" height="482" rx="28" fill="#FFFFFF" stroke="#141414" stroke-width="4"/>

  <g id="beat-1">
    <rect x="116" y="132" width="506" height="406" rx="20" fill="#F3E8C8" stroke="#141414" stroke-width="3.5" stroke-dasharray="10 6"/>
    <rect x="249" y="150" width="240" height="40" rx="20" fill="#FFFFFF" stroke="#141414" stroke-width="3"/>
    <text x="369" y="177" text-anchor="middle" font-family="'DejaVu Sans', 'Segoe UI', Arial, sans-serif" font-size="20" font-weight="700" fill="#141414">Phản ứng vội</text>
    <g transform="translate(369, 360) scale(0.9)">
      <path d="M-86 14 Q-114 14 -114 -16 Q-114 -44 -86 -48 Q-76 -88 -34 -92 Q8 -96 32 -66 Q66 -74 90 -46 Q116 -38 112 -8 Q110 14 82 14 Z" fill="#FFFFFF" stroke="#141414" stroke-width="6" stroke-linejoin="round"/>
      <polygon points="6,14 -24,62 2,62 -14,108 32,48 6,48 22,14" fill="#D92323" stroke="#141414" stroke-width="3.5" stroke-linejoin="round"/>
      <line x1="-68" y1="34" x2="-82" y2="74" stroke="#141414" stroke-width="4.5" stroke-linecap="round"/>
      <line x1="56" y1="34" x2="42" y2="74" stroke="#141414" stroke-width="4.5" stroke-linecap="round"/>
    </g>
  </g>

  <g id="beat-2">
    <g transform="translate(520, 224)">
      <circle cx="0" cy="0" r="52" fill="#D92323" fill-opacity="0.14"/>
      <path d="M-34 -34 L34 34 M34 -34 L-34 34" stroke="#D92323" stroke-width="12" stroke-linecap="round"/>
    </g>
    <circle cx="640" cy="335" r="34" fill="#D92323" stroke="#FFFFFF" stroke-width="5"/>
    <path d="M628 335 L652 335 M642 325 L654 335 L642 345" fill="none" stroke="#FFFFFF" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round"/>
  </g>

  <g id="beat-3">
    <rect x="658" y="132" width="506" height="406" rx="20" fill="#D92323" fill-opacity="0.08" stroke="#D92323" stroke-width="4"/>
    <rect x="791" y="150" width="240" height="40" rx="20" fill="#D92323"/>
    <text x="911" y="177" text-anchor="middle" font-family="'DejaVu Sans', 'Segoe UI', Arial, sans-serif" font-size="20" font-weight="800" fill="#FFFFFF">Làm chủ tâm trí</text>
    <g transform="translate(911, 368) scale(0.86)">
      <ellipse cx="0" cy="172" rx="68" ry="12" fill="#141414" fill-opacity="0.12"/>
      <path d="M-16 102 L-24 166 L-40 168 M16 102 L24 166 L42 168" fill="none" stroke="#141414" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M-32 20 L-58 64 L-38 92" fill="none" stroke="#141414" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M-34 8 Q0 -6 34 8 L28 104 Q0 112 -28 104 Z" fill="#FFFFFF" stroke="#141414" stroke-width="5.2" stroke-linejoin="round"/>
      <polygon points="0,14 -8,44 0,76 8,44" fill="#D92323"/>
      <path d="M32 18 L76 32 L92 14" fill="none" stroke="#141414" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M88 -34 L132 -20 L128 42 Q108 78 88 92 Q68 78 64 42 L68 -20 Z" fill="#FFFFFF" stroke="#D92323" stroke-width="6" stroke-linejoin="round"/>
      <path d="M77 24 L86 34 L104 12" fill="none" stroke="#D92323" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round"/>
      <rect x="-8" y="-32" width="16" height="34" rx="6" fill="#FFFFFF" stroke="#141414" stroke-width="4.5"/>
      <circle cx="0" cy="-76" r="46" fill="#FFFFFF" stroke="#141414" stroke-width="5.2"/>
      <path d="M-38 -102 Q-18 -134 18 -126 Q38 -120 44 -94 Q18 -110 -12 -106 Q-28 -104 -38 -102 Z" fill="#141414"/>
      <circle cx="-14" cy="-79" r="4.6" fill="#141414"/>
      <circle cx="14" cy="-79" r="4.6" fill="#141414"/>
      <path d="M-16 -60 Q0 -46 16 -60" fill="none" stroke="#141414" stroke-width="4.2" stroke-linecap="round"/>
    </g>
  </g>

  <rect x="68" y="598" width="1144" height="98" rx="20" fill="#FFFFFF" stroke="#D92323" stroke-width="4"/>
  <rect x="68" y="598" width="16" height="98" rx="8" fill="#D92323"/>
  <text x="640" y="659" text-anchor="middle" font-family="'DejaVu Sans', 'Segoe UI', Arial, sans-serif" font-size="36" font-weight="800" fill="#141414">Dừng 3 giây để chọn bản lĩnh thay vì cảm xúc</text>
</svg>`;
