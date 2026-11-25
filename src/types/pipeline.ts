export type ContentLanguage = 'vi-VN' | 'en-US';
export type AspectRatioOption = '16:9' | '9:16';
export type CronTimezone = 'ICT_0200' | 'UTC_0200';
export type TTSProviderOption = 'gemini_tts' | 'cloud_tts';
export type GeminiVoicePersona = 'Charon' | 'Fenrir' | 'Puck' | 'Kore' | 'Zephyr';
export type VideoVisualMode = 'stickman_whiteboard' | 'pen_sketch' | 'ken_burns_2d';
export type PenSketchPaperTheme = 'dark_slate' | 'classic_parchment';

export type NavSectionId =
  | 'overview'
  | 'studio'
  | 'config'
  | 'dedup'
  | 'fallback'
  | 'code'
  | 'deploy';

export interface PipelineConfig {
  language: ContentLanguage;
  aspectRatio: AspectRatioOption;
  videoVisualMode: VideoVisualMode;
  penSketchPaperTheme: PenSketchPaperTheme;
  whiteboardThemeId: string;
  whiteboardBgColor: string;
  whiteboardInkColor: string;
  whiteboardAccentColor: string;
  channelTopic: string;
  visualStylePrompt: string;
  dailyVideoCount: number;
  cronTimezone: CronTimezone;
  similarityThreshold: number;
  criticMinScore: number;
  historyRetentionDays: number;
  llmFallbackModels: string[];
  imagenFallbackModels: string[];
  ttsPrimaryProvider: TTSProviderOption;
  ttsFallbackModels: string[];
  ttsVoicePersona: GeminiVoicePersona;
  ttsVoiceStyle: string;
  embeddingFallbackModels: string[];
  musicFallbackModels: string[];
}

export interface ProjectFileEntry {
  path: string;
  name: string;
  folder: string;
  language: 'python' | 'yaml' | 'markdown' | 'text';
  summary: string;
  isDynamic?: boolean;
  content: string;
}

export interface MatrixComboItem {
  slot: number;
  philosopher: string;
  modernContext: string;
  narrativeHook: string;
  estimatedWords: string;
  sampleQuote: string;
}

export interface LiveStudioVisualBeat {
  beat_id: number;
  phrase: string;
  short_label: string;
  image_prompt: string;
  imageUrl?: string;
  svgMarkup?: string;
  svgThemeColors?: {
    bgColor: string;
    inkColor: string;
    accentColor: string;
    surfaceFill: string;
  };
  imageModelUsed?: string;
  regenerating?: boolean;
}

export interface LiveStudioScene {
  scene_id: number;
  chapter_header?: string;
  layout_type?: string;
  scene_label?: string;
  narration: string;
  quote_overlay: string;
  motion_type: 'zoom_in' | 'zoom_out' | 'pan_left' | 'pan_right';
  visual_theme?: string;
  image_prompt?: string;
  visual_beats?: LiveStudioVisualBeat[];
  imageUrl?: string;
  svgMarkup?: string;
  svgThemeColors?: {
    bgColor: string;
    inkColor: string;
    accentColor: string;
    surfaceFill: string;
  };
  imageSource?:
    | 'ai_stickman_whiteboard'
    | 'vertex_imagen'
    | 'ai_vector_content'
    | 'thematic_match';
  imageModelUsed?: string;
  regeneratingImage?: boolean;
  audioUrl?: string;
  audioDuration?: number;
  ttsModelUsed?: string;
}
