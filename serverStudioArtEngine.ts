/**
 * serverStudioArtEngine.ts
 * Bộ dựng hình minh họa Vector chuẩn Studio (Editorial Flat-Vector Explainer Engine).
 *
 * Kiến trúc 2 tầng chống 100% lỗi hình vẽ:
 * - Tầng 1 (AI Art Director trong server.ts): Phân tích từng cụm lời thoại và xuất JSON kịch bản
 *   hình ảnh có cấu trúc (bố cục, tư thế nhân vật, biểu cảm, đạo cụ ẩn dụ, hiệu ứng nhấn, nhãn ngắn).
 * - Tầng 2 (Module này): Dựng SVG chuẩn xác bằng hình học toán học, tỷ lệ nhân vật đồng nhất,
 *   32+ biểu tượng ẩn dụ nhiều lớp sắc nét, phân vùng chữ an toàn 100% (0% vỡ XML, 0% đứt tay chân,
 *   0% chữ đè hình, tương thích tức thì với đổi bảng màu nền).
 */

import { escapeXmlText, type SvgThemeColors } from './serverSvgQuality';

export const STUDIO_COMPOSITIONS = [
  'character_left_prop_right',
  'prop_left_character_right',
  'center_metaphor',
  'split_comparison',
  'cause_effect_flow',
  'two_characters_interaction',
  'character_on_pedestal',
  'checklist_steps',
] as const;
export type StudioComposition = (typeof STUDIO_COMPOSITIONS)[number];

export const STUDIO_POSES = [
  'standing_calm',
  'standing_confident',
  'slumped_sad',
  'overwhelmed_head',
  'pointing_accuse',
  'shield_stance',
  'meditating_zen',
  'thinking_chin',
  'walking_forward',
  'climbing_up',
  'blocking_noise',
  'presenting_idea',
  'arms_crossed_steady',
  'victory_raised',
] as const;
export type StudioPose = (typeof STUDIO_POSES)[number];

export const STUDIO_EXPRESSIONS = [
  'calm',
  'confident',
  'sad',
  'angry',
  'stressed',
  'shocked',
  'thinking',
  'peaceful',
  'determined',
  'hurt',
] as const;
export type StudioExpression = (typeof STUDIO_EXPRESSIONS)[number];

export const STUDIO_PROPS = [
  'boulder_wind',
  'criticism_arrows',
  'mind_shield',
  'storm_cloud',
  'sunrise_horizon',
  'hourglass',
  'balance_scale',
  'brain_focus',
  'mountain_peak',
  'broken_chains',
  'compass',
  'lightbulb',
  'target_bullseye',
  'phone_distraction',
  'clock_time',
  'stoic_scroll',
  'temple_pillar',
  'stairs_growth',
  'mirror_self',
  'brick_wall',
  'flame_forge',
  'anchor_waves',
  'heart_calm',
  'laurel_crown',
  'checklist_board',
  'crowd_chatter',
  'battery_power',
  'key_padlock',
  'crossroads',
  'growing_tree',
  'mask_duality',
  'speech_calm',
] as const;
export type StudioProp = (typeof STUDIO_PROPS)[number];

export const STUDIO_OVERLAYS = [
  'none',
  'big_x_crossout',
  'checkmark_badge',
  'curved_arrow_right',
  'upward_growth_arrow',
  'shield_aura',
  'spark_emphasis',
] as const;
export type StudioOverlay = (typeof STUDIO_OVERLAYS)[number];

export interface StudioShotBlueprint {
  composition: StudioComposition;
  character_pose: StudioPose;
  character_expression: StudioExpression;
  secondary_pose?: StudioPose;
  secondary_expression?: StudioExpression;
  primary_prop: StudioProp;
  secondary_prop?: StudioProp;
  overlay_effect: StudioOverlay;
  caption: string;
  sub_phrase?: string;
  left_badge?: string;
  right_badge?: string;
  chapter_header?: string;
  step_items?: string[];
  beat_index?: number;
  total_beats?: number;
}

export interface StudioThumbnailBlueprint {
  headline: string;
  subtitle: string;
  badgeLabel: string;
  character_pose: StudioPose;
  character_expression: StudioExpression;
  primary_prop: StudioProp;
  overlay_effect: StudioOverlay;
}

const FONT_FAMILY = "'DejaVu Sans', 'Segoe UI', Arial, sans-serif";

function pickEnum<T extends string>(
  raw: unknown,
  allowed: readonly T[],
  fallback: T
): T {
  if (typeof raw === 'string') {
    const norm = raw.trim().toLowerCase() as T;
    if ((allowed as readonly string[]).includes(norm)) {
      return norm;
    }
  }
  return fallback;
}

