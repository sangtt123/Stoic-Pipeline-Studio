/**
 * serverSvgQuality.ts
 * Bộ kiểm định, tự động sửa lỗi XML/SVG, định khung tọa độ chống chồng chữ
 * và tạo SVG dự phòng sắc nét để đảm bảo 0% lỗi hình ảnh trong Web Studio.
 */

export interface SvgThemeColors {
  bgColor: string;
  inkColor: string;
  accentColor: string;
  surfaceFill: string;
}

export function escapeXmlText(input: string): string {
  return String(input || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function wrapVietnameseLines(text: string, maxCharsPerLine: number, maxLines: number): string[] {
  const cleaned = String(text || '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!cleaned) return [];

  const words = cleaned.split(' ');
  const lines: string[] = [];
  let current = '';

  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length > maxCharsPerLine && current) {
      lines.push(current);
      current = word;
      if (lines.length >= maxLines) break;
    } else {
      current = candidate;
    }
  }
  if (current && lines.length < maxLines) {
    lines.push(current);
  }
  return lines;
}

/**
 * Làm sạch & tự động vá các lỗi XML phổ biến do LLM sinh ra khi viết SVG:
 * - Dấu `&` trần (ví dụ "Kaizen & Stoicism") làm vỡ bộ phân tích XML của trình duyệt
 * - Dấu `->`, `<`, `>` nằm trần trong thẻ `<text>` hoặc `<tspan>`
 * - Thiếu `xmlns`, `viewBox`, hoặc `width`/`height` (gây lỗi `img.width === 0` khi vẽ lên Canvas)
 * - Thiếu nền `<rect>` đúng màu chủ đạo của kênh
 */
export function sanitizeAndRepairSvg(
  rawText: string,
  vbW: number,
  vbH: number,
  safeBg: string,
  stripAllText = false
): string | null {
  const svgMatch = rawText.match(/<svg[\s\S]*?<\/svg>/i);
  if (!svgMatch) return null;

  let svg = svgMatch[0]
    // Xóa ký tự điều khiển không hợp lệ trong XML 1.0
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '')
    // Bảo mật: loại bỏ script, foreignObject, event handlers, link ngoài
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<foreignObject[\s\S]*?<\/foreignObject>/gi, '')
    .replace(/\son[a-z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '')
    .replace(/(?:xlink:)?href\s*=\s*["']\s*(?:https?:|javascript:|data:text)[^"']*["']/gi, '');

  if (stripAllText) {
    svg = svg.replace(/<text[\s\S]*?<\/text>/gi, '');
  }

  // Vá lỗi dấu & không hợp lệ trong XML (nhưng giữ nguyên &amp; &lt; &gt; &quot; &apos; &#123; &#x1F;)
  svg = svg.replace(/&(?!amp;|lt;|gt;|quot;|apos;|#[0-9]+;|#x[0-9a-fA-F]+;)/g, '&amp;');

  // Vá dấu ->, <- và ký tự < > trần bên trong nội dung text/tspan (không đụng thẻ con <tspan>)
  svg = svg.replace(/(<(?:text|tspan)\b[^>]*>)([\s\S]*?)(<\/(?:text|tspan)>)/gi, (_m, open, body, close) => {
    // Tách theo thẻ con hợp lệ như <tspan ...> hoặc </tspan> để chỉ escape phần text thuần
    const parts = String(body).split(/(<\/?tspan\b[^>]*>)/gi);
    const repaired = parts
      .map((part) => {
        if (/^<\/?tspan\b[^>]*>$/i.test(part)) return part;
        return part
          .replace(/-->/g, '→')
          .replace(/->/g, '→')
          .replace(/<-/g, '←')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;');
      })
      .join('');
    return `${open}${repaired}${close}`;
  });

  // Nếu có dùng xlink: mà thiếu xmlns:xlink -> bổ sung namespace chuẩn
  if (/\bxlink:/i.test(svg) && !/xmlns:xlink\s*=/i.test(svg)) {
    svg = svg.replace('<svg', '<svg xmlns:xlink="http://www.w3.org/1999/xlink"');
  }

  // Đảm bảo có xmlns chuẩn
  if (!/xmlns\s*=/i.test(svg)) {
    svg = svg.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"');
  }

  // Đảm bảo có viewBox chính xác
  if (!/viewBox\s*=/i.test(svg)) {
    svg = svg.replace('<svg', `<svg viewBox="0 0 ${vbW} ${vbH}"`);
  }

  // Đảm bảo có width & height tường minh (tránh lỗi naturalWidth === 0 khi vẽ SVG lên Canvas HTML5)
  const openTagMatch = svg.match(/^<svg\b[^>]*>/i);
  if (openTagMatch) {
    let openTag = openTagMatch[0];
    if (!/\bwidth\s*=/i.test(openTag)) {
      openTag = openTag.replace(/>$/, ` width="${vbW}">`);
    }
    if (!/\bheight\s*=/i.test(openTag)) {
      openTag = openTag.replace(/>$/, ` height="${vbH}">`);
    }
    svg = openTag + svg.slice(openTagMatch[0].length);
  }

  // Đảm bảo có lớp nền chuẩn đúng màu kênh ở dưới cùng nếu LLM quên vẽ nền
  const hasFullBgRect = new RegExp(
    `<rect[^>]+width\\s*=\\s*["'](?:${vbW}|100%)["'][^>]+height\\s*=\\s*["'](?:${vbH}|100%)["']`,
    'i'
  ).test(svg);
  if (!hasFullBgRect) {
    svg = svg.replace(
      /(<svg\b[^>]*>)/i,
      `$1\n  <rect width="${vbW}" height="${vbH}" fill="${safeBg}"/>`
    );
  }

  return svg;
}

/**
 * Kiểm tra cấu trúc XML chặt chẽ + chất lượng hình học cơ bản trước khi trả về trình duyệt.
 */
export function validateSvgWellFormed(
  svg: string,
  options: { requireBeats?: boolean; minPrimitives?: number } = {}
): { ok: boolean; reason?: string } {
  const { requireBeats = false, minPrimitives = 5 } = options;

  if (!svg || !svg.trim().startsWith('<svg') || !svg.trim().endsWith('</svg>')) {
    return { ok: false, reason: 'Thiếu thẻ mở/đóng <svg> hoàn chỉnh.' };
  }

  // Loại bỏ comment và nội dung <style> trước khi kiểm tra đóng/mở thẻ
  const cleanedForTagScan = svg
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, '');

  const stack: string[] = [];
  const tagRe = /<(\/?)([a-zA-Z][\w:-]*)((?:\s+[^<>]*?)?)(\/?)>/g;
  let match: RegExpExecArray | null;

  while ((match = tagRe.exec(cleanedForTagScan)) !== null) {
    const isClosing = match[1] === '/';
    const tagName = match[2].toLowerCase();
    const attrs = match[3] || '';
    const isSelfClosing = match[4] === '/';

    // Kiểm tra số lượng dấu nháy kép cân bằng trong thuộc tính thẻ (phát hiện lỗi cú pháp sớm)
    const doubleQuotes = (attrs.match(/"/g) || []).length;
    if (doubleQuotes % 2 !== 0) {
      return { ok: false, reason: `Lỗi đóng mở dấu ngoặc kép ở thẻ <${tagName}>.` };
    }

    if (isSelfClosing) {
      continue;
    }
    if (isClosing) {
      if (stack.length === 0 || stack[stack.length - 1] !== tagName) {
        return {
          ok: false,
          reason: `Thẻ đóng </${tagName}> không khớp thẻ mở <${stack[stack.length - 1] || 'none'}>.`,
        };
      }
      stack.pop();
    } else {
      stack.push(tagName);
    }
  }

  if (stack.length !== 0) {
    return { ok: false, reason: `Còn thẻ chưa đóng: ${stack.join(', ')}.` };
  }

  // Kiểm tra có đủ thành phần đồ họa (tránh ảnh trống hoặc chỉ có mỗi khung nền)
  const primitiveMatches = svg.match(/<(?:path|circle|rect|line|polygon|ellipse|polyline)\b/gi) || [];
  if (primitiveMatches.length < minPrimitives) {
    return {
      ok: false,
      reason: `Quá ít nét vẽ minh họa (${primitiveMatches.length} < ${minPrimitives}).`,
    };
  }

  if (requireBeats) {
    const hasB1 = /id\s*=\s*["']beat-1["']/i.test(svg);
    const hasB2 = /id\s*=\s*["']beat-2["']/i.test(svg);
    const hasB3 = /id\s*=\s*["']beat-3["']/i.test(svg);
    if (!hasB1 || !hasB2 || !hasB3) {
      return { ok: false, reason: 'Thiếu đủ 3 nhóm hoạt ảnh beat-1, beat-2, beat-3.' };
    }
  }

  return { ok: true };
}

/**
 * Hướng dẫn phân vùng tọa độ chặt chẽ theo từng loại bố cục để tránh chữ đè lên hình.
 */
export function buildLayoutZoneGuide(layoutType: string, vbW: number, vbH: number): string {
  if (vbH > vbW) {
    // Khổ dọc 9:16 (720 x 1280)
    return [
      'LAYOUT ZONES (9:16 VERTICAL — ZERO OVERLAP):',
      '- Header Zone: y=60..160 (centered x=360).',
      '- beat-1 (Top Visual / Problem): x=70..650, y=200..520.',
      '- beat-2 (Middle Transition / Accent Arrow or X): x=140..580, y=540..720.',
      '- beat-3 (Bottom Solution / Takeaway Card): x=70..650, y=750..1140.',
    ].join('\n');
  }

  switch (layoutType) {
    case 'comparison_vs':
      return [
        'LAYOUT ZONES (comparison_vs — 1280x720 — ZERO OVERLAP):',
        '- Header Zone: y=45..115 (centered x=640).',
        '- beat-1 (LEFT PANEL — WRONG / OLD WAY): x=70..520, y=155..620. Draw stickman/icon inside y=180..500, place short label at y=575 (text-anchor="middle", x=295).',
        '- beat-2 (CENTER DIVIDER & ACCENT X / ARROW): x=540..740, y=220..540. Put big accent X on left mistake or bold curved accent arrow pointing from x=530 to x=750.',
        '- beat-3 (RIGHT PANEL — RIGHT / NEW WAY): x=760..1210, y=155..620. Draw calm stickman/icon inside y=180..500, place framed takeaway label box at y=545..615 (x=985).',
      ].join('\n');

    case 'cause_effect':
      return [
        'LAYOUT ZONES (cause_effect — 1280x720 — ZERO OVERLAP):',
        '- Header Zone: y=45..115 (centered x=640).',
        '- beat-1 (LEFT CAUSE — x=80..440, y=170..610): Trigger icon + expressive stickman, short label at y=585 (x=260).',
        '- beat-2 (CENTER ACTION ARROW — x=460..800, y=260..480): Bold curved accent arrow + small 2-3 word action pill box above the arrow (y=260..320).',
        '- beat-3 (RIGHT RESULT — x=820..1200, y=170..610): Result icon/stickman + framed outcome label box at y=545..615 (x=1010).',
      ].join('\n');

    case 'three_branches':
      return [
        'LAYOUT ZONES (three_branches — 1280x720 — ZERO OVERLAP):',
        '- Header Zone: y=45..115 (centered x=640).',
        '- beat-1 (LEFT CORE STICKMAN — x=70..380, y=180..600): Standing stickman pointing right + short core label at y=590.',
        '- beat-2 (BRANCHING ACCENT ARROWS — x=395..620, y=180..600): 3 crisp accent arrows fanning out to y=215, y=385, y=555.',
        '- beat-3 (3 RIGHT STEP CARDS — x=640..1200): 3 stacked rounded boxes (width=540, height=110) at y=160, y=330, y=500 with numbered icon on left and short 3-5 word Vietnamese text inside.',
      ].join('\n');

    case 'summary_list':
      return [
        'LAYOUT ZONES (summary_list — 1280x720 — ZERO OVERLAP):',
        '- Header Zone: y=45..115 (centered x=640).',
        '- beat-1 (LEFT CHECKLIST STICKMAN — x=80..400, y=180..610): Confident smiling stickman holding clipboard/lightbulb.',
        '- beat-2 (CENTER CHECKMARK ACCENT — x=420..520, y=180..600): Bold accent vertical guide & checkmark badges.',
        '- beat-3 (RIGHT SUMMARY ITEMS — x=530..1200, y=165..620): 3–4 clean horizontal rounded rows (height=90, gap=22) with short bold Vietnamese takeaways (<= 28 chars per row).',
      ].join('\n');

    case 'chapter_title':
      return [
        'LAYOUT ZONES (chapter_title — 1280x720 — ZERO OVERLAP):',
        '- beat-1 (CENTER FOCAL ICON + STICKMAN — x=380..900, y=130..440): Large bold expressive stickman + 1 iconic symbol.',
        '- beat-2 (ACCENT UNDERLINE & SPARKS — x=300..980, y=455..510): Crisp accent highlight bar & emphasis rays.',
        '- beat-3 (MAIN PRINCIPLE BANNER — x=140..1140, y=525..635): Bold framed title card with short crisp Vietnamese heading (text-anchor="middle", x=640).',
      ].join('\n');

    default:
      return [
        'LAYOUT ZONES (stickman_explain — 1280x720 — ZERO OVERLAP):',
        '- Header Zone: y=45..115 (centered x=640).',
        '- beat-1 (LEFT STICKMAN — x=85..470, y=165..610): Expressive stickman (head r=42 at cx=270, cy=255, torso y=297..435, tie, arms, legs) + 1–2 short caption words at y=590.',
        '- beat-2 (CENTER ACCENT CONNECTOR — x=490..690, y=250..470): Vivid accent curved arrow or big X highlighting the insight.',
        '- beat-3 (RIGHT CONCEPT CARD — x=710..1200, y=165..610): Clean visual metaphor icon inside a rounded card (y=180..475) + bold short takeaway box (y=515..605, text-anchor="middle").',
      ].join('\n');
  }
}

/**
 * SVG Whiteboard Stickman dự phòng siêu sắc nét khi toàn bộ model LLM gặp lỗi hoặc sinh XML hỏng.
 * Đảm bảo 100% phân cảnh luôn có hình ảnh rõ ràng, đúng màu kênh và hỗ trợ hoạt ảnh 3 nhịp beat-1/2/3.
 */
export function buildDeterministicStickmanFallbackSvg(params: {
  chapterHeader: string;
  sceneLabel: string;
  narration: string;
  layoutType: string;
  theme: SvgThemeColors;
  vbW: number;
  vbH: number;
}): string {
  const { chapterHeader, sceneLabel, narration, layoutType, theme, vbW, vbH } = params;
  const { bgColor, inkColor, accentColor, surfaceFill } = theme;
  const headerText = escapeXmlText((chapterHeader || sceneLabel || 'Tư duy Khắc kỷ').slice(0, 48));
  const focusLines = wrapVietnameseLines(sceneLabel || narration, 22, 2).map(escapeXmlText);
  const narrationLines = wrapVietnameseLines(narration, 28, 3).map(escapeXmlText);

  const focusBlock = focusLines
    .map(
      (line, idx) =>
        `<text x="955" y="${548 + idx * 36}" text-anchor="middle" font-family="'DejaVu Sans', 'Segoe UI', Arial, sans-serif" font-size="28" font-weight="700" fill="${inkColor}">${line}</text>`
    )
    .join('\n    ');

  const cardTextBlock = narrationLines
    .map(
      (line, idx) =>
        `<text x="955" y="${335 + idx * 38}" text-anchor="middle" font-family="'DejaVu Sans', 'Segoe UI', Arial, sans-serif" font-size="26" font-weight="700" fill="${inkColor}">${line}</text>`
    )
    .join('\n    ');

  const isComparison = layoutType === 'comparison_vs';
  const leftLabel = isComparison ? 'Cách làm sai' : 'Vấn đề cốt lõi';
  const midLabel = isComparison ? 'Chuyển hướng' : 'Nguyên lý';

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${vbW} ${vbH}" width="${vbW}" height="${vbH}">
  <rect width="${vbW}" height="${vbH}" fill="${bgColor}"/>
  <text x="${Math.round(vbW / 2)}" y="74" text-anchor="middle" font-family="'DejaVu Sans', 'Segoe UI', Arial, sans-serif" font-size="36" font-weight="700" fill="${inkColor}">${headerText}</text>
  <line x1="220" y1="96" x2="${vbW - 220}" y2="96" stroke="${inkColor}" stroke-width="3.5" stroke-linecap="round"/>

  <g id="beat-1">
    <circle cx="270" cy="255" r="44" fill="${surfaceFill}" stroke="${inkColor}" stroke-width="5"/>
    <circle cx="256" cy="248" r="4.5" fill="${inkColor}"/>
    <circle cx="284" cy="248" r="4.5" fill="${inkColor}"/>
    <path d="M254 270 Q270 282 286 270" fill="none" stroke="${inkColor}" stroke-width="4" stroke-linecap="round"/>
    <line x1="270" y1="299" x2="270" y2="442" stroke="${inkColor}" stroke-width="5" stroke-linecap="round"/>
    <polygon points="270,306 262,336 270,362 278,336" fill="${inkColor}"/>
    <path d="M270 338 L212 382 M270 338 L345 312" stroke="${inkColor}" stroke-width="5" stroke-linecap="round"/>
    <path d="M270 442 L232 538 M270 442 L308 538" stroke="${inkColor}" stroke-width="5" stroke-linecap="round"/>
    <rect x="145" y="566" width="250" height="54" rx="10" fill="${surfaceFill}" stroke="${inkColor}" stroke-width="4"/>
    <text x="270" y="602" text-anchor="middle" font-family="'DejaVu Sans', 'Segoe UI', Arial, sans-serif" font-size="26" font-weight="700" fill="${inkColor}">${escapeXmlText(leftLabel)}</text>
  </g>

  <g id="beat-2">
    <path d="M415 375 Q545 305 665 375" fill="none" stroke="${accentColor}" stroke-width="8" stroke-linecap="round"/>
    <polygon points="688,384 646,356 654,398" fill="${accentColor}"/>
    <rect x="455" y="255" width="190" height="48" rx="10" fill="${surfaceFill}" stroke="${accentColor}" stroke-width="4"/>
    <text x="550" y="287" text-anchor="middle" font-family="'DejaVu Sans', 'Segoe UI', Arial, sans-serif" font-size="24" font-weight="700" fill="${accentColor}">${escapeXmlText(midLabel)}</text>
  </g>

  <g id="beat-3">
    <rect x="720" y="165" width="470" height="315" rx="18" fill="${surfaceFill}" stroke="${inkColor}" stroke-width="5"/>
    <circle cx="955" cy="235" r="34" fill="${bgColor}" stroke="${accentColor}" stroke-width="5"/>
    <path d="M940 235 L951 247 L973 222" fill="none" stroke="${accentColor}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
    ${cardTextBlock}
    <rect x="720" y="505" width="470" height="115" rx="14" fill="${surfaceFill}" stroke="${accentColor}" stroke-width="4.5"/>
    ${focusBlock}
  </g>
</svg>`;
}

/**
 * SVG Thumbnail YouTube 1280x720 dự phòng siêu sắc nét khi LLM gặp sự cố.
 */
export function buildDeterministicThumbnailFallbackSvg(params: {
  headline: string;
  subtitle: string;
  badgeLabel: string;
  theme: SvgThemeColors;
}): string {
  const { headline, subtitle, badgeLabel, theme } = params;
  const { bgColor, inkColor, accentColor, surfaceFill } = theme;
  const headLines = wrapVietnameseLines(headline.toUpperCase(), 14, 3).map(escapeXmlText);
  const subLines = wrapVietnameseLines(subtitle, 32, 2).map(escapeXmlText);

  const headSvg = headLines
    .map((line, idx) => {
      const fill = idx === headLines.length - 1 && headLines.length > 1 ? accentColor : inkColor;
      return `<text x="72" y="${258 + idx * 84}" font-family="'DejaVu Sans', 'Segoe UI', Arial, sans-serif" font-size="68" font-weight="800" fill="${fill}">${line}</text>`;
    })
    .join('\n  ');

  const dividerY = 258 + Math.max(1, headLines.length) * 84 - 16;
  const subSvg = subLines
    .map(
      (line, idx) =>
        `<text x="72" y="${dividerY + 52 + idx * 38}" font-family="'DejaVu Sans', 'Segoe UI', Arial, sans-serif" font-size="28" font-weight="700" fill="${inkColor}">${line}</text>`
    )
    .join('\n  ');

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">
  <rect width="1280" height="720" fill="${bgColor}"/>
  <rect x="0" y="0" width="22" height="720" fill="${accentColor}"/>
  <rect x="72" y="76" width="190" height="52" rx="10" fill="${accentColor}"/>
  <text x="167" y="111" text-anchor="middle" font-family="'DejaVu Sans', 'Segoe UI', Arial, sans-serif" font-size="26" font-weight="800" fill="${surfaceFill}">${escapeXmlText(badgeLabel)}</text>
  ${headSvg}
  <rect x="72" y="${dividerY}" width="180" height="8" rx="4" fill="${accentColor}"/>
  ${subSvg}
  <rect x="700" y="72" width="510" height="576" rx="22" fill="${surfaceFill}" stroke="${inkColor}" stroke-width="5"/>
  <circle cx="955" cy="245" r="58" fill="${surfaceFill}" stroke="${inkColor}" stroke-width="6"/>
  <circle cx="937" cy="236" r="5.5" fill="${inkColor}"/>
  <circle cx="973" cy="236" r="5.5" fill="${inkColor}"/>
  <path d="M936 264 Q955 280 974 264" fill="none" stroke="${inkColor}" stroke-width="5" stroke-linecap="round"/>
  <line x1="955" y1="303" x2="955" y2="470" stroke="${inkColor}" stroke-width="6" stroke-linecap="round"/>
  <polygon points="955,312 945,348 955,380 965,348" fill="${inkColor}"/>
  <path d="M955 352 L880 402 M955 352 L1052 308" stroke="${inkColor}" stroke-width="6" stroke-linecap="round"/>
  <path d="M955 470 L908 585 M955 470 L1002 585" stroke="${inkColor}" stroke-width="6" stroke-linecap="round"/>
  <circle cx="1095" cy="222" r="42" fill="${bgColor}" stroke="${accentColor}" stroke-width="6"/>
  <path d="M1078 222 L1091 236 L1116 208" fill="none" stroke="${accentColor}" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`;
}

/**
 * SVG dự phòng đơn ý (1 micro-shot = 1 hình ảnh rõ ràng trong 3–4 giây) khi 1 beat trong batch bị lỗi XML.
 */
export function buildDeterministicMicroShotSvg(params: {
  chapterHeader: string;
  shortLabel: string;
  phrase: string;
  beatIndex: number;
  totalBeats: number;
  theme: SvgThemeColors;
  vbW: number;
  vbH: number;
}): string {
  const { chapterHeader, shortLabel, phrase, beatIndex, totalBeats, theme, vbW, vbH } = params;
  const { bgColor, inkColor, accentColor, surfaceFill } = theme;
  const cx = Math.round(vbW / 2);
  const labelLines = wrapVietnameseLines(shortLabel || phrase, 22, 2).map(escapeXmlText);
  const phraseLines = wrapVietnameseLines(phrase, 36, 2).map(escapeXmlText);
  const headerSvg = chapterHeader
    ? `<text x="${cx}" y="66" text-anchor="middle" font-family="'DejaVu Sans', 'Segoe UI', Arial, sans-serif" font-size="30" font-weight="700" fill="${inkColor}">${escapeXmlText(chapterHeader.slice(0, 48))}</text>`
    : '';

  // Biểu cảm & tư thế người que thay đổi tự nhiên theo nhịp beatIndex (0..3)
  const pose = beatIndex % 4;
  const mouthPath =
    pose === 0
      ? `M${cx - 18} 274 L${cx + 18} 274`
      : pose === 1
        ? `M${cx - 18} 280 Q${cx} 266 ${cx + 18} 280`
        : `M${cx - 18} 268 Q${cx} 284 ${cx + 18} 268`;
  const armsPath =
    pose === 0
      ? `M${cx} 348 L${cx - 72} 312 M${cx} 348 L${cx + 76} 388`
      : pose === 1
        ? `M${cx} 348 L${cx - 64} 285 M${cx} 348 L${cx + 64} 285`
        : pose === 2
          ? `M${cx} 348 L${cx - 75} 390 M${cx} 348 L${cx + 85} 318`
          : `M${cx} 348 L${cx - 80} 302 M${cx} 348 L${cx + 80} 302`;

  const accentBadge =
    pose === 1
      ? `<path d="M${cx + 95} 210 L${cx + 155} 270 M${cx + 155} 210 L${cx + 95} 270" stroke="${accentColor}" stroke-width="9" stroke-linecap="round"/>`
      : `<circle cx="${cx + 130}" cy="240" r="34" fill="${surfaceFill}" stroke="${accentColor}" stroke-width="5.5"/><path d="M${cx + 116} 240 L${cx + 127} 252 L${cx + 146} 228" fill="none" stroke="${accentColor}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>`;

  const labelSvg = labelLines
    .map(
      (line, idx) =>
        `<text x="${cx}" y="${582 + idx * 38}" text-anchor="middle" font-family="'DejaVu Sans', 'Segoe UI', Arial, sans-serif" font-size="34" font-weight="800" fill="${inkColor}">${line}</text>`
    )
    .join('\n  ');

  const subSvg = phraseLines
    .map(
      (line, idx) =>
        `<text x="${cx}" y="${648 + idx * 28}" text-anchor="middle" font-family="'DejaVu Sans', 'Segoe UI', Arial, sans-serif" font-size="22" font-weight="600" fill="${accentColor}">${line}</text>`
    )
    .join('\n  ');

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${vbW} ${vbH}" width="${vbW}" height="${vbH}">
  <rect width="${vbW}" height="${vbH}" fill="${bgColor}"/>
  ${headerSvg}
  <rect x="${cx - 290}" y="128" width="580" height="390" rx="24" fill="${surfaceFill}" stroke="${inkColor}" stroke-width="4.5"/>
  <circle cx="${cx}" cy="254" r="46" fill="${surfaceFill}" stroke="${inkColor}" stroke-width="5"/>
  <circle cx="${cx - 15}" cy="246" r="4.5" fill="${inkColor}"/>
  <circle cx="${cx + 15}" cy="246" r="4.5" fill="${inkColor}"/>
  <path d="${mouthPath}" fill="none" stroke="${inkColor}" stroke-width="4.5" stroke-linecap="round"/>
  <line x1="${cx}" y1="300" x2="${cx}" y2="432" stroke="${inkColor}" stroke-width="5.5" stroke-linecap="round"/>
  <polygon points="${cx},308 ${cx - 8},338 ${cx},364 ${cx + 8},338" fill="${inkColor}"/>
  <path d="${armsPath}" stroke="${inkColor}" stroke-width="5.5" stroke-linecap="round"/>
  <path d="M${cx} 432 L${cx - 42} 502 M${cx} 432 L${cx + 42} 502" stroke="${inkColor}" stroke-width="5.5" stroke-linecap="round"/>
  ${accentBadge}
  ${labelSvg}
  ${subSvg}
  <text x="${vbW - 70}" y="58" text-anchor="end" font-family="'DejaVu Sans', 'Segoe UI', Arial, sans-serif" font-size="18" font-weight="700" fill="${accentColor}">${beatIndex + 1}/${Math.max(1, totalBeats)}</text>
</svg>`;
}