function wrapTextLines(text: string, maxChars: number, maxLines: number): string[] {
  const cleaned = String(text || '')
    .replace(/[&<>]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (!cleaned) return [];

  const words = cleaned.split(' ');
  const lines: string[] = [];
  let current = '';

  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length > maxChars && current) {
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

function renderMultilineText(
  lines: string[],
  x: number,
  startY: number,
  lineHeight: number,
  fontSize: number,
  fill: string,
  fontWeight = '700',
  anchor: 'middle' | 'start' | 'end' = 'middle'
): string {
  return lines
    .map(
      (line, idx) =>
        `<text x="${x}" y="${startY + idx * lineHeight}" text-anchor="${anchor}" font-family="${FONT_FAMILY}" font-size="${fontSize}" font-weight="${fontWeight}" fill="${fill}">${escapeXmlText(line)}</text>`
    )
    .join('\n');
}

/**
 * Bộ phân tích ngữ nghĩa tiếng Việt & tiếng Anh dự phòng thông minh:
 * Ánh xạ chính xác ý nghĩa câu thoại sang tư thế + biểu tượng + bố cục tương ứng
 * (dùng khi tạo gợi ý mặc định hoặc fallback 0% lỗi).
 */
export function inferSemanticBlueprint(params: {
  phrase: string;
  shortLabel: string;
  imagePrompt?: string;
  chapterHeader?: string;
  layoutType?: string;
  beatIndex?: number;
  totalBeats?: number;
}): StudioShotBlueprint {
  const text = `${params.phrase} ${params.shortLabel} ${params.imagePrompt || ''}`.toLowerCase();
  const idx = params.beatIndex ?? 0;

  // Khớp trực tiếp các hình ảnh ẩn dụ giàu sức gợi
  if (/(đá tảng|hòn đá|tảng đá|boulder|rock|wind|luồng gió|gió thổi)/.test(text)) {
    return {
      composition: 'center_metaphor',
      character_pose: 'arms_crossed_steady',
      character_expression: 'calm',
      primary_prop: 'boulder_wind',
      overlay_effect: 'shield_aura',
      caption: params.shortLabel || 'Gió qua đá tảng',
      sub_phrase: params.phrase,
      chapter_header: params.chapterHeader,
      beat_index: params.beatIndex,
      total_beats: params.totalBeats,
    };
  }

  if (/(chê bai|chỉ trích|công kích|phán xét|xúc phạm|criticism|insult|pointing|shout|gossip|nói xấu)/.test(text)) {
    return {
      composition: 'two_characters_interaction',
      character_pose: 'standing_calm',
      character_expression: 'calm',
      secondary_pose: 'pointing_accuse',
      secondary_expression: 'angry',
      primary_prop: 'criticism_arrows',
      overlay_effect: 'none',
      left_badge: 'Lời công kích',
      right_badge: 'Giữ bình tĩnh',
      caption: params.shortLabel || 'Khi bị chê bai',
      sub_phrase: params.phrase,
      chapter_header: params.chapterHeader,
      beat_index: params.beatIndex,
      total_beats: params.totalBeats,
    };
  }

  if (/(đau khổ|buồn|tổn thương|gục ngã|sụp đổ|tuyệt vọng|sad|suffer|pain|slumped|hurt|cry)/.test(text)) {
    const isNegated = /(thay vì|đừng|không|avoid|instead|stop|no longer|crossed out)/.test(text);
    return {
      composition: 'character_left_prop_right',
      character_pose: 'slumped_sad',
      character_expression: 'sad',
      primary_prop: 'storm_cloud',
      overlay_effect: isNegated ? 'big_x_crossout' : 'none',
      caption: params.shortLabel || (isNegated ? 'Không đau khổ' : 'Nỗi đau nội tâm'),
      sub_phrase: params.phrase,
      chapter_header: params.chapterHeader,
      beat_index: params.beatIndex,
      total_beats: params.totalBeats,
    };
  }

  if (/(tâm trí|vững vàng|bình tĩnh|khiên|lá chắn|phòng thủ|shield|calm mind|steady|inner peace|bất biến)/.test(text)) {
    return {
      composition: 'character_on_pedestal',
      character_pose: 'shield_stance',
      character_expression: 'confident',
      primary_prop: 'mind_shield',
      overlay_effect: 'shield_aura',
      caption: params.shortLabel || 'Tâm trí vững vàng',
      sub_phrase: params.phrase,
      chapter_header: params.chapterHeader,
      beat_index: params.beatIndex,
      total_beats: params.totalBeats,
    };
  }

  if (/(căng thẳng|lo âu|áp lực|quá tải|hoảng loạn|stress|anxious|overwhelm|panic|chaos)/.test(text)) {
    return {
      composition: 'prop_left_character_right',
      character_pose: 'overwhelmed_head',
      character_expression: 'stressed',
      primary_prop: 'storm_cloud',
      overlay_effect: 'big_x_crossout',
      caption: params.shortLabel || 'Áp lực và lo âu',
      sub_phrase: params.phrase,
      chapter_header: params.chapterHeader,
      beat_index: params.beatIndex,
      total_beats: params.totalBeats,
    };
  }

  if (/(kiểm soát|cân bằng|nhị phân|lựa chọn|ngã rẽ|control|balance|scale|dichotomy|choice)/.test(text)) {
    return {
      composition: 'split_comparison',
      character_pose: 'standing_confident',
      character_expression: 'determined',
      primary_prop: 'balance_scale',
      secondary_prop: 'crossroads',
      overlay_effect: 'checkmark_badge',
      left_badge: 'Ngoài tầm kiểm soát',
      right_badge: 'Trong tay bạn',
      caption: params.shortLabel || 'Kiểm soát nội tâm',
      sub_phrase: params.phrase,
      chapter_header: params.chapterHeader,
      beat_index: params.beatIndex,
      total_beats: params.totalBeats,
    };
  }

  if (/(thời gian|đồng hồ|cát|trì hoãn|hôm nay|hiện tại|time|hourglass|clock|procrastin|deadline)/.test(text)) {
    return {
      composition: 'character_left_prop_right',
      character_pose: 'thinking_chin',
      character_expression: 'focused' === ('focused' as string) ? 'determined' : 'determined',
      primary_prop: 'hourglass',
      overlay_effect: 'spark_emphasis',
      caption: params.shortLabel || 'Giá trị thời gian',
      sub_phrase: params.phrase,
      chapter_header: params.chapterHeader,
      beat_index: params.beatIndex,
      total_beats: params.totalBeats,
    };
  }

  if (/(điện thoại|mạng xã hội|dopamine|xao nhãng|ồn ào|phone|social media|distract|noise|scroll)/.test(text)) {
    return {
      composition: 'prop_left_character_right',
      character_pose: 'blocking_noise',
      character_expression: 'determined',
      primary_prop: 'phone_distraction',
      overlay_effect: 'big_x_crossout',
      caption: params.shortLabel || 'Cắt bỏ xao nhãng',
      sub_phrase: params.phrase,
      chapter_header: params.chapterHeader,
      beat_index: params.beatIndex,
      total_beats: params.totalBeats,
    };
  }

  if (/(tập trung|não bộ|suy nghĩ|nhận thức|tư duy|focus|brain|mind|clarity|thought|cognitive)/.test(text)) {
    return {
      composition: 'character_left_prop_right',
      character_pose: 'presenting_idea',
      character_expression: 'confident',
      primary_prop: 'brain_focus',
      overlay_effect: 'spark_emphasis',
      caption: params.shortLabel || 'Rèn luyện tâm trí',
      sub_phrase: params.phrase,
      chapter_header: params.chapterHeader,
      beat_index: params.beatIndex,
      total_beats: params.totalBeats,
    };
  }

  if (/(kỷ luật|bước|tiến lên|phát triển|mục tiêu|đỉnh cao|climb|stairs|goal|growth|mountain|target)/.test(text)) {
    return {
      composition: 'cause_effect_flow',
      character_pose: 'climbing_up',
      character_expression: 'determined',
      primary_prop: 'stairs_growth',
      secondary_prop: 'mountain_peak',
      overlay_effect: 'upward_growth_arrow',
      caption: params.shortLabel || 'Tiến từng bước vững',
      sub_phrase: params.phrase,
      chapter_header: params.chapterHeader,
      beat_index: params.beatIndex,
      total_beats: params.totalBeats,
    };
  }

  if (/(tự do|xiềng xích|buông bỏ|thoát khỏi|rời đi|chain|freedom|let go|break free)/.test(text)) {
    return {
      composition: 'center_metaphor',
      character_pose: 'victory_raised',
      character_expression: 'peaceful',
      primary_prop: 'broken_chains',
      overlay_effect: 'spark_emphasis',
      caption: params.shortLabel || 'Tự do từ bên trong',
      sub_phrase: params.phrase,
      chapter_header: params.chapterHeader,
      beat_index: params.beatIndex,
      total_beats: params.totalBeats,
    };
  }

  if (/(khắc kỷ|marcus|seneca|epictetus|triết lý|cổ đại|sách|stoic|scroll|pillar|wisdom)/.test(text)) {
    return {
      composition: 'character_left_prop_right',
      character_pose: 'presenting_idea',
      character_expression: 'calm',
      primary_prop: 'stoic_scroll',
      secondary_prop: 'temple_pillar',
      overlay_effect: 'spark_emphasis',
      caption: params.shortLabel || 'Triết lý Khắc kỷ',
      sub_phrase: params.phrase,
      chapter_header: params.chapterHeader,
      beat_index: params.beatIndex,
      total_beats: params.totalBeats,
    };
  }

  if (/(thử thách|nghịch cảnh|rào cản|vượt qua|lửa|obstacle|wall|fire|adversity|forge)/.test(text)) {
    return {
      composition: 'cause_effect_flow',
      character_pose: 'walking_forward',
      character_expression: 'determined',
      primary_prop: 'brick_wall',
      secondary_prop: 'flame_forge',
      overlay_effect: 'curved_arrow_right',
      caption: params.shortLabel || 'Nghịch cảnh là đường đi',
      sub_phrase: params.phrase,
      chapter_header: params.chapterHeader,
      beat_index: params.beatIndex,
      total_beats: params.totalBeats,
    };
  }

  if (/(thiền|thở|im lặng|tĩnh lặng|bình an|meditat|breathe|silence|stillness|anchor)/.test(text)) {
    return {
      composition: 'character_on_pedestal',
      character_pose: 'meditating_zen',
      character_expression: 'peaceful',
      primary_prop: 'anchor_waves',
      overlay_effect: 'shield_aura',
      caption: params.shortLabel || 'Tĩnh lặng nội tâm',
      sub_phrase: params.phrase,
      chapter_header: params.chapterHeader,
      beat_index: params.beatIndex,
      total_beats: params.totalBeats,
    };
  }

  if (/(tổng kết|danh sách|3 bước|4 nguyên lý|áp dụng|thực hành|summary|checklist|steps)/.test(text) || params.layoutType === 'summary_list' || params.layoutType === 'three_branches') {
    return {
      composition: 'checklist_steps',
      character_pose: 'presenting_idea',
      character_expression: 'confident',
      primary_prop: 'checklist_board',
      overlay_effect: 'checkmark_badge',
      caption: params.shortLabel || 'Áp dụng ngay hôm nay',
      sub_phrase: params.phrase,
      chapter_header: params.chapterHeader,
      beat_index: params.beatIndex,
      total_beats: params.totalBeats,
    };
  }

  // Đa dạng hóa theo beatIndex để 4 cảnh liên tiếp luôn thay đổi nhịp hình
  const cycleDefaults: Array<Pick<StudioShotBlueprint, 'composition' | 'character_pose' | 'character_expression' | 'primary_prop' | 'overlay_effect'>> = [
    {
      composition: 'character_left_prop_right',
      character_pose: 'thinking_chin',
      character_expression: 'thinking',
      primary_prop: 'compass',
      overlay_effect: 'spark_emphasis',
    },
    {
      composition: 'split_comparison',
      character_pose: 'arms_crossed_steady',
      character_expression: 'determined',
      primary_prop: 'balance_scale',
      overlay_effect: 'curved_arrow_right',
    },
    {
      composition: 'center_metaphor',
      character_pose: 'standing_confident',
      character_expression: 'calm',
      primary_prop: 'lightbulb',
      overlay_effect: 'upward_growth_arrow',
    },
    {
      composition: 'character_on_pedestal',
      character_pose: 'standing_confident',
      character_expression: 'confident',
      primary_prop: 'laurel_crown',
      overlay_effect: 'checkmark_badge',
    },
  ];
  const preset = cycleDefaults[Math.abs(idx) % cycleDefaults.length];
  return {
    ...preset,
    caption: params.shortLabel || 'Góc nhìn Khắc kỷ',
    sub_phrase: params.phrase,
    chapter_header: params.chapterHeader,
    beat_index: params.beatIndex,
    total_beats: params.totalBeats,
  };
}

/**
 * Chuẩn hóa blueprint từ JSON của AI Art Director để đảm bảo 100% enum hợp lệ.
 */
export function normalizeStudioBlueprint(
  raw: Record<string, unknown> | undefined,
  fallbackContext: {
    phrase: string;
    shortLabel: string;
    imagePrompt?: string;
    chapterHeader?: string;
    layoutType?: string;
    beatIndex?: number;
    totalBeats?: number;
  }
): StudioShotBlueprint {
  const inferred = inferSemanticBlueprint(fallbackContext);
  if (!raw || typeof raw !== 'object') return inferred;

  const stepItems = Array.isArray(raw.step_items)
    ? raw.step_items
        .map((x) => String(x || '').replace(/[&<>]/g, ' ').trim().slice(0, 34))
        .filter(Boolean)
        .slice(0, 3)
    : undefined;

  return {
    composition: pickEnum(raw.composition, STUDIO_COMPOSITIONS, inferred.composition),
    character_pose: pickEnum(raw.character_pose, STUDIO_POSES, inferred.character_pose),
    character_expression: pickEnum(raw.character_expression, STUDIO_EXPRESSIONS, inferred.character_expression),
    secondary_pose: raw.secondary_pose
      ? pickEnum(raw.secondary_pose, STUDIO_POSES, inferred.secondary_pose || 'pointing_accuse')
      : inferred.secondary_pose,
    secondary_expression: raw.secondary_expression
      ? pickEnum(raw.secondary_expression, STUDIO_EXPRESSIONS, inferred.secondary_expression || 'angry')
      : inferred.secondary_expression,
    primary_prop: pickEnum(raw.primary_prop, STUDIO_PROPS, inferred.primary_prop),
    secondary_prop: raw.secondary_prop
      ? pickEnum(raw.secondary_prop, STUDIO_PROPS, inferred.secondary_prop || 'sunrise_horizon')
      : inferred.secondary_prop,
    overlay_effect: pickEnum(raw.overlay_effect, STUDIO_OVERLAYS, inferred.overlay_effect),
    caption:
      String(raw.caption || fallbackContext.shortLabel || inferred.caption)
        .replace(/[&<>]/g, ' ')
        .trim()
        .slice(0, 44) || inferred.caption,
    sub_phrase: fallbackContext.phrase,
    left_badge: raw.left_badge
      ? String(raw.left_badge).replace(/[&<>]/g, ' ').trim().slice(0, 22)
      : inferred.left_badge,
    right_badge: raw.right_badge
      ? String(raw.right_badge).replace(/[&<>]/g, ' ').trim().slice(0, 22)
      : inferred.right_badge,
    chapter_header: fallbackContext.chapterHeader,
    step_items: stepItems,
    beat_index: fallbackContext.beatIndex,
    total_beats: fallbackContext.totalBeats,
  };
}

// ============================================================================
// 1. BỘ VẼ NHÂN VẬT EDITORIAL EXPLAINER (TỶ LỆ CHUẨN, BIỂU CẢM SỐNG ĐỘNG, 0% ĐỨT NÉT)
//    Hệ tọa độ cục bộ chuẩn hóa: tâm chân ở (0, 175), đỉnh đầu ở (0, -145), cao ~320px
// ============================================================================

function renderFaceExpression(
  expression: StudioExpression,
  ink: string,
  accent: string,
  surface: string
): string {
  switch (expression) {
    case 'angry':
      return `
        <path d="M-24 -94 L-7 -86 M24 -94 L7 -86" stroke="${ink}" stroke-width="4.5" stroke-linecap="round"/>
        <circle cx="-14" cy="-78" r="4.5" fill="${ink}"/>
        <circle cx="14" cy="-78" r="4.5" fill="${ink}"/>
        <path d="M-16 -56 Q0 -69 16 -56" fill="${accent}" fill-opacity="0.22" stroke="${ink}" stroke-width="4" stroke-linecap="round"/>
        <path d="M26 -110 L35 -101 M35 -110 L26 -101" stroke="${accent}" stroke-width="3.2" stroke-linecap="round"/>
      `;
    case 'sad':
    case 'hurt':
      return `
        <path d="M-24 -88 Q-15 -94 -7 -90 M24 -88 Q15 -94 7 -90" fill="none" stroke="${ink}" stroke-width="3.6" stroke-linecap="round"/>
        <circle cx="-14" cy="-78" r="4.2" fill="${ink}"/>
        <circle cx="14" cy="-78" r="4.2" fill="${ink}"/>
        <path d="M-15 -54 Q0 -66 15 -54" fill="none" stroke="${ink}" stroke-width="4" stroke-linecap="round"/>
        <path d="M-20 -68 Q-24 -58 -19 -54 Q-14 -58 -20 -68 Z" fill="${accent}" fill-opacity="0.8"/>
      `;
    case 'stressed':
      return `
        <path d="M-23 -93 L-8 -88 M23 -93 L8 -88" stroke="${ink}" stroke-width="3.8" stroke-linecap="round"/>
        <circle cx="-14" cy="-78" r="5" fill="${surface}" stroke="${ink}" stroke-width="3.2"/>
        <circle cx="-14" cy="-78" r="2" fill="${ink}"/>
        <circle cx="14" cy="-78" r="5" fill="${surface}" stroke="${ink}" stroke-width="3.2"/>
        <circle cx="14" cy="-78" r="2" fill="${ink}"/>
        <path d="M-16 -57 Q-8 -63 0 -57 Q8 -51 16 -57" fill="none" stroke="${ink}" stroke-width="3.8" stroke-linecap="round"/>
        <path d="M32 -95 Q38 -84 32 -78 Q26 -84 32 -95 Z" fill="${accent}"/>
      `;
    case 'shocked':
      return `
        <path d="M-23 -96 Q-14 -103 -6 -96 M6 -96 Q14 -103 23 -96" fill="none" stroke="${ink}" stroke-width="3.5" stroke-linecap="round"/>
        <circle cx="-14" cy="-80" r="5.5" fill="${surface}" stroke="${ink}" stroke-width="3.2"/>
        <circle cx="-14" cy="-80" r="2.2" fill="${ink}"/>
        <circle cx="14" cy="-80" r="5.5" fill="${surface}" stroke="${ink}" stroke-width="3.2"/>
        <circle cx="14" cy="-80" r="2.2" fill="${ink}"/>
        <ellipse cx="0" cy="-57" rx="9" ry="11" fill="${accent}" fill-opacity="0.2" stroke="${ink}" stroke-width="3.8"/>
      `;
    case 'peaceful':
      return `
        <path d="M-22 -78 Q-14 -72 -6 -78 M6 -78 Q14 -72 22 -78" fill="none" stroke="${ink}" stroke-width="4" stroke-linecap="round"/>
        <path d="M-13 -58 Q0 -49 13 -58" fill="none" stroke="${ink}" stroke-width="3.8" stroke-linecap="round"/>
      `;
    case 'thinking':
      return `
        <path d="M-22 -91 Q-14 -96 -6 -91 M7 -94 L22 -91" fill="none" stroke="${ink}" stroke-width="3.5" stroke-linecap="round"/>
        <circle cx="-13" cy="-79" r="4.2" fill="${ink}"/>
        <circle cx="15" cy="-79" r="4.2" fill="${ink}"/>
        <path d="M-9 -57 Q2 -55 12 -60" fill="none" stroke="${ink}" stroke-width="3.8" stroke-linecap="round"/>
      `;
    case 'determined':
      return `
        <path d="M-23 -91 L-7 -88 M23 -91 L7 -88" stroke="${ink}" stroke-width="4.2" stroke-linecap="round"/>
        <circle cx="-14" cy="-78" r="4.5" fill="${ink}"/>
        <circle cx="14" cy="-78" r="4.5" fill="${ink}"/>
        <line x1="-13" y1="-57" x2="13" y2="-57" stroke="${ink}" stroke-width="4.2" stroke-linecap="round"/>
      `;
    case 'confident':
      return `
        <path d="M-22 -92 Q-14 -97 -6 -92 M6 -92 Q14 -97 22 -92" fill="none" stroke="${ink}" stroke-width="3.6" stroke-linecap="round"/>
        <circle cx="-14" cy="-79" r="4.6" fill="${ink}"/>
        <circle cx="-12.5" cy="-80.5" r="1.4" fill="${surface}"/>
        <circle cx="14" cy="-79" r="4.6" fill="${ink}"/>
        <circle cx="15.5" cy="-80.5" r="1.4" fill="${surface}"/>
        <path d="M-16 -60 Q0 -46 16 -60" fill="none" stroke="${ink}" stroke-width="4.2" stroke-linecap="round"/>
      `;
    default: // calm
      return `
        <circle cx="-14" cy="-79" r="4.5" fill="${ink}"/>
        <circle cx="-12.5" cy="-80.5" r="1.3" fill="${surface}"/>
        <circle cx="14" cy="-79" r="4.5" fill="${ink}"/>
        <circle cx="15.5" cy="-80.5" r="1.3" fill="${surface}"/>
        <path d="M-13 -59 Q0 -50 13 -59" fill="none" stroke="${ink}" stroke-width="4" stroke-linecap="round"/>
      `;
  }
}

/**
 * Vẽ nhân vật Explainer chuẩn studio tại tâm (x, y), tỷ lệ scale, hướng flipX (-1 hoặc 1).
 * Nhân vật có đầu bo tròn + tóc stylized + thân áo tối giản có cà vạt màu nhấn + tay chân khớp nối chuẩn + bóng mặt đất.
 */
function renderStudioCharacter(params: {
  x: number;
  y: number;
  scale?: number;
  flipX?: boolean;
  pose: StudioPose;
  expression: StudioExpression;
  theme: SvgThemeColors;
  accentTie?: boolean;
}): string {
  const { x, y, scale = 1, flipX = false, pose, expression, theme, accentTie = true } = params;
  const { inkColor: ink, accentColor: accent, surfaceFill: surface } = theme;
  const tieColor = accentTie ? accent : ink;
  const sx = flipX ? -scale : scale;

  // Tư thế ngồi thiền có bố cục thân & chân riêng
  if (pose === 'meditating_zen') {
    return `<g transform="translate(${x}, ${y}) scale(${sx}, ${scale})">
      <ellipse cx="0" cy="146" rx="88" ry="15" fill="${ink}" fill-opacity="0.12"/>
      <circle cx="0" cy="-25" r="120" fill="${accent}" fill-opacity="0.06" stroke="${accent}" stroke-width="2.5" stroke-dasharray="10 8"/>
      <!-- Chân xếp bằng -->
      <path d="M-24 92 Q-78 104 -68 132 Q-42 146 8 134" fill="none" stroke="${ink}" stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M24 92 Q78 104 68 132 Q42 146 -8 134" fill="none" stroke="${ink}" stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/>
      <!-- Thân áo gọn -->
      <path d="M-32 8 Q0 -6 32 8 L38 96 Q0 108 -38 96 Z" fill="${surface}" stroke="${ink}" stroke-width="5" stroke-linejoin="round"/>
      <polygon points="0,4 -7,34 0,60 7,34" fill="${tieColor}"/>
      <!-- Hai tay đặt lên gối -->
      <path d="M-30 22 Q-66 56 -56 106 L-34 114" fill="none" stroke="${ink}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M30 22 Q66 56 56 106 L34 114" fill="none" stroke="${ink}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="-32" cy="114" r="7" fill="${surface}" stroke="${ink}" stroke-width="4"/>
      <circle cx="32" cy="114" r="7" fill="${surface}" stroke="${ink}" stroke-width="4"/>
      <!-- Cổ + Đầu -->
      <rect x="-8" y="-32" width="16" height="32" rx="6" fill="${surface}" stroke="${ink}" stroke-width="4.5"/>
      <circle cx="0" cy="-76" r="46" fill="${surface}" stroke="${ink}" stroke-width="5.2"/>
      <path d="M-36 -104 Q-14 -132 18 -124 Q38 -118 42 -96 Q16 -112 -14 -108 Q-28 -106 -36 -104 Z" fill="${ink}"/>
      ${renderFaceExpression(expression, ink, accent, surface)}
    </g>`;
  }

  // Tính toán độ nghiêng đầu / thân + tay + chân theo từng pose
  let headShiftX = 0;
  let headShiftY = 0;
  let torsoSkew = '';
  let leftArm = `M-32 18 L-68 68 L-58 104`;
  let rightArm = `M32 18 L68 68 L58 104`;
  let leftHand = { cx: -58, cy: 104 };
  let rightHand = { cx: 58, cy: 104 };
  let legsSvg = `
    <path d="M-16 102 L-24 166 L-40 168" fill="none" stroke="${ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M16 102 L24 166 L42 168" fill="none" stroke="${ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
  `;
  let extraProp = '';

  switch (pose) {
    case 'standing_confident':
      leftArm = `M-32 18 L-66 56 L-34 84`;
      rightArm = `M32 18 L66 56 L34 84`;
      leftHand = { cx: -34, cy: 84 };
      rightHand = { cx: 34, cy: 84 };
      legsSvg = `
        <path d="M-16 102 L-32 166 L-50 168" fill="none" stroke="${ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M16 102 L32 166 L50 168" fill="none" stroke="${ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
      `;
      break;

    case 'slumped_sad':
      headShiftX = 12;
      headShiftY = 14;
      torsoSkew = 'rotate(8, 0, 60)';
      leftArm = `M-26 26 L-44 82 L-30 124`;
      rightArm = `M30 28 L46 84 L38 126`;
      leftHand = { cx: -30, cy: 124 };
      rightHand = { cx: 38, cy: 126 };
      break;

    case 'overwhelmed_head':
      headShiftY = 6;
      leftArm = `M-32 18 L-66 -26 L-44 -76`;
      rightArm = `M32 18 L66 -26 L44 -76`;
      leftHand = { cx: -44, cy: -76 };
      rightHand = { cx: 44, cy: -76 };
      extraProp = `
        <path d="M-64 -116 Q-42 -136 -20 -122 M20 -124 Q44 -140 66 -116" fill="none" stroke="${accent}" stroke-width="4" stroke-linecap="round"/>
        <path d="M-56 -138 L-44 -128 M56 -138 L44 -128 M0 -144 L0 -132" stroke="${accent}" stroke-width="4" stroke-linecap="round"/>
      `;
      break;

    case 'pointing_accuse':
      headShiftX = 8;
      torsoSkew = 'rotate(6, 0, 70)';
      leftArm = `M-30 22 L-56 64 L-32 82`;
      rightArm = `M32 16 L84 8 L122 4`;
      leftHand = { cx: -32, cy: 82 };
      rightHand = { cx: 122, cy: 4 };
      legsSvg = `
        <path d="M-16 102 L-36 166 L-54 168" fill="none" stroke="${ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M16 102 L38 166 L58 168" fill="none" stroke="${ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
      `;
      extraProp = `
        <path d="M62 -98 L82 -108 M66 -78 L90 -80 M62 -58 L82 -50" stroke="${accent}" stroke-width="4.5" stroke-linecap="round"/>
      `;
      break;

    case 'shield_stance':
      leftArm = `M-32 20 L-58 64 L-38 92`;
      rightArm = `M32 18 L76 32 L92 14`;
      leftHand = { cx: -38, cy: 92 };
      rightHand = { cx: 92, cy: 14 };
      extraProp = `
        <path d="M88 -34 L132 -20 L128 42 Q108 78 88 92 Q68 78 64 42 L68 -20 Z" fill="${surface}" stroke="${accent}" stroke-width="6" stroke-linejoin="round"/>
        <path d="M88 -14 L112 -5 L110 34 Q98 56 88 66 Q78 56 76 34 L78 -5 Z" fill="${accent}" fill-opacity="0.18"/>
        <path d="M77 24 L86 34 L104 12" fill="none" stroke="${accent}" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round"/>
      `;
      break;

    case 'thinking_chin':
      leftArm = `M-32 22 L-54 70 L-22 80`;
      rightArm = `M32 20 L58 18 L18 -34`;
      leftHand = { cx: -22, cy: 80 };
      rightHand = { cx: 18, cy: -34 };
      extraProp = `
        <circle cx="64" cy="-110" r="6" fill="${accent}" fill-opacity="0.4"/>
        <circle cx="80" cy="-126" r="9" fill="${accent}" fill-opacity="0.65"/>
      `;
      break;

    case 'walking_forward':
      torsoSkew = 'rotate(5, 0, 70)';
      leftArm = `M-30 22 L-62 58 L-48 92`;
      rightArm = `M32 20 L68 48 L88 26`;
      leftHand = { cx: -48, cy: 92 };
      rightHand = { cx: 88, cy: 26 };
      legsSvg = `
        <path d="M-12 102 L-48 158 L-66 154" fill="none" stroke="${ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M16 102 L48 164 L68 166" fill="none" stroke="${ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
      `;
      break;

    case 'climbing_up':
      torsoSkew = 'rotate(7, 0, 60)';
      leftArm = `M-30 22 L-58 48 L-44 82`;
      rightArm = `M32 16 L76 -16 L96 -42`;
      leftHand = { cx: -44, cy: 82 };
      rightHand = { cx: 96, cy: -42 };
      legsSvg = `
        <path d="M-14 102 L-38 166 L-56 168" fill="none" stroke="${ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M16 100 L54 124 L42 158 L62 158" fill="none" stroke="${ink}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
      `;
      break;

    case 'blocking_noise':
      leftArm = `M-32 20 L-60 66 L-44 96`;
      rightArm = `M32 16 L84 6 L108 -18`;
      leftHand = { cx: -44, cy: 96 };
      rightHand = { cx: 108, cy: -18 };
      extraProp = `
        <path d="M118 -40 L118 8" stroke="${accent}" stroke-width="6" stroke-linecap="round"/>
        <path d="M132 -32 L132 0" stroke="${accent}" stroke-width="4" stroke-linecap="round" stroke-opacity="0.55"/>
      `;
      break;

    case 'presenting_idea':
      leftArm = `M-32 22 L-56 70 L-42 102`;
      rightArm = `M32 16 L82 -6 L112 -32`;
      leftHand = { cx: -42, cy: 102 };
      rightHand = { cx: 112, cy: -32 };
      break;

    case 'arms_crossed_steady':
      leftArm = `M-32 18 L-54 58 L22 52`;
      rightArm = `M32 18 L54 58 L-22 64`;
      leftHand = { cx: 22, cy: 52 };
      rightHand = { cx: -22, cy: 64 };
      break;

    case 'victory_raised':
      leftArm = `M-32 16 L-72 -26 L-64 -76`;
      rightArm = `M32 16 L72 -26 L64 -76`;
      leftHand = { cx: -64, cy: -76 };
      rightHand = { cx: 64, cy: -76 };
      extraProp = `
        <path d="M-92 -94 L-78 -86 M92 -94 L78 -86 M0 -144 L0 -128" stroke="${accent}" stroke-width="4.5" stroke-linecap="round"/>
      `;
      break;

    default: // standing_calm
      leftArm = `M-32 20 L-58 68 L-48 102`;
      rightArm = `M32 20 L68 54 L92 38`;
      leftHand = { cx: -48, cy: 102 };
      rightHand = { cx: 92, cy: 38 };
      break;
  }

  return `<g transform="translate(${x}, ${y}) scale(${sx}, ${scale})">
    <!-- Bóng tiếp đất mềm chống cảm giác lơ lửng -->
    <ellipse cx="0" cy="172" rx="68" ry="12" fill="${ink}" fill-opacity="0.12"/>
    <!-- Chân có khớp gối & giày -->
    ${legsSvg}
    <!-- Thân trên (áo tối giản + cà vạt điểm nhấn) -->
    <g transform="${torsoSkew}">
      <!-- Cánh tay sau -->
      <path d="${leftArm}" fill="none" stroke="${ink}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="${leftHand.cx}" cy="${leftHand.cy}" r="7.5" fill="${surface}" stroke="${ink}" stroke-width="4"/>
      <!-- Thân áo -->
      <path d="M-34 8 Q0 -6 34 8 L28 104 Q0 112 -28 104 Z" fill="${surface}" stroke="${ink}" stroke-width="5.2" stroke-linejoin="round"/>
      <!-- Cổ áo chữ V & Cà vạt -->
      <path d="M-14 4 L0 20 L14 4" fill="none" stroke="${ink}" stroke-width="3.5" stroke-linejoin="round"/>
      <polygon points="0,14 -8,44 0,76 8,44" fill="${tieColor}"/>
      <!-- Cánh tay trước -->
      <path d="${rightArm}" fill="none" stroke="${ink}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="${rightHand.cx}" cy="${rightHand.cy}" r="7.5" fill="${surface}" stroke="${ink}" stroke-width="4"/>
      <!-- Cổ + Đầu + Tóc -->
      <g transform="translate(${headShiftX}, ${headShiftY})">
        <rect x="-8" y="-32" width="16" height="34" rx="6" fill="${surface}" stroke="${ink}" stroke-width="4.5"/>
        <circle cx="0" cy="-76" r="46" fill="${surface}" stroke="${ink}" stroke-width="5.2"/>
        <path d="M-38 -102 Q-18 -134 18 -126 Q38 -120 44 -94 Q18 -110 -12 -106 Q-28 -104 -38 -102 Z" fill="${ink}"/>
        ${renderFaceExpression(expression, ink, accent, surface)}
      </g>
      ${extraProp}
    </g>
  </g>`;
}

// ============================================================================
// 2. THƯ VIỆN 32 ĐẠO CỤ & ẨN DỤ HÌNH ẢNH VẼ TAY CHUẨN STUDIO (TÂM 0,0 · KÍCH THƯỚC ~240x240)
// ============================================================================

function renderStudioProp(
  prop: StudioProp,
  x: number,
  y: number,
  scale: number,
  theme: SvgThemeColors
): string {
  const { bgColor: bg, inkColor: ink, accentColor: accent, surfaceFill: surface } = theme;
  let inner = '';

  switch (prop) {
    case 'boulder_wind':
      inner = `
        <ellipse cx="10" cy="108" rx="130" ry="18" fill="${ink}" fill-opacity="0.14"/>
        <!-- Luồng gió xoáy thổi mạnh từ trái sang nhưng vòng qua tảng đá -->
        <path d="M-195 -46 C-125 -46 -95 -112 -10 -116 C65 -120 120 -78 188 -82" fill="none" stroke="${accent}" stroke-width="6.5" stroke-linecap="round"/>
        <path d="M168 -96 L192 -82 L170 -68" fill="none" stroke="${accent}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M-185 8 C-132 8 -108 -68 -14 -76 C70 -84 128 -26 178 -30" fill="none" stroke="${accent}" stroke-width="5" stroke-linecap="round" stroke-opacity="0.72"/>
        <path d="M-168 58 C-124 58 -106 34 -88 18" fill="none" stroke="${accent}" stroke-width="4.5" stroke-linecap="round" stroke-dasharray="12 10"/>
        <path d="M126 32 C154 32 178 24 196 10" fill="none" stroke="${accent}" stroke-width="4.5" stroke-linecap="round"/>
        <!-- Tảng đá tảng lớn nhiều mặt cắt vững chãi -->
        <polygon points="-108,104 -92,-6 -34,-74 48,-66 104,-4 116,104" fill="${surface}" stroke="${ink}" stroke-width="6" stroke-linejoin="round"/>
        <polygon points="-34,-74 14,-8 -12,104 -108,104 -92,-6" fill="${ink}" fill-opacity="0.09"/>
        <polygon points="48,-66 104,-4 116,104 42,104 54,18" fill="${ink}" fill-opacity="0.15"/>
        <path d="M-34 -74 L14 -8 L-12 104 M48 -66 L14 -8 L98 28" fill="none" stroke="${ink}" stroke-width="4" stroke-linejoin="round"/>
        <path d="M-54 36 L-26 22 M36 56 L72 44" stroke="${ink}" stroke-width="3.5" stroke-linecap="round" stroke-opacity="0.6"/>
      `;
      break;

    case 'criticism_arrows':
      inner = `
        <!-- 3 bong bóng lời chỉ trích sắc nhọn bay tới -->
        <g transform="translate(-52, -74)">
          <rect x="-78" y="-34" width="156" height="62" rx="14" fill="${surface}" stroke="${ink}" stroke-width="5"/>
          <polygon points="62,24 94,38 72,8" fill="${surface}" stroke="${ink}" stroke-width="5" stroke-linejoin="round"/>
          <path d="M-46 -6 L-36 12 M-28 -10 L-28 8 M-28 16 L-28 18 M-6 -8 L12 10 M12 -8 L-6 10 M32 -12 L26 12 M44 -12 L38 12" stroke="${accent}" stroke-width="5" stroke-linecap="round"/>
        </g>
        <g transform="translate(-82, 24)">
          <rect x="-66" y="-28" width="132" height="52" rx="12" fill="${surface}" stroke="${ink}" stroke-width="4.5"/>
          <polygon points="50,18 78,30 58,4" fill="${surface}" stroke="${ink}" stroke-width="4.5" stroke-linejoin="round"/>
          <line x1="-38" y1="-4" x2="28" y2="-4" stroke="${ink}" stroke-width="4.5" stroke-linecap="round"/>
          <line x1="-38" y1="10" x2="8" y2="10" stroke="${accent}" stroke-width="4.5" stroke-linecap="round"/>
        </g>
        <!-- Mũi tên công kích sắc nhọn -->
        <path d="M-128 -14 L94 -14" stroke="${accent}" stroke-width="6.5" stroke-linecap="round"/>
        <polygon points="114,-14 84,-28 90,-14 84,0" fill="${accent}"/>
        <path d="M-104 82 L76 48" stroke="${accent}" stroke-width="5.5" stroke-linecap="round"/>
        <polygon points="96,44 66,36 74,48 70,62" fill="${accent}"/>
      `;
      break;

    case 'mind_shield':
      inner = `
        <circle cx="0" cy="-2" r="118" fill="${accent}" fill-opacity="0.08" stroke="${accent}" stroke-width="3" stroke-dasharray="10 8"/>
        <circle cx="0" cy="-2" r="94" fill="none" stroke="${accent}" stroke-width="2.5" stroke-opacity="0.45"/>
        <!-- Khiên khắc kỷ nhiều lớp -->
        <path d="M0 -98 L82 -66 L74 28 Q56 84 0 112 Q-56 84 -74 28 L-82 -66 Z" fill="${surface}" stroke="${ink}" stroke-width="6" stroke-linejoin="round"/>
        <path d="M0 -76 L62 -52 L56 22 Q42 64 0 88 Q-42 64 -56 22 L-62 -52 Z" fill="${accent}" fill-opacity="0.14" stroke="${accent}" stroke-width="4.5" stroke-linejoin="round"/>
        <!-- Biểu tượng tâm trí cân bằng bên trong -->
        <circle cx="0" cy="0" r="28" fill="${surface}" stroke="${accent}" stroke-width="4.5"/>
        <path d="M-12 0 L-3 10 L15 -10" fill="none" stroke="${accent}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
      `;
      break;

    case 'storm_cloud':
      inner = `
        <ellipse cx="0" cy="108" rx="92" ry="12" fill="${ink}" fill-opacity="0.1"/>
        <!-- Đám mây bão nhiều lớp -->
        <path d="M-86 14 Q-114 14 -114 -16 Q-114 -44 -86 -48 Q-76 -88 -34 -92 Q8 -96 32 -66 Q66 -74 90 -46 Q116 -38 112 -8 Q110 14 82 14 Z" fill="${surface}" stroke="${ink}" stroke-width="6" stroke-linejoin="round"/>
        <path d="M-82 14 Q-108 14 -108 -14 Q-108 -36 -84 -42 Q-74 -78 -34 -82 Q4 -86 28 -58" fill="${ink}" fill-opacity="0.08"/>
        <!-- Tia sét màu nhấn & giọt mưa -->
        <polygon points="6,14 -24,62 2,62 -14,108 32,48 6,48 22,14" fill="${accent}" stroke="${ink}" stroke-width="3.5" stroke-linejoin="round"/>
        <line x1="-68" y1="34" x2="-82" y2="74" stroke="${ink}" stroke-width="4.5" stroke-linecap="round"/>
        <line x1="-42" y1="42" x2="-54" y2="82" stroke="${ink}" stroke-width="4.5" stroke-linecap="round"/>
        <line x1="56" y1="34" x2="42" y2="74" stroke="${ink}" stroke-width="4.5" stroke-linecap="round"/>
        <line x1="82" y1="40" x2="70" y2="76" stroke="${ink}" stroke-width="4.5" stroke-linecap="round"/>
      `;
      break;

    case 'sunrise_horizon':
      inner = `
        <!-- Hào quang bình minh -->
        <circle cx="0" cy="24" r="76" fill="${accent}" fill-opacity="0.16" stroke="${accent}" stroke-width="5"/>
        <path d="M0 -88 L0 -64 M-82 -52 L-64 -34 M82 -52 L64 -34 M-112 18 L-88 18 M112 18 L88 18" stroke="${accent}" stroke-width="5.5" stroke-linecap="round"/>
        <!-- Đồi chân trời nhiều lớp -->
        <path d="M-136 68 Q-58 18 14 58 Q74 26 136 68 L136 102 L-136 102 Z" fill="${surface}" stroke="${ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <path d="M-136 86 Q-36 52 54 84 Q102 68 136 86" fill="none" stroke="${ink}" stroke-width="4" stroke-linecap="round"/>
      `;
      break;

    case 'hourglass':
      inner = `
        <ellipse cx="0" cy="112" rx="76" ry="12" fill="${ink}" fill-opacity="0.12"/>
        <!-- Khung gỗ trên & dưới -->
        <rect x="-76" y="-102" width="152" height="18" rx="6" fill="${ink}"/>
        <rect x="-76" y="84" width="152" height="18" rx="6" fill="${ink}"/>
        <!-- Thân thủy tinh -->
        <path d="M-58 -84 C-58 -24 -12 -14 -8 0 C-12 14 -58 24 -58 84 L58 84 C58 24 12 14 8 0 C12 -14 58 -24 58 -84 Z" fill="${surface}" stroke="${ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <!-- Cát chảy màu nhấn -->
        <path d="M-36 -48 L36 -48 Q16 -14 0 -8 Q-16 -14 -36 -48 Z" fill="${accent}" fill-opacity="0.82"/>
        <line x1="0" y1="-6" x2="0" y2="54" stroke="${accent}" stroke-width="4.5" stroke-dasharray="6 5" stroke-linecap="round"/>
        <path d="M-44 82 Q0 32 44 82 Z" fill="${accent}" fill-opacity="0.88"/>
      `;
      break;

    case 'balance_scale':
      inner = `
        <ellipse cx="0" cy="108" rx="82" ry="12" fill="${ink}" fill-opacity="0.12"/>
        <rect x="-46" y="92" width="92" height="14" rx="5" fill="${ink}"/>
        <line x1="0" y1="-78" x2="0" y2="94" stroke="${ink}" stroke-width="7" stroke-linecap="round"/>
        <circle cx="0" cy="-78" r="12" fill="${accent}" stroke="${ink}" stroke-width="4.5"/>
        <!-- Thanh cân ngang -->
        <line x1="-102" y1="-58" x2="102" y2="-58" stroke="${ink}" stroke-width="6.5" stroke-linecap="round"/>
        <!-- Đĩa trái -->
        <path d="M-92 -58 L-120 18 L-64 18 Z" fill="none" stroke="${ink}" stroke-width="3.8" stroke-linejoin="round"/>
        <path d="M-126 18 Q-92 48 -58 18 Z" fill="${surface}" stroke="${ink}" stroke-width="5"/>
        <!-- Đĩa phải -->
        <path d="M92 -58 L64 18 L120 18 Z" fill="none" stroke="${ink}" stroke-width="3.8" stroke-linejoin="round"/>
        <path d="M58 18 Q92 48 126 18 Z" fill="${accent}" fill-opacity="0.24" stroke="${accent}" stroke-width="5"/>
        <circle cx="92" cy="4" r="13" fill="${accent}"/>
      `;
      break;

    case 'brain_focus':
      inner = `
        <circle cx="0" cy="0" r="102" fill="${accent}" fill-opacity="0.08" stroke="${accent}" stroke-width="3" stroke-dasharray="10 8"/>
        <!-- Bán cầu não tối giản sắc nét -->
        <path d="M-8 -76 C-56 -78 -86 -42 -78 -4 C-94 24 -70 72 -26 70 L-8 70 Z" fill="${surface}" stroke="${ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <path d="M8 -76 C56 -78 86 -42 78 -4 C94 24 70 72 26 70 L8 70 Z" fill="${surface}" stroke="${ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <!-- Đường nếp gấp tinh gọn -->
        <path d="M-54 -28 Q-32 -40 -22 -18 M-58 20 Q-34 8 -22 32 M54 -28 Q32 -40 22 -18 M58 20 Q34 8 22 32" fill="none" stroke="${ink}" stroke-width="4" stroke-linecap="round"/>
        <!-- Tâm điểm tập trung -->
        <circle cx="0" cy="-2" r="26" fill="${surface}" stroke="${accent}" stroke-width="5"/>
        <circle cx="0" cy="-2" r="10" fill="${accent}"/>
      `;
      break;

    case 'mountain_peak':
      inner = `
        <ellipse cx="0" cy="104" rx="132" ry="14" fill="${ink}" fill-opacity="0.12"/>
        <!-- Ngọn núi phụ & chính -->
        <polygon points="-132,100 -42,-42 46,100" fill="${surface}" stroke="${ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <polygon points="-28,100 54,-82 136,100" fill="${surface}" stroke="${ink}" stroke-width="6" stroke-linejoin="round"/>
        <polygon points="54,-82 28,-22 54,-34 80,-22" fill="${accent}" fill-opacity="0.22" stroke="${ink}" stroke-width="4" stroke-linejoin="round"/>
        <!-- Lá cờ trên đỉnh -->
        <line x1="54" y1="-82" x2="54" y2="-126" stroke="${ink}" stroke-width="5" stroke-linecap="round"/>
        <polygon points="54,-126 102,-112 54,-96" fill="${accent}" stroke="${ink}" stroke-width="3.5" stroke-linejoin="round"/>
        <!-- Đường dẫn lên đỉnh -->
        <path d="M-84 100 Q-18 54 14 68 Q46 80 54 -14" fill="none" stroke="${accent}" stroke-width="5" stroke-dasharray="10 8" stroke-linecap="round"/>
      `;
      break;

    case 'broken_chains':
      inner = `
        <!-- Xiềng xích bên trái -->
        <g transform="translate(-62, 0) rotate(-18)">
          <rect x="-56" y="-22" width="68" height="44" rx="22" fill="none" stroke="${ink}" stroke-width="11"/>
          <rect x="-6" y="-22" width="54" height="44" rx="22" fill="none" stroke="${ink}" stroke-width="11"/>
        </g>
        <!-- Xiềng xích bên phải -->
        <g transform="translate(62, 0) rotate(18)">
          <rect x="-48" y="-22" width="54" height="44" rx="22" fill="none" stroke="${ink}" stroke-width="11"/>
          <rect x="-12" y="-22" width="68" height="44" rx="22" fill="none" stroke="${ink}" stroke-width="11"/>
        </g>
        <!-- Tia sáng bứt phá ở điểm đứt -->
        <path d="M0 -76 L0 -36 M-28 -56 L-12 -30 M28 -56 L12 -30 M0 36 L0 76 M-26 56 L-10 32 M26 56 L10 32" stroke="${accent}" stroke-width="6.5" stroke-linecap="round"/>
      `;
      break;

    case 'compass':
      inner = `
        <ellipse cx="0" cy="112" rx="76" ry="12" fill="${ink}" fill-opacity="0.12"/>
        <circle cx="0" cy="0" r="96" fill="${surface}" stroke="${ink}" stroke-width="6"/>
        <circle cx="0" cy="0" r="78" fill="none" stroke="${ink}" stroke-width="2.5" stroke-dasharray="4 10"/>
        <path d="M0 -88 L0 -70 M0 70 L0 88 M-88 0 L-70 0 M70 0 L88 0" stroke="${ink}" stroke-width="5" stroke-linecap="round"/>
        <!-- Kim la bàn chỉ hướng Bắc -->
        <polygon points="0,-64 18,0 0,14 -18,0" fill="${accent}" stroke="${ink}" stroke-width="4" stroke-linejoin="round"/>
        <polygon points="0,64 18,0 0,-14 -18,0" fill="${surface}" stroke="${ink}" stroke-width="4" stroke-linejoin="round"/>
        <circle cx="0" cy="0" r="9" fill="${ink}"/>
      `;
      break;

    case 'lightbulb':
      inner = `
        <!-- Tia sáng tỏa ra -->
        <path d="M0 -122 L0 -96 M-84 -86 L-66 -68 M84 -86 L66 -68 M-112 -16 L-86 -16 M112 -16 L86 -16" stroke="${accent}" stroke-width="6" stroke-linecap="round"/>
        <!-- Bóng đèn sáng -->
        <path d="M-42 36 C-68 12 -74 -34 -52 -64 C-26 -96 26 -96 52 -64 C74 -34 68 12 42 36 L34 64 L-34 64 Z" fill="${surface}" stroke="${ink}" stroke-width="6" stroke-linejoin="round"/>
        <circle cx="0" cy="-20" r="36" fill="${accent}" fill-opacity="0.18"/>
        <path d="M-16 64 L-16 10 Q0 -8 16 10 L16 64" fill="none" stroke="${accent}" stroke-width="5" stroke-linecap="round"/>
        <!-- Đui đèn -->
        <rect x="-32" y="66" width="64" height="16" rx="6" fill="${ink}"/>
        <rect x="-24" y="86" width="48" height="14" rx="6" fill="${ink}"/>
      `;
      break;

    case 'target_bullseye':
      inner = `
        <circle cx="-12" cy="6" r="92" fill="${surface}" stroke="${ink}" stroke-width="6"/>
        <circle cx="-12" cy="6" r="62" fill="${accent}" fill-opacity="0.15" stroke="${ink}" stroke-width="5"/>
        <circle cx="-12" cy="6" r="32" fill="${accent}" stroke="${ink}" stroke-width="4.5"/>
        <circle cx="-12" cy="6" r="10" fill="${surface}"/>
        <!-- Mũi tên trúng hồng tâm -->
        <line x1="98" y1="-88" x2="-4" y2="0" stroke="${ink}" stroke-width="6.5" stroke-linecap="round"/>
        <polygon points="-10,6 16,-4 4,-18" fill="${ink}"/>
        <path d="M84 -76 L108 -74 M94 -84 L96 -108 M72 -66 L96 -64" stroke="${accent}" stroke-width="5.5" stroke-linecap="round"/>
      `;
      break;

    case 'phone_distraction':
      inner = `
        <!-- Thân điện thoại -->
        <rect x="-56" y="-96" width="112" height="196" rx="20" fill="${surface}" stroke="${ink}" stroke-width="6"/>
        <rect x="-42" y="-68" width="84" height="136" rx="8" fill="${bg}" stroke="${ink}" stroke-width="3"/>
        <line x1="-18" y1="-82" x2="18" y2="-82" stroke="${ink}" stroke-width="4.5" stroke-linecap="round"/>
        <circle cx="0" cy="84" r="7" fill="${ink}"/>
        <!-- Bong bóng thông báo gây xao nhãng bay loạn -->
        <g transform="translate(68, -68)">
          <rect x="-32" y="-22" width="64" height="40" rx="12" fill="${accent}" stroke="${ink}" stroke-width="4"/>
          <circle cx="-12" cy="-2" r="4" fill="${surface}"/><circle cx="0" cy="-2" r="4" fill="${surface}"/><circle cx="12" cy="-2" r="4" fill="${surface}"/>
        </g>
        <g transform="translate(-74, -22)">
          <circle cx="0" cy="0" r="24" fill="${accent}" stroke="${ink}" stroke-width="4"/>
          <path d="M0 -10 L0 3 M0 10 L0 12" stroke="${surface}" stroke-width="5" stroke-linecap="round"/>
        </g>
        <g transform="translate(74, 24)">
          <circle cx="0" cy="0" r="22" fill="${surface}" stroke="${accent}" stroke-width="4.5"/>
          <path d="M-8 0 L0 -8 L8 0 L0 10 Z" fill="${accent}"/>
        </g>
      `;
      break;

    case 'clock_time':
      inner = `
        <ellipse cx="0" cy="110" rx="76" ry="12" fill="${ink}" fill-opacity="0.12"/>
        <circle cx="0" cy="0" r="94" fill="${surface}" stroke="${ink}" stroke-width="6.5"/>
        <path d="M0 -78 L0 -64 M0 64 L0 78 M-78 0 L-64 0 M64 0 L78 0" stroke="${ink}" stroke-width="5" stroke-linecap="round"/>
        <path d="M0 0 L0 -54 M0 0 L44 22" stroke="${ink}" stroke-width="7" stroke-linecap="round"/>
        <path d="M0 -64 A64 64 0 0 1 58 28" fill="none" stroke="${accent}" stroke-width="7" stroke-linecap="round"/>
        <circle cx="0" cy="0" r="10" fill="${accent}" stroke="${ink}" stroke-width="3.5"/>
      `;
      break;

    case 'stoic_scroll':
      inner = `
        <!-- Cuộn giấy triết lý Khắc kỷ -->
        <rect x="-78" y="-76" width="156" height="156" rx="10" fill="${surface}" stroke="${ink}" stroke-width="5.5"/>
        <rect x="-92" y="-92" width="184" height="24" rx="12" fill="${surface}" stroke="${ink}" stroke-width="5.5"/>
        <rect x="-92" y="68" width="184" height="24" rx="12" fill="${surface}" stroke="${ink}" stroke-width="5.5"/>
        <line x1="-46" y1="-34" x2="46" y2="-34" stroke="${ink}" stroke-width="5" stroke-linecap="round"/>
        <line x1="-46" y1="-8" x2="46" y2="-8" stroke="${ink}" stroke-width="5" stroke-linecap="round"/>
        <line x1="-46" y1="18" x2="22" y2="18" stroke="${ink}" stroke-width="5" stroke-linecap="round"/>
        <!-- Dấu triện sáp -->
        <circle cx="44" cy="36" r="20" fill="${accent}" stroke="${ink}" stroke-width="4"/>
        <path d="M36 36 L42 42 L54 30" fill="none" stroke="${surface}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
      `;
      break;

    case 'temple_pillar':
      inner = `
        <ellipse cx="0" cy="110" rx="92" ry="12" fill="${ink}" fill-opacity="0.12"/>
        <!-- Đế cột & Đỉnh cột Doric -->
        <rect x="-76" y="84" width="152" height="20" rx="5" fill="${surface}" stroke="${ink}" stroke-width="5.5"/>
        <rect x="-62" y="66" width="124" height="18" rx="4" fill="${surface}" stroke="${ink}" stroke-width="5"/>
        <rect x="-48" y="-66" width="96" height="132" fill="${surface}" stroke="${ink}" stroke-width="5.5"/>
        <line x1="-22" y1="-56" x2="-22" y2="56" stroke="${ink}" stroke-width="3.5" stroke-linecap="round"/>
        <line x1="0" y1="-56" x2="0" y2="56" stroke="${ink}" stroke-width="3.5" stroke-linecap="round"/>
        <line x1="22" y1="-56" x2="22" y2="56" stroke="${ink}" stroke-width="3.5" stroke-linecap="round"/>
        <rect x="-78" y="-92" width="156" height="26" rx="6" fill="${accent}" fill-opacity="0.18" stroke="${ink}" stroke-width="5.5"/>
      `;
      break;

    case 'stairs_growth':
      inner = `
        <ellipse cx="0" cy="108" rx="116" ry="12" fill="${ink}" fill-opacity="0.12"/>
        <path d="M-108 100 L-108 58 L-54 58 L-54 16 L0 16 L0 -26 L54 -26 L54 -68 L108 -68 L108 100 Z" fill="${surface}" stroke="${ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <!-- Mũi tên tăng trưởng vút lên -->
        <path d="M-96 24 Q-16 -24 88 -98" fill="none" stroke="${accent}" stroke-width="7.5" stroke-linecap="round"/>
        <polygon points="104,-108 72,-102 88,-82" fill="${accent}"/>
      `;
      break;

    case 'mirror_self':
      inner = `
        <ellipse cx="0" cy="108" rx="76" ry="12" fill="${ink}" fill-opacity="0.12"/>
        <rect x="-70" y="-96" width="140" height="194" rx="70" fill="${surface}" stroke="${ink}" stroke-width="6.5"/>
        <rect x="-54" y="-80" width="108" height="162" rx="54" fill="${accent}" fill-opacity="0.12" stroke="${accent}" stroke-width="4"/>
        <!-- Ánh phản chiếu sắc nét -->
        <line x1="-26" y1="-44" x2="14" y2="-8" stroke="${surface}" stroke-width="7" stroke-linecap="round"/>
        <line x1="-24" y1="-12" x2="4" y2="14" stroke="${surface}" stroke-width="5" stroke-linecap="round"/>
        <circle cx="0" cy="24" r="24" fill="${surface}" stroke="${ink}" stroke-width="4.5"/>
      `;
      break;

    case 'brick_wall':
      inner = `
        <rect x="-106" y="-44" width="212" height="142" rx="8" fill="${surface}" stroke="${ink}" stroke-width="5.5"/>
        <line x1="-106" y1="4" x2="106" y2="4" stroke="${ink}" stroke-width="4.5"/>
        <line x1="-106" y1="52" x2="106" y2="52" stroke="${ink}" stroke-width="4.5"/>
        <line x1="-36" y1="-44" x2="-36" y2="4" stroke="${ink}" stroke-width="4.5"/>
        <line x1="36" y1="-44" x2="36" y2="4" stroke="${ink}" stroke-width="4.5"/>
        <line x1="0" y1="4" x2="0" y2="52" stroke="${ink}" stroke-width="4.5"/>
        <line x1="-70" y1="4" x2="-70" y2="52" stroke="${ink}" stroke-width="4.5"/>
        <line x1="70" y1="4" x2="70" y2="52" stroke="${ink}" stroke-width="4.5"/>
        <line x1="-36" y1="52" x2="-36" y2="98" stroke="${ink}" stroke-width="4.5"/>
        <line x1="36" y1="52" x2="36" y2="98" stroke="${ink}" stroke-width="4.5"/>
        <!-- Đường vòng vượt qua rào cản -->
        <path d="M-112 -64 Q0 -132 104 -64" fill="none" stroke="${accent}" stroke-width="7" stroke-linecap="round"/>
        <polygon points="122,-54 90,-54 102,-78" fill="${accent}"/>
      `;
      break;

    case 'flame_forge':
      inner = `
        <ellipse cx="0" cy="108" rx="76" ry="12" fill="${ink}" fill-opacity="0.12"/>
        <path d="M0 -106 C48 -58 76 -12 64 46 C54 88 26 102 0 102 C-34 102 -68 78 -68 32 C-68 -18 -26 -54 0 -106 Z" fill="${accent}" fill-opacity="0.22" stroke="${ink}" stroke-width="6" stroke-linejoin="round"/>
        <path d="M0 -42 C24 -12 36 16 28 52 C22 76 10 86 0 86 C-18 86 -34 72 -34 44 C-34 18 -14 -10 0 -42 Z" fill="${accent}" stroke="${ink}" stroke-width="4.5" stroke-linejoin="round"/>
        <circle cx="0" cy="54" r="12" fill="${surface}"/>
      `;
      break;

    case 'anchor_waves':
      inner = `
        <!-- Sóng biển động -->
        <path d="M-126 78 Q-92 52 -58 78 Q-24 104 10 78 Q44 52 78 78 Q106 96 128 78" fill="none" stroke="${accent}" stroke-width="6.5" stroke-linecap="round"/>
        <path d="M-114 104 Q-80 82 -46 104 Q-12 124 22 104 Q56 82 90 104" fill="none" stroke="${accent}" stroke-width="4.5" stroke-linecap="round" stroke-opacity="0.6"/>
        <!-- Mỏ neo vững chắc -->
        <circle cx="0" cy="-78" r="18" fill="${surface}" stroke="${ink}" stroke-width="6"/>
        <line x1="0" y1="-60" x2="0" y2="66" stroke="${ink}" stroke-width="8" stroke-linecap="round"/>
        <line x1="-42" y1="-34" x2="42" y2="-34" stroke="${ink}" stroke-width="7" stroke-linecap="round"/>
        <path d="M-64 16 C-62 56 -32 72 0 72 C32 72 62 56 64 16" fill="none" stroke="${ink}" stroke-width="8" stroke-linecap="round"/>
        <polygon points="-68,8 -80,30 -50,26" fill="${ink}"/>
        <polygon points="68,8 80,30 50,26" fill="${ink}"/>
      `;
      break;

    case 'heart_calm':
      inner = `
        <circle cx="0" cy="0" r="100" fill="${accent}" fill-opacity="0.08" stroke="${accent}" stroke-width="4"/>
        <path d="M0 58 C-78 8 -86 -54 -44 -68 C-20 -76 -4 -58 0 -44 C4 -58 20 -76 44 -68 C86 -54 78 8 0 58 Z" fill="${surface}" stroke="${ink}" stroke-width="6" stroke-linejoin="round"/>
        <path d="M-38 -2 L-16 -2 L-6 -24 L8 18 L18 -2 L38 -2" fill="none" stroke="${accent}" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round"/>
      `;
      break;

    case 'laurel_crown':
      inner = `
        <!-- Vòng nguyệt quế Khắc kỷ -->
        <path d="M-16 88 C-86 68 -104 -18 -54 -76" fill="none" stroke="${ink}" stroke-width="6" stroke-linecap="round"/>
        <path d="M16 88 C86 68 104 -18 54 -76" fill="none" stroke="${ink}" stroke-width="6" stroke-linecap="round"/>
        <ellipse cx="-78" cy="18" rx="18" ry="9" transform="rotate(-32 -78 18)" fill="${accent}" fill-opacity="0.28" stroke="${ink}" stroke-width="3.5"/>
        <ellipse cx="-82" cy="-22" rx="18" ry="9" transform="rotate(-6 -82 -22)" fill="${accent}" fill-opacity="0.28" stroke="${ink}" stroke-width="3.5"/>
        <ellipse cx="-62" cy="-58" rx="16" ry="8" transform="rotate(28 -62 -58)" fill="${accent}" fill-opacity="0.28" stroke="${ink}" stroke-width="3.5"/>
        <ellipse cx="78" cy="18" rx="18" ry="9" transform="rotate(32 78 18)" fill="${accent}" fill-opacity="0.28" stroke="${ink}" stroke-width="3.5"/>
        <ellipse cx="82" cy="-22" rx="18" ry="9" transform="rotate(6 82 -22)" fill="${accent}" fill-opacity="0.28" stroke="${ink}" stroke-width="3.5"/>
        <ellipse cx="62" cy="-58" rx="16" ry="8" transform="rotate(-28 62 -58)" fill="${accent}" fill-opacity="0.28" stroke="${ink}" stroke-width="3.5"/>
        <polygon points="0,-54 14,-16 54,-16 22,8 34,46 0,22 -34,46 -22,8 -54,-16 -14,-16" fill="${accent}" stroke="${ink}" stroke-width="4.5" stroke-linejoin="round"/>
      `;
      break;

    case 'checklist_board':
      inner = `
        <rect x="-78" y="-92" width="156" height="192" rx="16" fill="${surface}" stroke="${ink}" stroke-width="5.5"/>
        <rect x="-34" y="-108" width="68" height="28" rx="8" fill="${accent}" stroke="${ink}" stroke-width="4.5"/>
        <!-- 3 dòng đã hoàn thành -->
        <circle cx="-44" cy="-34" r="14" fill="${accent}" fill-opacity="0.2" stroke="${accent}" stroke-width="4"/>
        <path d="M-50 -34 L-45 -29 L-36 -39" fill="none" stroke="${accent}" stroke-width="4" stroke-linecap="round"/>
        <line x1="-16" y1="-34" x2="52" y2="-34" stroke="${ink}" stroke-width="6" stroke-linecap="round"/>

        <circle cx="-44" cy="16" r="14" fill="${accent}" fill-opacity="0.2" stroke="${accent}" stroke-width="4"/>
        <path d="M-50 16 L-45 21 L-36 11" fill="none" stroke="${accent}" stroke-width="4" stroke-linecap="round"/>
        <line x1="-16" y1="16" x2="46" y2="16" stroke="${ink}" stroke-width="6" stroke-linecap="round"/>

        <circle cx="-44" cy="66" r="14" fill="${accent}" fill-opacity="0.2" stroke="${accent}" stroke-width="4"/>
        <path d="M-50 66 L-45 71 L-36 61" fill="none" stroke="${accent}" stroke-width="4" stroke-linecap="round"/>
        <line x1="-16" y1="66" x2="36" y2="66" stroke="${ink}" stroke-width="6" stroke-linecap="round"/>
      `;
      break;

    case 'crowd_chatter':
      inner = `
        <!-- 3 bóng người đám đông phía sau -->
        <g opacity="0.9">
          <circle cx="-68" cy="10" r="24" fill="${surface}" stroke="${ink}" stroke-width="5"/>
          <path d="M-104 92 C-104 54 -32 54 -32 92 Z" fill="${surface}" stroke="${ink}" stroke-width="5"/>
          <circle cx="68" cy="10" r="24" fill="${surface}" stroke="${ink}" stroke-width="5"/>
          <path d="M32 92 C32 54 104 54 104 92 Z" fill="${surface}" stroke="${ink}" stroke-width="5"/>
          <circle cx="0" cy="-4" r="28" fill="${surface}" stroke="${ink}" stroke-width="5.5"/>
          <path d="M-42 96 C-42 50 42 50 42 96 Z" fill="${surface}" stroke="${ink}" stroke-width="5.5"/>
        </g>
        <!-- Bong bóng ồn ào -->
        <rect x="-86" y="-92" width="76" height="38" rx="12" fill="${accent}" fill-opacity="0.2" stroke="${accent}" stroke-width="4"/>
        <line x1="-68" y1="-73" x2="-28" y2="-73" stroke="${accent}" stroke-width="4.5" stroke-linecap="round"/>
        <rect x="14" y="-84" width="76" height="38" rx="12" fill="${surface}" stroke="${ink}" stroke-width="4"/>
        <line x1="32" y1="-65" x2="72" y2="-65" stroke="${ink}" stroke-width="4.5" stroke-linecap="round"/>
      `;
      break;

    case 'battery_power':
      inner = `
        <rect x="-92" y="-50" width="172" height="100" rx="16" fill="${surface}" stroke="${ink}" stroke-width="6"/>
        <rect x="80" y="-22" width="18" height="44" rx="6" fill="${ink}"/>
        <rect x="-76" y="-34" width="42" height="68" rx="6" fill="${accent}"/>
        <rect x="-24" y="-34" width="42" height="68" rx="6" fill="${accent}" fill-opacity="0.72"/>
        <rect x="28" y="-34" width="36" height="68" rx="6" fill="${accent}" fill-opacity="0.35"/>
      `;
      break;

    case 'key_padlock':
      inner = `
        <path d="M-44 -20 L-44 -58 C-44 -90 44 -90 44 -58 L44 -20" fill="none" stroke="${ink}" stroke-width="9" stroke-linecap="round"/>
        <rect x="-68" y="-24" width="136" height="114" rx="18" fill="${surface}" stroke="${ink}" stroke-width="6"/>
        <circle cx="0" cy="24" r="16" fill="${accent}"/>
        <rect x="-6" y="34" width="12" height="28" rx="4" fill="${accent}"/>
      `;
      break;

    case 'crossroads':
      inner = `
        <ellipse cx="0" cy="108" rx="68" ry="12" fill="${ink}" fill-opacity="0.12"/>
        <rect x="-10" y="-88" width="20" height="196" rx="6" fill="${surface}" stroke="${ink}" stroke-width="5.5"/>
        <!-- Bảng chỉ trái (cũ) -->
        <polygon points="10,-64 -84,-64 -108,-42 -84,-20 10,-20" fill="${surface}" stroke="${ink}" stroke-width="5" stroke-linejoin="round"/>
        <!-- Bảng chỉ phải (hướng đúng màu nhấn) -->
        <polygon points="-10,-2 84,-2 108,20 84,42 -10,42" fill="${accent}" fill-opacity="0.22" stroke="${accent}" stroke-width="5.5" stroke-linejoin="round"/>
        <path d="M18 20 L66 20 M54 10 L68 20 L54 30" fill="none" stroke="${accent}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
      `;
      break;

    case 'growing_tree':
      inner = `
        <ellipse cx="0" cy="108" rx="92" ry="12" fill="${ink}" fill-opacity="0.12"/>
        <path d="M-12 104 L-8 14 L8 14 L12 104 Z" fill="${surface}" stroke="${ink}" stroke-width="5.5"/>
        <path d="M-12 104 Q-44 106 -64 114 M12 104 Q44 106 64 114" fill="none" stroke="${ink}" stroke-width="4.5" stroke-linecap="round"/>
        <circle cx="0" cy="-36" r="56" fill="${accent}" fill-opacity="0.18" stroke="${ink}" stroke-width="5.5"/>
        <circle cx="-46" cy="-4" r="38" fill="${surface}" stroke="${ink}" stroke-width="5"/>
        <circle cx="46" cy="-4" r="38" fill="${surface}" stroke="${ink}" stroke-width="5"/>
        <path d="M0 16 L0 -44 M0 -8 L-28 -26 M0 -16 L28 -32" stroke="${ink}" stroke-width="4.5" stroke-linecap="round"/>
      `;
      break;

    case 'mask_duality':
      inner = `
        <!-- Mặt nạ cảm xúc được gỡ bỏ -->
        <g transform="translate(-44, 14) rotate(-14)">
          <path d="M-46 -56 Q0 -70 46 -56 L42 18 Q0 64 -42 18 Z" fill="${surface}" stroke="${ink}" stroke-width="5.5" stroke-linejoin="round"/>
          <path d="M-24 -14 L-8 -8 M24 -14 L8 -8" stroke="${ink}" stroke-width="4.5" stroke-linecap="round"/>
          <path d="M-18 24 Q0 10 18 24" fill="none" stroke="${ink}" stroke-width="4.5" stroke-linecap="round"/>
        </g>
        <!-- Gương mặt điềm tĩnh thật -->
        <g transform="translate(46, -12) rotate(10)">
          <path d="M-46 -56 Q0 -70 46 -56 L42 18 Q0 64 -42 18 Z" fill="${accent}" fill-opacity="0.18" stroke="${accent}" stroke-width="5.5" stroke-linejoin="round"/>
          <circle cx="-16" cy="-12" r="4.5" fill="${ink}"/>
          <circle cx="16" cy="-12" r="4.5" fill="${ink}"/>
          <path d="M-16 18 Q0 32 16 18" fill="none" stroke="${ink}" stroke-width="4.5" stroke-linecap="round"/>
        </g>
      `;
      break;

    default: // speech_calm
      inner = `
        <rect x="-98" y="-66" width="196" height="118" rx="22" fill="${surface}" stroke="${ink}" stroke-width="5.5"/>
        <polygon points="-44,52 -74,88 -12,52" fill="${surface}" stroke="${ink}" stroke-width="5.5" stroke-linejoin="round"/>
        <path d="M-58 -8 Q-36 -28 -14 -8 Q8 12 30 -8 Q52 -28 66 -8" fill="none" stroke="${accent}" stroke-width="6" stroke-linecap="round"/>
        <line x1="-54" y1="22" x2="38" y2="22" stroke="${ink}" stroke-width="5" stroke-linecap="round"/>
      `;
      break;
  }

  return `<g transform="translate(${x}, ${y}) scale(${scale})">${inner}</g>`;
}

// ============================================================================
// 3. HIỆU ỨNG NHẤN SẮC NÉT (DẤU X GẠCH SAI, TICK XANH, MŨI TÊN CHUYỂN HƯỚNG, HÀO QUANG)
// ============================================================================

function renderOverlayEffect(
  effect: StudioOverlay,
  x: number,
  y: number,
  theme: SvgThemeColors
): string {
  const { accentColor: accent, surfaceFill: surface } = theme;
  switch (effect) {
    case 'big_x_crossout':
      return `<g transform="translate(${x}, ${y})">
        <circle cx="0" cy="0" r="64" fill="${accent}" fill-opacity="0.12"/>
        <path d="M-46 -46 L46 46 M46 -46 L-46 46" stroke="${accent}" stroke-width="14" stroke-linecap="round"/>
      </g>`;
    case 'checkmark_badge':
      return `<g transform="translate(${x}, ${y})">
        <circle cx="0" cy="0" r="38" fill="${accent}"/>
        <path d="M-16 1 L-4 13 L18 -12" fill="none" stroke="${surface}" stroke-width="7.5" stroke-linecap="round" stroke-linejoin="round"/>
      </g>`;
    case 'curved_arrow_right':
      return `<g transform="translate(${x}, ${y})">
        <path d="M-78 16 Q0 -34 72 8" fill="none" stroke="${accent}" stroke-width="9" stroke-linecap="round"/>
        <polygon points="94,16 56,-8 64,28" fill="${accent}"/>
      </g>`;
    case 'upward_growth_arrow':
      return `<g transform="translate(${x}, ${y})">
        <path d="M-54 46 L48 -42" stroke="${accent}" stroke-width="9" stroke-linecap="round"/>
        <polygon points="64,-54 28,-46 50,-22" fill="${accent}"/>
      </g>`;
    case 'shield_aura':
      return `<g transform="translate(${x}, ${y})">
        <circle cx="0" cy="0" r="145" fill="none" stroke="${accent}" stroke-width="3.5" stroke-dasharray="14 10" stroke-opacity="0.55"/>
      </g>`;
    case 'spark_emphasis':
      return `<g transform="translate(${x}, ${y})">
        <path d="M0 -34 L0 -14 M0 14 L0 34 M-34 0 L-14 0 M14 0 L34 0 M-22 -22 L-10 -10 M22 22 L10 10 M22 -22 L10 -10 M-22 22 L-10 10" stroke="${accent}" stroke-width="5" stroke-linecap="round"/>
      </g>`;
    default:
      return '';
  }
}

// ============================================================================
// 4. BỘ DỰNG SVG HOÀN CHỈNH CHO TỪNG KHUNG HÌNH (16:9 & 9:16) + HỖ TRỢ BEAT-1/2/3
// ============================================================================

export function renderStudioShotSvg(params: {
  blueprint: StudioShotBlueprint;
  theme: SvgThemeColors;
  vbW: number;
  vbH: number;
  includeBeatGroups?: boolean;
}): string {
  const { blueprint, theme, vbW, vbH } = params;
  const { bgColor: bg, inkColor: ink, accentColor: accent, surfaceFill: surface } = theme;
  const isVertical = vbH > vbW;
  const cx = Math.round(vbW / 2);

  // Nền studio sạch kèm lưới chấm nhẹ tinh tế + khung bố cục hiện đại (không lỗi bộ lọc blur)
  const backdropDecor = `
    <rect width="${vbW}" height="${vbH}" fill="${bg}"/>
    <circle cx="${Math.round(vbW * 0.14)}" cy="${Math.round(vbH * 0.18)}" r="${isVertical ? 140 : 190}" fill="${accent}" fill-opacity="0.05"/>
    <circle cx="${Math.round(vbW * 0.86)}" cy="${Math.round(vbH * 0.78)}" r="${isVertical ? 160 : 210}" fill="${ink}" fill-opacity="0.04"/>
  `;

  // Thanh tiêu đề chương trên cùng (nếu có) — luôn nằm gọn trong vùng an toàn y=24..82
  const headerClean = String(blueprint.chapter_header || '')
    .replace(/[&<>]/g, ' ')
    .trim()
    .slice(0, 48);
  const headerSvg = headerClean
    ? `
    <g id="studio-header">
      <rect x="${cx - 320}" y="22" width="640" height="50" rx="25" fill="${surface}" stroke="${ink}" stroke-width="3"/>
      <text x="${cx}" y="55" text-anchor="middle" font-family="${FONT_FAMILY}" font-size="24" font-weight="700" fill="${ink}">${escapeXmlText(headerClean)}</text>
    </g>`
    : '';

  // Chỉ báo nhịp shot ở góc trên phải
  const beatCounterSvg =
    typeof blueprint.beat_index === 'number' && typeof blueprint.total_beats === 'number' && blueprint.total_beats > 1
      ? `<rect x="${vbW - 118}" y="24" width="84" height="36" rx="18" fill="${accent}" fill-opacity="0.14" stroke="${accent}" stroke-width="2.5"/>
         <text x="${vbW - 76}" y="48" text-anchor="middle" font-family="${FONT_FAMILY}" font-size="18" font-weight="800" fill="${accent}">${blueprint.beat_index + 1}/${blueprint.total_beats}</text>`
      : '';

  // Khung sân khấu chính (Stage Card) tách biệt hoàn toàn với vùng Caption bên dưới -> 0% chồng chữ!
  const stageX = isVertical ? 44 : 68;
  const stageY = headerClean ? 94 : 62;
  const stageW = vbW - stageX * 2;
  const stageH = isVertical ? 790 : 482;
  const stageMidX = Math.round(stageX + stageW / 2);
  const stageMidY = Math.round(stageY + stageH / 2);

  const stageFrameSvg = `
    <!-- Bóng đổ phẳng offset tạo chiều sâu chuẩn editorial -->
    <rect x="${stageX + 8}" y="${stageY + 8}" width="${stageW}" height="${stageH}" rx="28" fill="${ink}" fill-opacity="0.08"/>
    <rect x="${stageX}" y="${stageY}" width="${stageW}" height="${stageH}" rx="28" fill="${surface}" stroke="${ink}" stroke-width="4"/>
    <!-- Đường chân trời nền nhẹ bên trong khung tranh -->
    <line x1="${stageX + 42}" y1="${stageY + stageH - 54}" x2="${stageX + stageW - 42}" y2="${stageY + stageH - 54}" stroke="${ink}" stroke-width="2.5" stroke-opacity="0.18" stroke-linecap="round"/>
  `;

  // Dựng nội dung 3 lớp beat-1 / beat-2 / beat-3 theo đúng composition
  let beat1Svg = '';
  let beat2Svg = '';
  let beat3Svg = '';

  const charScale = isVertical ? 0.96 : 1.04;
  const propScale = isVertical ? 0.94 : 1.06;

  switch (blueprint.composition) {
    case 'center_metaphor': {
      beat1Svg = renderStudioProp(
        blueprint.primary_prop,
        stageMidX,
        stageMidY - 4,
        isVertical ? 1.24 : 1.38,
        theme
      );
      beat2Svg =
        blueprint.overlay_effect !== 'none'
          ? renderOverlayEffect(
              blueprint.overlay_effect,
              blueprint.overlay_effect === 'shield_aura' ? stageMidX : stageMidX + (isVertical ? 145 : 225),
              blueprint.overlay_effect === 'shield_aura' ? stageMidY - 4 : stageMidY - 95,
              theme
            )
          : '';
      beat3Svg = blueprint.right_badge
        ? `<rect x="${stageMidX - 165}" y="${stageY + 26}" width="330" height="44" rx="22" fill="${accent}" fill-opacity="0.14" stroke="${accent}" stroke-width="3"/>
           <text x="${stageMidX}" y="${stageY + 56}" text-anchor="middle" font-family="${FONT_FAMILY}" font-size="22" font-weight="800" fill="${accent}">${escapeXmlText(blueprint.right_badge)}</text>`
        : `<circle cx="${stageMidX - 245}" cy="${stageY + 56}" r="10" fill="${accent}" fill-opacity="0.28"/>
           <circle cx="${stageMidX + 245}" cy="${stageY + 56}" r="10" fill="${accent}" fill-opacity="0.28"/>`;
      break;
    }

    case 'prop_left_character_right': {
      const leftX = isVertical ? stageMidX : stageX + Math.round(stageW * 0.30);
      const leftY = isVertical ? stageY + Math.round(stageH * 0.28) : stageMidY - 8;
      const rightX = isVertical ? stageMidX : stageX + Math.round(stageW * 0.72);
      const rightY = isVertical ? stageY + Math.round(stageH * 0.72) : stageMidY + 24;

      beat1Svg = renderStudioProp(blueprint.primary_prop, leftX, leftY, propScale, theme);
      beat2Svg = renderOverlayEffect(
        blueprint.overlay_effect === 'none' ? 'curved_arrow_right' : blueprint.overlay_effect,
        blueprint.overlay_effect === 'big_x_crossout' ? leftX : stageMidX,
        blueprint.overlay_effect === 'big_x_crossout' ? leftY : stageMidY - 12,
        theme
      );
      beat3Svg = renderStudioCharacter({
        x: rightX,
        y: rightY,
        scale: charScale,
        flipX: !isVertical,
        pose: blueprint.character_pose,
        expression: blueprint.character_expression,
        theme,
      });
      break;
    }

    case 'split_comparison': {
      const panelGap = 36;
      const panelW = isVertical ? stageW - 64 : Math.round((stageW - 96 - panelGap) / 2);
      const panelH = isVertical ? Math.round((stageH - 112) / 2) : stageH - 76;
      const leftPX = isVertical ? stageX + 32 : stageX + 48;
      const leftPY = stageY + 38;
      const rightPX = isVertical ? stageX + 32 : leftPX + panelW + panelGap;
      const rightPY = isVertical ? leftPY + panelH + 34 : stageY + 38;

      const leftMidX = Math.round(leftPX + panelW / 2);
      const leftMidY = Math.round(leftPY + panelH / 2);
      const rightMidX = Math.round(rightPX + panelW / 2);
      const rightMidY = Math.round(rightPY + panelH / 2);

      const leftTag = blueprint.left_badge || 'Phản ứng cũ';
      const rightTag = blueprint.right_badge || 'Bản lĩnh mới';

      beat1Svg = `
        <rect x="${leftPX}" y="${leftPY}" width="${panelW}" height="${panelH}" rx="20" fill="${bg}" stroke="${ink}" stroke-width="3.5" stroke-dasharray="10 6"/>
        <rect x="${leftMidX - 120}" y="${leftPY + 18}" width="240" height="40" rx="20" fill="${surface}" stroke="${ink}" stroke-width="3"/>
        <text x="${leftMidX}" y="${leftPY + 45}" text-anchor="middle" font-family="${FONT_FAMILY}" font-size="20" font-weight="700" fill="${ink}">${escapeXmlText(leftTag)}</text>
        ${renderStudioProp(blueprint.primary_prop, leftMidX, leftMidY + 22, isVertical ? 0.72 : 0.88, theme)}
      `;

      beat2Svg = `
        ${renderOverlayEffect('big_x_crossout', leftMidX + Math.round(panelW * 0.28), leftPY + 88, theme)}
        <circle cx="${stageMidX}" cy="${stageMidY}" r="34" fill="${accent}" stroke="${surface}" stroke-width="5"/>
        <path d="M${stageMidX - 12} ${stageMidY} L${stageMidX + 12} ${stageMidY} M${stageMidX + 2} ${stageMidY - 10} L${stageMidX + 14} ${stageMidY} L${stageMidX + 2} ${stageMidY + 10}" fill="none" stroke="${surface}" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round"/>
      `;

      beat3Svg = `
        <rect x="${rightPX}" y="${rightPY}" width="${panelW}" height="${panelH}" rx="20" fill="${accent}" fill-opacity="0.08" stroke="${accent}" stroke-width="4"/>
        <rect x="${rightMidX - 120}" y="${rightPY + 18}" width="240" height="40" rx="20" fill="${accent}"/>
        <text x="${rightMidX}" y="${rightPY + 45}" text-anchor="middle" font-family="${FONT_FAMILY}" font-size="20" font-weight="800" fill="${surface}">${escapeXmlText(rightTag)}</text>
        ${renderStudioCharacter({
          x: rightMidX,
          y: rightMidY + 34,
          scale: isVertical ? 0.72 : 0.84,
          pose: blueprint.character_pose,
          expression: blueprint.character_expression,
          theme,
        })}
      `;
      break;
    }

    case 'cause_effect_flow': {
      const leftX = isVertical ? stageMidX : stageX + Math.round(stageW * 0.24);
      const leftY = isVertical ? stageY + Math.round(stageH * 0.24) : stageMidY + 18;
      const rightX = isVertical ? stageMidX : stageX + Math.round(stageW * 0.76);
      const rightY = isVertical ? stageY + Math.round(stageH * 0.74) : stageMidY - 4;

      beat1Svg = renderStudioCharacter({
        x: leftX,
        y: leftY,
        scale: charScale * 0.96,
        pose: blueprint.character_pose,
        expression: blueprint.character_expression,
        theme,
      });

      const midLabel = blueprint.left_badge || 'Chuyển hóa';
      beat2Svg = `
        ${renderOverlayEffect('curved_arrow_right', stageMidX, stageMidY + 10, theme)}
        <rect x="${stageMidX - 106}" y="${stageMidY - 82}" width="212" height="42" rx="21" fill="${accent}" fill-opacity="0.14" stroke="${accent}" stroke-width="3"/>
        <text x="${stageMidX}" y="${stageMidY - 54}" text-anchor="middle" font-family="${FONT_FAMILY}" font-size="21" font-weight="800" fill="${accent}">${escapeXmlText(midLabel)}</text>
      `;

      beat3Svg = renderStudioProp(
        blueprint.secondary_prop || blueprint.primary_prop,
        rightX,
        rightY,
        propScale,
        theme
      );
      break;
    }

    case 'two_characters_interaction': {
      const leftX = isVertical ? stageMidX - 135 : stageX + Math.round(stageW * 0.23);
      const rightX = isVertical ? stageMidX + 135 : stageX + Math.round(stageW * 0.77);
      const charY = stageMidY + 26;

      beat1Svg = renderStudioCharacter({
        x: leftX,
        y: charY,
        scale: isVertical ? 0.82 : 0.96,
        pose: blueprint.secondary_pose || 'pointing_accuse',
        expression: blueprint.secondary_expression || 'angry',
        theme,
        accentTie: false,
      });

      beat2Svg = renderStudioProp(
        blueprint.primary_prop,
        stageMidX,
        stageMidY - 38,
        isVertical ? 0.62 : 0.84,
        theme
      );

      beat3Svg = renderStudioCharacter({
        x: rightX,
        y: charY,
        scale: isVertical ? 0.82 : 0.98,
        flipX: true,
        pose: blueprint.character_pose,
        expression: blueprint.character_expression,
        theme,
        accentTie: true,
      });
      break;
    }

    case 'character_on_pedestal': {
      const pedestalY = stageY + stageH - 120;
      beat1Svg = `
        <polygon points="${stageMidX - 210},${stageY + stageH - 52} ${stageMidX - 148},${pedestalY} ${stageMidX + 148},${pedestalY} ${stageMidX + 210},${stageY + stageH - 52}" fill="${bg}" stroke="${ink}" stroke-width="5" stroke-linejoin="round"/>
        <line x1="${stageMidX - 110}" y1="${pedestalY + 28}" x2="${stageMidX + 110}" y2="${pedestalY + 28}" stroke="${accent}" stroke-width="5" stroke-linecap="round"/>
      `;
      beat2Svg = renderOverlayEffect(
        blueprint.overlay_effect === 'none' ? 'shield_aura' : blueprint.overlay_effect,
        stageMidX,
        stageMidY - 26,
        theme
      );
      beat3Svg = `
        ${renderStudioCharacter({
          x: stageMidX,
          y: pedestalY - 148,
          scale: isVertical ? 0.9 : 0.94,
          pose: blueprint.character_pose,
          expression: blueprint.character_expression,
          theme,
        })}
        ${renderStudioProp(blueprint.primary_prop, stageMidX + (isVertical ? 175 : 275), stageMidY - 28, isVertical ? 0.56 : 0.72, theme)}
      `;
      break;
    }

    case 'checklist_steps': {
      const charX = isVertical ? stageMidX : stageX + Math.round(stageW * 0.22);
      const charY = isVertical ? stageY + 195 : stageMidY + 24;
      const cardsX = isVertical ? stageX + 42 : stageX + Math.round(stageW * 0.43);
      const cardsW = isVertical ? stageW - 84 : Math.round(stageW * 0.52);
      const cardStartY = isVertical ? stageY + 395 : stageY + 62;
      const stepLabels =
        blueprint.step_items && blueprint.step_items.length > 0
          ? blueprint.step_items
          : [
              blueprint.left_badge || '1. Dừng lại 3 giây quan sát',
              blueprint.right_badge || '2. Tách sự thật khỏi cảm xúc',
              blueprint.caption || '3. Hành động điềm tĩnh, dứt khoát',
            ];

      beat1Svg = renderStudioCharacter({
        x: charX,
        y: charY,
        scale: isVertical ? 0.8 : 0.95,
        pose: blueprint.character_pose,
        expression: blueprint.character_expression,
        theme,
      });

      beat2Svg = isVertical
        ? ''
        : `<path d="M${charX + 115} ${stageMidY - 10} L${cardsX - 24} ${cardStartY + 46} M${charX + 115} ${stageMidY - 10} L${cardsX - 24} ${cardStartY + 174} M${charX + 115} ${stageMidY - 10} L${cardsX - 24} ${cardStartY + 302}" stroke="${accent}" stroke-width="5" stroke-linecap="round" stroke-dasharray="10 8"/>`;

      beat3Svg = stepLabels
        .slice(0, 3)
        .map((label, sIdx) => {
          const rowY = cardStartY + sIdx * 124;
          const cleanLabel = label.replace(/^\d+\.\s*/, '');
          return `
            <rect x="${cardsX}" y="${rowY}" width="${cardsW}" height="96" rx="18" fill="${bg}" stroke="${ink}" stroke-width="4"/>
            <circle cx="${cardsX + 46}" cy="${rowY + 48}" r="24" fill="${accent}"/>
            <text x="${cardsX + 46}" y="${rowY + 57}" text-anchor="middle" font-family="${FONT_FAMILY}" font-size="24" font-weight="800" fill="${surface}">${sIdx + 1}</text>
            <text x="${cardsX + 90}" y="${rowY + 57}" text-anchor="start" font-family="${FONT_FAMILY}" font-size="24" font-weight="700" fill="${ink}">${escapeXmlText(cleanLabel.slice(0, 30))}</text>
          `;
        })
        .join('\n');
      break;
    }

    default: {
      // character_left_prop_right
      const leftX = isVertical ? stageMidX : stageX + Math.round(stageW * 0.28);
      const leftY = isVertical ? stageY + Math.round(stageH * 0.30) : stageMidY + 24;
      const rightX = isVertical ? stageMidX : stageX + Math.round(stageW * 0.72);
      const rightY = isVertical ? stageY + Math.round(stageH * 0.72) : stageMidY - 8;

      beat1Svg = renderStudioCharacter({
        x: leftX,
        y: leftY,
        scale: charScale,
        pose: blueprint.character_pose,
        expression: blueprint.character_expression,
        theme,
      });

      beat2Svg =
        blueprint.overlay_effect !== 'none'
          ? renderOverlayEffect(
              blueprint.overlay_effect,
              blueprint.overlay_effect === 'big_x_crossout' ? leftX : stageMidX,
              blueprint.overlay_effect === 'big_x_crossout' ? leftY - 22 : stageMidY - 10,
              theme
            )
          : `<path d="M${leftX + 115} ${stageMidY} L${rightX - 150} ${stageMidY}" stroke="${accent}" stroke-width="5" stroke-dasharray="10 8" stroke-linecap="round"/>`;

      beat3Svg = renderStudioProp(blueprint.primary_prop, rightX, rightY, propScale, theme);
      break;
    }
  }

  // Khung Caption độc lập phía dưới sân khấu — KHÔNG BAO GIỜ đè lên nhân vật hay biểu tượng!
  const captionBoxY = stageY + stageH + 22;
  const captionBoxH = vbH - captionBoxY - 24;
  const captionLines = wrapTextLines(blueprint.caption, isVertical ? 24 : 38, 2);
  const captionFontSize = captionLines.length > 1 ? (isVertical ? 30 : 32) : isVertical ? 34 : 38;
  const captionTextStartY =
    captionLines.length > 1
      ? captionBoxY + Math.round(captionBoxH / 2) - 6
      : captionBoxY + Math.round(captionBoxH / 2) + 12;

  const captionBoxSvg = `
    <g id="studio-caption">
      <rect x="${stageX}" y="${captionBoxY}" width="${stageW}" height="${captionBoxH}" rx="20" fill="${surface}" stroke="${accent}" stroke-width="4"/>
      <rect x="${stageX}" y="${captionBoxY}" width="16" height="${captionBoxH}" rx="8" fill="${accent}"/>
      ${renderMultilineText(captionLines, cx, captionTextStartY, 38, captionFontSize, ink, '800', 'middle')}
    </g>
  `;

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${vbW} ${vbH}" width="${vbW}" height="${vbH}">
  ${backdropDecor}
  ${headerSvg}
  ${beatCounterSvg}
  ${stageFrameSvg}
  <g id="beat-1">${beat1Svg}</g>
  <g id="beat-2">${beat2Svg}</g>
  <g id="beat-3">${beat3Svg}</g>
  ${captionBoxSvg}
</svg>`;
}

// ============================================================================
// 5. BỘ DỰNG THUMBNAIL YOUTUBE 1280×720 CHUẨN CTR CAO (0% CHỒNG CHỮ, 0% LỖI HÌNH)
// ============================================================================

export function renderStudioThumbnailSvg(params: {
  blueprint: StudioThumbnailBlueprint;
  theme: SvgThemeColors;
}): string {
  const { blueprint, theme } = params;
  const { bgColor: bg, inkColor: ink, accentColor: accent, surfaceFill: surface } = theme;

  const headLines = wrapTextLines(blueprint.headline.toUpperCase(), 13, 3);
  const subLines = wrapTextLines(blueprint.subtitle, 30, 2);
  const headFontSize = headLines.length >= 3 ? 62 : 70;
  const headLineHeight = headLines.length >= 3 ? 76 : 84;
  const headStartY = headLines.length >= 3 ? 236 : 258;

  const headlineSvg = headLines
    .map((line, idx) => {
      const isHighlight = idx === headLines.length - 1 && headLines.length > 1;
      return `<text x="74" y="${headStartY + idx * headLineHeight}" font-family="${FONT_FAMILY}" font-size="${headFontSize}" font-weight="800" fill="${isHighlight ? accent : ink}">${escapeXmlText(line)}</text>`;
    })
    .join('\n  ');

  const dividerY = headStartY + Math.max(1, headLines.length) * headLineHeight - 14;
  const subtitleSvg = subLines
    .map(
      (line, idx) =>
        `<text x="74" y="${dividerY + 52 + idx * 38}" font-family="${FONT_FAMILY}" font-size="27" font-weight="700" fill="${ink}" fill-opacity="0.88">${escapeXmlText(line)}</text>`
    )
    .join('\n  ');

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">
  <rect width="1280" height="720" fill="${bg}"/>
  <circle cx="1140" cy="110" r="240" fill="${accent}" fill-opacity="0.08"/>
  <rect x="0" y="0" width="24" height="720" fill="${accent}"/>

  <!-- Episode Badge góc trên trái -->
  <rect x="74" y="68" width="196" height="54" rx="14" fill="${accent}"/>
  <text x="172" y="104" text-anchor="middle" font-family="${FONT_FAMILY}" font-size="26" font-weight="800" fill="${surface}">${escapeXmlText(blueprint.badgeLabel)}</text>

  <!-- Tiêu đề lớn cỡ di động dễ đọc -->
  ${headlineSvg}
  <rect x="74" y="${dividerY}" width="184" height="9" rx="4.5" fill="${accent}"/>
  ${subtitleSvg}

  <!-- Khung hình minh họa nhân vật + biểu tượng bên phải -->
  <rect x="706" y="76" width="512" height="576" rx="28" fill="${ink}" fill-opacity="0.1"/>
  <rect x="696" y="66" width="512" height="576" rx="28" fill="${surface}" stroke="${ink}" stroke-width="5.5"/>
  <circle cx="952" cy="350" r="196" fill="${accent}" fill-opacity="0.07"/>

  ${renderStudioProp(blueprint.primary_prop, 1054, 242, 0.86, theme)}
  ${renderStudioCharacter({
    x: 854,
    y: 416,
    scale: 1.18,
    pose: blueprint.character_pose,
    expression: blueprint.character_expression,
    theme,
  })}
  ${blueprint.overlay_effect !== 'none' ? renderOverlayEffect(blueprint.overlay_effect, 1086, 514, theme) : ''}
</svg>`;
}
