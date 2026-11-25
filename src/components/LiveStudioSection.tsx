import { useEffect, useRef, useState } from 'react';
import {
  Clock,
  Download,
  Film,
  FolderOpen,
  Image as ImageIcon,
  Loader2,
  Palette,
  Play,
  RefreshCw,
  Sparkles,
  Volume2,
} from 'lucide-react';
import { VOICE_PERSONA_OPTIONS } from '../data/projectFiles';
import { STUDIO_TOPIC_PRESETS } from '../data/sceneVisuals';
import {
  buildCustomWhiteboardTheme,
  resolveWhiteboardTheme,
  rethemeStickmanSvg,
  svgMarkupToDataUrl,
  WHITEBOARD_THEME_PRESETS,
  type WhiteboardTheme,
} from '../data/whiteboardThemes';
import type {
  GeminiVoicePersona,
  LiveStudioScene,
  LiveStudioVisualBeat,
  PenSketchPaperTheme,
  PipelineConfig,
  VideoVisualMode,
} from '../types/pipeline';
import {
  preparePenSketchAsset,
  renderPenSketchFrame,
  type PenSketchAsset,
} from '../utils/penSketchCanvas';
import {
  extractAudioEnergyEnvelope,
  LivingBeatDeck,
  renderLivingBeatFrame,
  renderVoiceEqualizerBadge,
  sampleAudioEnergy,
  type LivingBeatRecipe,
} from '../utils/studioMotionRenderer';

interface LiveStudioSectionProps {
  config: PipelineConfig;
}

type StudioDurationMode = 'full_5min' | 'quick_45s';

function base64ToBlob(base64: string, mimeType: string): Blob {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Blob([bytes], { type: mimeType });
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Không thể tải ảnh minh họa: ${src.slice(0, 80)}`));
    img.src = src;
  });
}

function formatDurationMmSs(totalSec: number): string {
  const rounded = Math.max(0, Math.round(totalSec));
  const mins = Math.floor(rounded / 60);
  const secs = rounded % 60;
  return mins > 0 ? `${mins}m ${String(secs).padStart(2, '0')}s` : `${secs}s`;
}

function formatNumberedDriveFolder(seqNumber: number, rawTitle: string): string {
  const cleaned = rawTitle
    .replace(/[\\/:*?"<>|]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 72);
  return `${Math.max(1, seqNumber)} - ${cleaned || 'Video Moi'}`;
}

function slugifyFilename(rawTitle: string): string {
  const normalized = rawTitle
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
    .replace(/Đ/g, 'D')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 48);
  return normalized || 'video';
}

function wrapCanvasText(
  ctx: CanvasRenderingContext2D,
  text: string,
  maxWidth: number
): string[] {
  const words = text.split(/\s+/);
  const lines: string[] = [];
  let current = '';
  for (const word of words) {
    const test = current ? `${current} ${word}` : word;
    if (ctx.measureText(test).width > maxWidth && current) {
      lines.push(current);
      current = word;
    } else {
      current = test;
    }
  }
  if (current) lines.push(current);
  return lines;
}

async function runWithConcurrency<T>(
  items: T[],
  concurrency: number,
  worker: (item: T, index: number) => Promise<void>
): Promise<void> {
  let cursor = 0;
  const runners = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (cursor < items.length) {
      const idx = cursor++;
      await worker(items[idx], idx);
    }
  });
  await Promise.all(runners);
}

export function LiveStudioSection({ config }: LiveStudioSectionProps) {
  const [topic, setTopic] = useState(
    config.language === 'vi-VN'
      ? '4 nguyên lý Khắc kỷ giúp bạn giữ bình tĩnh tuyệt đối khi bị công kích'
      : '4 Stoic principles to stay completely calm under criticism and pressure'
  );
  const [philosopher, setPhilosopher] = useState('Marcus Aurelius');
  const [durationMode, setDurationMode] = useState<StudioDurationMode>('full_5min');
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1.25);
  const [preferredTtsModel, setPreferredTtsModel] = useState<string>(
    config.ttsFallbackModels[0] || 'gemini-3.8-flash-lite-tts'
  );
  const [voicePersona, setVoicePersona] = useState<GeminiVoicePersona>(
    config.ttsVoicePersona
  );
  const [visualMode, setVisualMode] = useState<VideoVisualMode>(
    config.videoVisualMode || 'stickman_whiteboard'
  );
  const [paperTheme, setPaperTheme] = useState<PenSketchPaperTheme>(
    config.penSketchPaperTheme || 'classic_parchment'
  );
  const [activeTheme, setActiveTheme] = useState<WhiteboardTheme>(() =>
    resolveWhiteboardTheme(
      config.whiteboardThemeId,
      config.whiteboardBgColor,
      config.whiteboardAccentColor
    )
  );

  const [generating, setGenerating] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string>('');
  const [errorMessage, setErrorMessage] = useState<string>('');
  const [videoTitle, setVideoTitle] = useState<string>('');
  const [coreQuote, setCoreQuote] = useState<string>('');
  const [thumbnailHook, setThumbnailHook] = useState<string>('');
  const [thumbnailPrompt, setThumbnailPrompt] = useState<string>('');
  const [scriptModelUsed, setScriptModelUsed] = useState<string>('');
  const [scenes, setScenes] = useState<LiveStudioScene[]>([]);
  const [activeBeatByScene, setActiveBeatByScene] = useState<Record<number, number>>({});

  const [thumbnailData, setThumbnailData] = useState<{
    imageUrl: string;
    svgMarkup?: string;
    themeColors?: {
      bgColor: string;
      inkColor: string;
      accentColor: string;
      surfaceFill: string;
    };
    modelUsed?: string;
    regenerating: boolean;
  } | null>(null);

  const [driveFolderInfo, setDriveFolderInfo] = useState<{
    connected: boolean;
    existingCount: number;
    maxNumber: number;
    nextNumber: number;
    sampleFolders: string[];
  }>({
    connected: false,
    existingCount: 0,
    maxNumber: 0,
    nextNumber: 1,
    sampleFolders: [],
  });

  const [renderingVideo, setRenderingVideo] = useState(false);
  const [convertingMp4, setConvertingMp4] = useState(false);
  const [renderProgress, setRenderProgress] = useState(0);
  const [renderedVideoUrl, setRenderedVideoUrl] = useState<string | null>(null);
  const [renderedVideoExt, setRenderedVideoExt] = useState<'mp4' | 'webm'>('mp4');
  const [gcpProjectLabel, setGcpProjectLabel] = useState<string | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    let active = true;
    fetch('/api/gcp/status')
      .then((res) => res.json())
      .then((data: { mode?: string; projectId?: string | null; source?: string | null }) => {
        if (!active) return;
        if (data.mode === 'service_account_json' && data.projectId) {
          setGcpProjectLabel(`GCP JSON: ${data.projectId} (${data.source})`);
        }
      })
      .catch(() => {
        // Ignore read-only status check failures
      });

    fetch('/api/gcp/drive-next-folder')
      .then((res) => res.json())
      .then(
        (data: {
          connected?: boolean;
          existingCount?: number;
          maxNumber?: number;
          nextNumber?: number;
          sampleFolders?: string[];
        }) => {
          if (!active) return;
          setDriveFolderInfo({
            connected: Boolean(data.connected),
            existingCount: Number(data.existingCount) || 0,
            maxNumber: Number(data.maxNumber) || 0,
            nextNumber: Math.max(1, Number(data.nextNumber) || 1),
            sampleFolders: Array.isArray(data.sampleFolders) ? data.sampleFolders : [],
          });
        }
      )
      .catch(() => {
        // Fallback to starting sequence #1 when Drive is not connected in preview
      });

    return () => {
      active = false;
    };
  }, []);

  const selectedPersonaObj =
    VOICE_PERSONA_OPTIONS.find((v) => v.id === voicePersona) ?? VOICE_PERSONA_OPTIONS[0];

  const applyWhiteboardTheme = (nextTheme: WhiteboardTheme) => {
    setActiveTheme(nextTheme);
    const nextColors = {
      bgColor: nextTheme.bgColor,
      inkColor: nextTheme.inkColor,
      accentColor: nextTheme.accentColor,
      surfaceFill: nextTheme.surfaceFill,
    };
    // Đổi màu nền ngay lập tức cho toàn bộ 72–96 ảnh con + phân cảnh SVG mà không cần gọi AI vẽ lại
    setScenes((prev) =>
      prev.map((scene) => {
        const updatedBeats = scene.visual_beats?.map((beat) => {
          if (!beat.svgMarkup) return beat;
          const nextBeatSvg = rethemeStickmanSvg(beat.svgMarkup, nextTheme, beat.svgThemeColors);
          return {
            ...beat,
            svgMarkup: nextBeatSvg,
            imageUrl: svgMarkupToDataUrl(nextBeatSvg),
            svgThemeColors: nextColors,
          };
        });

        let updatedSceneSvg = scene.svgMarkup;
        let updatedSceneUrl = scene.imageUrl;
        if (scene.svgMarkup && scene.imageSource === 'ai_stickman_whiteboard') {
          updatedSceneSvg = rethemeStickmanSvg(scene.svgMarkup, nextTheme, scene.svgThemeColors);
          updatedSceneUrl = svgMarkupToDataUrl(updatedSceneSvg);
        } else if (updatedBeats && updatedBeats[0]?.imageUrl) {
          updatedSceneUrl = updatedBeats[0].imageUrl;
          updatedSceneSvg = updatedBeats[0].svgMarkup;
        }

        return {
          ...scene,
          svgMarkup: updatedSceneSvg,
          imageUrl: updatedSceneUrl,
          svgThemeColors: nextColors,
          visual_beats: updatedBeats,
        };
      })
    );
    // Đồng thời đổi màu nền ngay lập tức cho Thumbnail YouTube
    setThumbnailData((prev) => {
      if (!prev || !prev.svgMarkup) return prev;
      const updatedSvg = rethemeStickmanSvg(prev.svgMarkup, nextTheme, prev.themeColors);
      return {
        ...prev,
        svgMarkup: updatedSvg,
        imageUrl: svgMarkupToDataUrl(updatedSvg),
        themeColors: {
          bgColor: nextTheme.bgColor,
          inkColor: nextTheme.inkColor,
          accentColor: nextTheme.accentColor,
          surfaceFill: nextTheme.surfaceFill,
        },
      };
    });
  };

  const requestYoutubeThumbnail = async (
    params: {
      title: string;
      hook: string;
      prompt: string;
      quote: string;
      folderNumber: number;
    },
    themeForThumb: WhiteboardTheme
  ) => {
    const thumbRes = await fetch('/api/studio/generate-thumbnail', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: params.title,
        thumbnailHook: params.hook,
        thumbnailPrompt: params.prompt,
        coreQuote: params.quote,
        folderNumber: params.folderNumber,
        language: config.language,
        bgColor: themeForThumb.bgColor,
        inkColor: themeForThumb.inkColor,
        accentColor: themeForThumb.accentColor,
        surfaceFill: themeForThumb.surfaceFill,
      }),
    });
    const thumbJson = await thumbRes.json();
    if (!thumbRes.ok || !thumbJson.imageDataUrl) {
      throw new Error(thumbJson.error || 'Không thể tạo Thumbnail YouTube.');
    }
    return {
      imageUrl: String(thumbJson.imageDataUrl),
      svgMarkup: thumbJson.svgMarkup ? String(thumbJson.svgMarkup) : undefined,
      themeColors: thumbJson.themeColors || {
        bgColor: themeForThumb.bgColor,
        inkColor: themeForThumb.inkColor,
        accentColor: themeForThumb.accentColor,
        surfaceFill: themeForThumb.surfaceFill,
      },
      modelUsed: String(thumbJson.modelUsed || 'AI YouTube Thumbnail'),
      regenerating: false,
    };
  };

  const handleRegenerateThumbnail = async () => {
    if (!videoTitle || thumbnailData?.regenerating) return;
    setThumbnailData((prev) =>
      prev
        ? { ...prev, regenerating: true }
        : { imageUrl: '', regenerating: true }
    );
    setErrorMessage('');
    try {
      const nextThumb = await requestYoutubeThumbnail(
        {
          title: videoTitle,
          hook: thumbnailHook || videoTitle,
          prompt: thumbnailPrompt || videoTitle,
          quote: coreQuote,
          folderNumber: driveFolderInfo.nextNumber,
        },
        activeTheme
      );
      setThumbnailData(nextThumb);
    } catch (err: unknown) {
      setThumbnailData((prev) => (prev ? { ...prev, regenerating: false } : null));
      setErrorMessage(
        err instanceof Error ? err.message : 'Lỗi khi vẽ lại Thumbnail YouTube.'
      );
    }
  };

  const handleDownloadThumbnailPng = async () => {
    if (!thumbnailData?.imageUrl) return;
    try {
      const img = await loadImage(thumbnailData.imageUrl);
      const offscreen = document.createElement('canvas');
      offscreen.width = 1280;
      offscreen.height = 720;
      const ctx = offscreen.getContext('2d');
      if (!ctx) return;
      ctx.fillStyle = activeTheme.bgColor;
      ctx.fillRect(0, 0, 1280, 720);
      ctx.drawImage(img, 0, 0, 1280, 720);
      const pngUrl = offscreen.toDataURL('image/png');
      const link = document.createElement('a');
      link.href = pngUrl;
      link.download = `${driveFolderInfo.nextNumber}_thumbnail.png`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch {
      setErrorMessage('Không thể xuất tệp PNG cho Thumbnail.');
    }
  };

  const requestSceneImage = async (
    scene: LiveStudioScene,
    modeForImage: VideoVisualMode,
    themeForImage: WhiteboardTheme,
    isRegenerate = false
  ): Promise<{
    imageUrl: string;
    svgMarkup?: string;
    svgThemeColors?: LiveStudioScene['svgThemeColors'];
    imageSource: LiveStudioScene['imageSource'];
    imageModelUsed: string;
  }> => {
    const styleMode =
      modeForImage === 'stickman_whiteboard' ? 'stickman_whiteboard' : 'editorial_sketch';

    let lastErr: unknown = null;
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const imgRes = await fetch('/api/studio/generate-image', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            narration: scene.narration,
            imagePrompt: scene.image_prompt,
            sceneLabel: scene.scene_label,
            chapterHeader: scene.chapter_header,
            layoutType: scene.layout_type,
            language: config.language,
            styleMode,
            bgColor: themeForImage.bgColor,
            inkColor: themeForImage.inkColor,
            accentColor: themeForImage.accentColor,
            surfaceFill: themeForImage.surfaceFill,
            visualStylePrompt: config.visualStylePrompt,
            paperTheme,
            aspectRatio: config.aspectRatio,
            isRegenerate,
          }),
        });
        const imgData = await imgRes.json();
        if (!imgRes.ok || !imgData.imageDataUrl) {
          throw new Error(imgData.error || `Không thể vẽ ảnh cho cảnh ${scene.scene_id}.`);
        }

        // Kiểm chứng thực tế ảnh hiển thị được trên trình duyệt (chống 100% ảnh vỡ XML)
        const loaded = await loadImage(imgData.imageDataUrl);
        if ((loaded.naturalWidth || loaded.width) <= 0 || (loaded.naturalHeight || loaded.height) <= 0) {
          throw new Error(`Ảnh trả về cho cảnh ${scene.scene_id} có kích thước rỗng.`);
        }

        return {
          imageUrl: imgData.imageDataUrl,
          svgMarkup: imgData.svgMarkup,
          svgThemeColors: imgData.themeColors || {
            bgColor: themeForImage.bgColor,
            inkColor: themeForImage.inkColor,
            accentColor: themeForImage.accentColor,
            surfaceFill: themeForImage.surfaceFill,
          },
          imageSource: imgData.source || 'ai_stickman_whiteboard',
          imageModelUsed: imgData.modelUsed || 'AI Whiteboard Stickman',
        };
      } catch (err) {
        lastErr = err;
        if (attempt === 0) {
          await new Promise((r) => setTimeout(r, 700));
        }
      }
    }

    throw lastErr instanceof Error
      ? lastErr
      : new Error(`Không thể tạo ảnh hợp lệ cho cảnh ${scene.scene_id}.`);
  };

  const requestSceneBeats = async (
    scene: LiveStudioScene,
    themeForImage: WhiteboardTheme
  ): Promise<LiveStudioVisualBeat[]> => {
    const beatsInput =
      scene.visual_beats && scene.visual_beats.length > 0
        ? scene.visual_beats
        : [
            {
              beat_id: 1,
              phrase: scene.narration,
              short_label: scene.scene_label || `Cảnh ${scene.scene_id}`,
              image_prompt: scene.image_prompt || scene.narration,
            },
          ];

    const res = await fetch('/api/studio/generate-scene-beats', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chapterHeader: scene.chapter_header,
        narration: scene.narration,
        visualBeats: beatsInput,
        language: config.language,
        bgColor: themeForImage.bgColor,
        inkColor: themeForImage.inkColor,
        accentColor: themeForImage.accentColor,
        surfaceFill: themeForImage.surfaceFill,
        aspectRatio: config.aspectRatio,
      }),
    });
    const data = await res.json();
    if (!res.ok || !Array.isArray(data.beats)) {
      throw new Error(data.error || `Không thể tạo chuỗi ảnh cho cảnh ${scene.scene_id}.`);
    }

    const mapped: LiveStudioVisualBeat[] = beatsInput.map((b, idx) => {
      const returned = data.beats[idx];
      return {
        ...b,
        imageUrl: returned?.imageDataUrl,
        svgMarkup: returned?.svgMarkup,
        svgThemeColors: returned?.themeColors || {
          bgColor: themeForImage.bgColor,
          inkColor: themeForImage.inkColor,
          accentColor: themeForImage.accentColor,
          surfaceFill: themeForImage.surfaceFill,
        },
        imageModelUsed: returned?.modelUsed || data.modelUsed || 'AI Multi-Shot',
        regenerating: false,
      };
    });

    // Kiểm chứng nhẹ ảnh đầu tiên tải hợp lệ trên trình duyệt
    if (mapped[0]?.imageUrl) {
      await loadImage(mapped[0].imageUrl);
    }
    return mapped;
  };

  const handleRegenerateSingleImage = async (sceneIndex: number, beatIndex?: number) => {
    const target = scenes[sceneIndex];
    if (!target) return;

    const beats = target.visual_beats;
    if (
      visualMode === 'stickman_whiteboard' &&
      beats &&
      beats.length > 0 &&
      typeof beatIndex === 'number' &&
      beats[beatIndex]
    ) {
      const targetBeat = beats[beatIndex];
      if (targetBeat.regenerating) return;

      setScenes((prev) =>
        prev.map((s, idx) =>
          idx === sceneIndex
            ? {
                ...s,
                visual_beats: s.visual_beats?.map((b, bIdx) =>
                  bIdx === beatIndex ? { ...b, regenerating: true } : b
                ),
              }
            : s
        )
      );
      setErrorMessage('');

      try {
        const singleRes = await fetch('/api/studio/generate-scene-beats', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            chapterHeader: target.chapter_header,
            narration: targetBeat.phrase || target.narration,
            visualBeats: [targetBeat],
            language: config.language,
            bgColor: activeTheme.bgColor,
            inkColor: activeTheme.inkColor,
            accentColor: activeTheme.accentColor,
            surfaceFill: activeTheme.surfaceFill,
            aspectRatio: config.aspectRatio,
            isRegenerate: true,
          }),
        });
        const singleData = await singleRes.json();
        const refreshed = singleData.beats?.[0];
        if (!singleRes.ok || !refreshed?.imageDataUrl) {
          throw new Error(singleData.error || 'Không thể vẽ lại ảnh cho cụm ý này.');
        }
        await loadImage(refreshed.imageDataUrl);

        setScenes((prev) =>
          prev.map((s, idx) => {
            if (idx !== sceneIndex) return s;
            const nextBeats = s.visual_beats?.map((b, bIdx) =>
              bIdx === beatIndex
                ? {
                    ...b,
                    imageUrl: refreshed.imageDataUrl,
                    svgMarkup: refreshed.svgMarkup,
                    svgThemeColors: refreshed.themeColors,
                    imageModelUsed: refreshed.modelUsed || singleData.modelUsed,
                    regenerating: false,
                  }
                : b
            );
            return {
              ...s,
              visual_beats: nextBeats,
              imageUrl: beatIndex === 0 ? refreshed.imageDataUrl : s.imageUrl,
              svgMarkup: beatIndex === 0 ? refreshed.svgMarkup : s.svgMarkup,
            };
          })
        );
      } catch (err: unknown) {
        setScenes((prev) =>
          prev.map((s, idx) =>
            idx === sceneIndex
              ? {
                  ...s,
                  visual_beats: s.visual_beats?.map((b, bIdx) =>
                    bIdx === beatIndex ? { ...b, regenerating: false } : b
                  ),
                }
              : s
          )
        );
        setErrorMessage(
          err instanceof Error ? err.message : `Lỗi khi vẽ lại ảnh #${beatIndex + 1} cảnh ${target.scene_id}.`
        );
      }
      return;
    }

    if (target.regeneratingImage) return;
    setScenes((prev) =>
      prev.map((s, idx) => (idx === sceneIndex ? { ...s, regeneratingImage: true } : s))
    );
    setErrorMessage('');

    try {
      const result = await requestSceneImage(target, visualMode, activeTheme, true);
      setScenes((prev) =>
        prev.map((s, idx) =>
          idx === sceneIndex
            ? {
                ...s,
                ...result,
                regeneratingImage: false,
              }
            : s
        )
      );
    } catch (err: unknown) {
      setScenes((prev) =>
        prev.map((s, idx) => (idx === sceneIndex ? { ...s, regeneratingImage: false } : s))
      );
      setErrorMessage(
        err instanceof Error ? err.message : `Lỗi khi vẽ lại ảnh cảnh ${target.scene_id}.`
      );
    }
  };

  const handleGenerateScriptImagesAndVoice = async () => {
    setGenerating(true);
    setErrorMessage('');
    setRenderedVideoUrl(null);
    setThumbnailData(null);
    setActiveBeatByScene({});
    setScenes([]);

    const expectedCount = durationMode === 'full_5min' ? 24 : 6;

    try {
      setStatusMessage(
        durationMode === 'full_5min'
          ? 'Bước 1/3: Đang viết kịch bản 5 phút & tách 72–96 ảnh theo từng cụm ý (~3–4s đổi 1 hình)...'
          : 'Bước 1/3: Đang viết kịch bản test nhanh 45s & tách 18–24 ảnh theo từng cụm ý...'
      );

      const scriptRes = await fetch('/api/studio/generate-script', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic,
          language: config.language,
          philosopher,
          durationMode,
        }),
      });
      const scriptData = await scriptRes.json();
      if (!scriptRes.ok) {
        throw new Error(scriptData.error || 'Không thể tạo kịch bản từ máy chủ.');
      }

      const rawScenes = Array.isArray(scriptData.scenes)
        ? scriptData.scenes.slice(0, expectedCount)
        : [];
      if (rawScenes.length === 0) {
        throw new Error('Kịch bản trả về không có phân cảnh hợp lệ.');
      }

      const resolvedTitle = String(scriptData.title || topic);
      const resolvedQuote = String(scriptData.core_quote || '');
      const resolvedThumbHook = String(scriptData.thumbnail_hook || resolvedTitle);
      const resolvedThumbPrompt = String(scriptData.thumbnail_prompt || resolvedTitle);

      setVideoTitle(resolvedTitle);
      setCoreQuote(resolvedQuote);
      setThumbnailHook(resolvedThumbHook);
      setThumbnailPrompt(resolvedThumbPrompt);
      setScriptModelUsed(scriptData.modelUsed || 'gemini-4-hydrogen');

      const builtScenes: LiveStudioScene[] = rawScenes.map(
        (
          s: {
            scene_id?: number;
            chapter_header?: string;
            layout_type?: string;
            scene_label?: string;
            narration?: string;
            quote_overlay?: string;
            motion_type?: LiveStudioScene['motion_type'];
            image_prompt?: string;
            visual_beats?: Array<{
              beat_id?: number;
              phrase?: string;
              short_label?: string;
              image_prompt?: string;
            }>;
          },
          idx: number
        ) => {
          const narrationStr = s.narration ?? '';
          const parsedBeats: LiveStudioVisualBeat[] =
            Array.isArray(s.visual_beats) && s.visual_beats.length > 0
              ? s.visual_beats.slice(0, 4).map((b, bIdx) => ({
                  beat_id: b.beat_id ?? bIdx + 1,
                  phrase: b.phrase ?? narrationStr,
                  short_label: b.short_label ?? `Ý ${bIdx + 1}`,
                  image_prompt: b.image_prompt ?? s.image_prompt ?? narrationStr,
                  regenerating: true,
                }))
              : [
                  {
                    beat_id: 1,
                    phrase: narrationStr,
                    short_label: s.scene_label ?? `Cảnh ${idx + 1}`,
                    image_prompt: s.image_prompt ?? narrationStr,
                    regenerating: true,
                  },
                ];

          return {
            scene_id: s.scene_id ?? idx + 1,
            chapter_header: s.chapter_header ?? '',
            layout_type: s.layout_type ?? 'stickman_explain',
            scene_label: s.scene_label ?? `Cảnh ${idx + 1}`,
            narration: narrationStr,
            quote_overlay: s.quote_overlay ?? '',
            motion_type: s.motion_type ?? 'zoom_in',
            image_prompt: s.image_prompt ?? narrationStr,
            visual_beats: parsedBeats,
            regeneratingImage: true,
          };
        }
      );
      setScenes([...builtScenes]);

      const plannedTotalShots = builtScenes.reduce(
        (sum, s) => sum + (visualMode === 'stickman_whiteboard' ? s.visual_beats?.length || 1 : 1),
        0
      );

      // Khởi chạy tạo Thumbnail YouTube 1280x720 song song với bước vẽ chuỗi ảnh từng cụm ý
      setThumbnailData({ imageUrl: '', regenerating: true });
      const thumbnailPromise = requestYoutubeThumbnail(
        {
          title: resolvedTitle,
          hook: resolvedThumbHook,
          prompt: resolvedThumbPrompt,
          quote: resolvedQuote,
          folderNumber: driveFolderInfo.nextNumber,
        },
        activeTheme
      )
        .then((thumb) => {
          setThumbnailData(thumb);
        })
        .catch((err) => {
          console.warn('[YouTube Thumbnail generation failed]', err);
          setThumbnailData(null);
        });

      // Bước 2/3: Vẽ theo lô 3–4 ảnh/cảnh (~72–96 ảnh cho 5 phút), song song 3 cảnh/lượt
      let completedShots = 0;
      setStatusMessage(
        `Bước 2/3: Đang tạo Thumbnail + chuỗi ảnh theo từng cụm ý (0/${plannedTotalShots} ảnh)...`
      );

      await Promise.all([
        thumbnailPromise,
        runWithConcurrency(builtScenes, 3, async (scene, idx) => {
          try {
            if (visualMode === 'stickman_whiteboard' && scene.visual_beats && scene.visual_beats.length > 0) {
              const drawnBeats = await requestSceneBeats(scene, activeTheme);
              builtScenes[idx] = {
                ...builtScenes[idx],
                visual_beats: drawnBeats,
                imageUrl: drawnBeats[0]?.imageUrl,
                svgMarkup: drawnBeats[0]?.svgMarkup,
                svgThemeColors: drawnBeats[0]?.svgThemeColors,
                imageSource: 'ai_stickman_whiteboard',
                imageModelUsed: drawnBeats[0]?.imageModelUsed || 'AI Multi-Shot',
                regeneratingImage: false,
              };
              completedShots += drawnBeats.length;
            } else {
              const result = await requestSceneImage(scene, visualMode, activeTheme);
              builtScenes[idx] = {
                ...builtScenes[idx],
                ...result,
                regeneratingImage: false,
              };
              completedShots += 1;
            }
          } catch (err) {
            builtScenes[idx] = {
              ...builtScenes[idx],
              regeneratingImage: false,
              visual_beats: builtScenes[idx].visual_beats?.map((b) => ({
                ...b,
                regenerating: false,
              })),
            };
            completedShots += visualMode === 'stickman_whiteboard' ? scene.visual_beats?.length || 1 : 1;
            console.warn(`[Scene ${scene.scene_id} image failed]`, err);
          } finally {
            setScenes([...builtScenes]);
            setStatusMessage(
              `Bước 2/3: Đang vẽ Thumbnail & chuỗi hình ảnh từng cụm ý (${Math.min(completedShots, plannedTotalShots)}/${plannedTotalShots} ảnh)...`
            );
          }
        }),
      ]);

      // Bước 3/3: Tổng hợp giọng đọc WAV 24kHz thật cho toàn bộ các phân cảnh (song song 2 cảnh/lượt để nhanh và ổn định)
      let completedVoices = 0;
      setStatusMessage(
        `Bước 3/3: Đang tổng hợp giọng đọc AI (${voicePersona}) cho 0/${builtScenes.length} cảnh...`
      );

      const probeCtx = new AudioContext();
      try {
        await runWithConcurrency(builtScenes, 2, async (scene, idx) => {
          const ttsRes = await fetch('/api/studio/synthesize-voice', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              text: scene.narration,
              language: config.language,
              voiceName: voicePersona,
              voiceStyle: selectedPersonaObj.style,
              preferredModel: preferredTtsModel,
            }),
          });
          const ttsData = await ttsRes.json();
          if (!ttsRes.ok) {
            throw new Error(ttsData.error || `Lỗi tổng hợp giọng cảnh ${scene.scene_id}.`);
          }

          const wavBlob = base64ToBlob(ttsData.audioBase64, ttsData.mimeType || 'audio/wav');
          const audioUrl = URL.createObjectURL(wavBlob);
          const arrBuf = await wavBlob.arrayBuffer();
          const decoded = await probeCtx.decodeAudioData(arrBuf.slice(0));

          builtScenes[idx] = {
            ...builtScenes[idx],
            audioUrl,
            audioDuration: decoded.duration,
            ttsModelUsed: ttsData.modelUsed,
          };
          completedVoices += 1;
          setScenes([...builtScenes]);
          setStatusMessage(
            `Bước 3/3: Đang tổng hợp giọng đọc AI (${voicePersona}) cho ${completedVoices}/${builtScenes.length} cảnh...`
          );
        });
      } finally {
        await probeCtx.close();
      }

      const finalDur = builtScenes.reduce((acc, s) => acc + (s.audioDuration || 0), 0);
      const speedAdjustedDur = finalDur / playbackSpeed;
      const finalShotsCount = builtScenes.reduce(
        (sum, s) => sum + (visualMode === 'stickman_whiteboard' ? s.visual_beats?.length || 1 : 1),
        0
      );
      setStatusMessage(
        `Hoàn tất ${finalShotsCount} ảnh minh họa theo từng cụm ý (${builtScenes.length} phân cảnh · thời lượng ở ${playbackSpeed}x: ~${formatDurationMmSs(speedAdjustedDur)}). Bấm "Dựng Video MP4" để xuất tệp!`
      );
    } catch (err: unknown) {
      setErrorMessage(
        err instanceof Error ? err.message : 'Đã xảy ra lỗi không xác định khi tạo nội dung.'
      );
      setStatusMessage('');
    } finally {
      setGenerating(false);
    }
  };

  const handleRenderVideoWithVoice = async () => {
    if (scenes.length === 0 || scenes.some((s) => !s.audioUrl || !s.imageUrl)) return;
    setRenderingVideo(true);
    setConvertingMp4(false);
    setRenderProgress(0);
    setErrorMessage('');
    setRenderedVideoUrl(null);
    setRenderedVideoExt('mp4');

    try {
      const isVertical = config.aspectRatio === '9:16';
      const width = isVertical ? 720 : 1280;
      const height = isVertical ? 1280 : 720;

      // Chờ 1 nhịp vẽ để React hiển thị đúng thẻ <canvas ref={canvasRef}> duy nhất trước khi lấy context
      await new Promise<void>((r) => requestAnimationFrame(() => r()));

      const canvas = canvasRef.current ?? document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('Trình duyệt không hỗ trợ Canvas 2D.');

      // Chuẩn bị bộ đệm cuốn Raster Deck (chỉ giữ 5 beat quanh khung hiện tại -> 0ms blit, không đơ máy!)
      let beatDeck: LivingBeatDeck | null = null;
      let multiBeatBounds: number[][] = [];
      let sceneBeatOffsets: number[] = [];
      let sceneBeatCounts: number[] = [];
      let images: HTMLImageElement[] = [];
      let sketchAssets: PenSketchAsset[] = [];

      if (visualMode === 'stickman_whiteboard') {
        setStatusMessage(
          'Đang khởi tạo bộ đệm hoạt ảnh đa lớp 30fps (tối ưu GPU chống đứng hình)...'
        );
        const flatRecipes: LivingBeatRecipe[] = [];
        let runningBeatOffset = 0;

        for (const s of scenes) {
          sceneBeatOffsets.push(runningBeatOffset);
          if (s.visual_beats && s.visual_beats.length > 0) {
            sceneBeatCounts.push(s.visual_beats.length);
            for (const b of s.visual_beats) {
              flatRecipes.push({
                svgMarkup: b.svgMarkup ?? s.svgMarkup,
                fallbackImageUrl: b.imageUrl || s.imageUrl!,
                width,
                height,
              });
            }
            runningBeatOffset += s.visual_beats.length;
          } else {
            sceneBeatCounts.push(1);
            flatRecipes.push({
              svgMarkup: s.svgMarkup,
              fallbackImageUrl: s.imageUrl!,
              width,
              height,
            });
            runningBeatOffset += 1;
          }
        }

        beatDeck = new LivingBeatDeck(flatRecipes);
        await beatDeck.warmUp(0);

        multiBeatBounds = scenes.map((s) => {
          const beats = s.visual_beats && s.visual_beats.length > 0 ? s.visual_beats : [];
          if (beats.length <= 1) return [0, 1];
          const weights = beats.map((b) =>
            Math.max(3, (b.phrase || '').trim().split(/\s+/).filter(Boolean).length)
          );
          const totalW = weights.reduce((a, b) => a + b, 0) || beats.length;
          const bounds: number[] = [0];
          let acc = 0;
          for (const w of weights) {
            acc += w / totalW;
            bounds.push(Math.min(1, acc));
          }
          bounds[bounds.length - 1] = 1;
          return bounds;
        });
      } else {
        images = await Promise.all(scenes.map((s) => loadImage(s.imageUrl!)));
        if (visualMode === 'pen_sketch') {
          sketchAssets = images.map((img) =>
            preparePenSketchAsset(img, width, height, paperTheme)
          );
        }
      }

      const audioCtx = new AudioContext();
      const audioBuffers: AudioBuffer[] = [];
      for (const scene of scenes) {
        const resp = await fetch(scene.audioUrl!);
        const arrBuf = await resp.arrayBuffer();
        const decoded = await audioCtx.decodeAudioData(arrBuf);
        audioBuffers.push(decoded);
      }

      // Phân tích biên độ năng lượng giọng nói thật (30 mẫu/giây) để nhân vật & sóng âm phản ứng sống động
      const audioEnvelopes: number[][] = audioBuffers.map((buf) =>
        extractAudioEnergyEnvelope(buf, 30)
      );

      const sceneGapSec = 0.25;
      const totalDuration = audioBuffers.reduce((sum, b) => sum + b.duration + sceneGapSec, 0);
      const dest = audioCtx.createMediaStreamDestination();
      const canvasStream = canvas.captureStream(30);
      const combinedStream = new MediaStream([
        ...canvasStream.getVideoTracks(),
        ...dest.stream.getAudioTracks(),
      ]);

      // Ưu tiên VP8 khi ghi thời gian thực trên trình duyệt (nhanh gấp 4–6 lần VP9, không bị đơ khung hình),
      // sau đó máy chủ FFmpeg sẽ đóng gói lại thành H.264 MP4 sắc nét 30fps.
      const mimeCandidates = [
        'video/webm;codecs=vp8,opus',
        'video/webm;codecs=vp9,opus',
        'video/webm',
      ];
      const chosenMime =
        mimeCandidates.find((m) => MediaRecorder.isTypeSupported(m)) || 'video/webm';

      const recorder = new MediaRecorder(combinedStream, {
        mimeType: chosenMime,
        videoBitsPerSecond: 3_200_000,
      });

      const chunks: BlobPart[] = [];
      recorder.ondataavailable = (ev) => {
        if (ev.data.size > 0) chunks.push(ev.data);
      };

      const recordingDone = new Promise<Blob>((resolve) => {
        recorder.onstop = () => resolve(new Blob(chunks, { type: chosenMime }));
      });

      await audioCtx.resume();
      recorder.start(250);

      const startAudioTime = audioCtx.currentTime + 0.1;
      let cursor = startAudioTime;
      const sceneTimeline: { start: number; duration: number }[] = [];

      audioBuffers.forEach((buf) => {
        const src = audioCtx.createBufferSource();
        src.buffer = buf;
        src.connect(dest);
        src.connect(audioCtx.destination);
        src.start(cursor);
        const segDur = buf.duration + sceneGapSec;
        sceneTimeline.push({ start: cursor - startAudioTime, duration: segDur });
        cursor += segDur;
      });

      try {
        await new Promise<void>((resolve) => {
          let finished = false;
          let lastReportedPct = -1;
          let lastDrawWallMs = 0;
          let timerId: number | null = null;
          let rafId: number | null = null;

          const finishRecording = () => {
            if (finished) return;
            finished = true;
            if (timerId !== null) window.clearTimeout(timerId);
            if (rafId !== null) cancelAnimationFrame(rafId);
            if (recorder.state !== 'inactive') {
              recorder.stop();
            }
            resolve();
          };

          const drawFrame = () => {
            if (finished) return;
            if (timerId !== null) {
              window.clearTimeout(timerId);
              timerId = null;
            }
            if (rafId !== null) {
              cancelAnimationFrame(rafId);
              rafId = null;
            }

            const nowMs = performance.now();
            // Giới hạn đúng nhịp ~30fps để không làm quá tải trình duyệt 60Hz/120Hz
            if (nowMs - lastDrawWallMs < 30) {
              timerId = window.setTimeout(drawFrame, 45);
              rafId = requestAnimationFrame(drawFrame);
              return;
            }
            lastDrawWallMs = nowMs;

            if (audioCtx.state === 'suspended') {
              void audioCtx.resume();
            }

            const elapsed = Math.max(0, audioCtx.currentTime - startAudioTime);
            const overallProgress = Math.min(1, elapsed / Math.max(totalDuration, 0.1));
            const pct = Math.round(overallProgress * 100);
            if (pct !== lastReportedPct) {
              lastReportedPct = pct;
              setRenderProgress(pct);
            }

            try {
              let activeIdx = sceneTimeline.length - 1;
              for (let i = 0; i < sceneTimeline.length; i++) {
                const seg = sceneTimeline[i];
                if (elapsed >= seg.start && elapsed < seg.start + seg.duration) {
                  activeIdx = i;
                  break;
                }
              }

              const seg = sceneTimeline[activeIdx];
              const localSec = Math.max(0, elapsed - seg.start);
              const localP = Math.max(
                0,
                Math.min(1, localSec / Math.max(seg.duration, 0.1))
              );
              const scene = scenes[activeIdx];
              const voiceEnergy = sampleAudioEnergy(audioEnvelopes[activeIdx] || [], localSec, 30);

              if (visualMode === 'stickman_whiteboard' && beatDeck) {
                const beatCount = sceneBeatCounts[activeIdx] || 1;
                const bounds = multiBeatBounds[activeIdx] || [0, 1];
                let bIdx = beatCount - 1;
                for (let i = 0; i < beatCount; i++) {
                  if (localP >= bounds[i] && localP < bounds[i + 1]) {
                    bIdx = i;
                    break;
                  }
                }
                const bStart = bounds[bIdx] ?? 0;
                const bEnd = bounds[bIdx + 1] ?? 1;
                const beatP = Math.max(
                  0,
                  Math.min(1, (localP - bStart) / Math.max(0.01, bEnd - bStart))
                );

                const beatGlobalIndex = (sceneBeatOffsets[activeIdx] ?? 0) + bIdx;
                const currentAsset = beatDeck.getReadyBeat(beatGlobalIndex);
                const prevAsset =
                  beatGlobalIndex > 0 ? beatDeck.getCachedOnly(beatGlobalIndex - 1) : undefined;

                if (currentAsset) {
                  renderLivingBeatFrame({
                    ctx,
                    asset: currentAsset,
                    prevAsset,
                    beatP,
                    elapsedSec: elapsed,
                    beatGlobalIndex,
                    voiceEnergy,
                    theme: activeTheme,
                  });
                }

                // Thanh tiến trình siêu mảnh đồng bộ màu nhấn sát mép dưới
                const barH = 5;
                ctx.fillStyle = activeTheme.isDark
                  ? 'rgba(255, 255, 255, 0.14)'
                  : 'rgba(15, 23, 42, 0.12)';
                ctx.fillRect(0, height - barH, width, barH);
                ctx.fillStyle = activeTheme.accentColor;
                ctx.fillRect(0, height - barH, width * overallProgress, barH);
              } else {
                const img = images[activeIdx];
                if (visualMode === 'pen_sketch' && sketchAssets[activeIdx]) {
                  renderPenSketchFrame(ctx, sketchAssets[activeIdx], localP);
                } else if (img) {
                  ctx.fillStyle = '#0B0F17';
                  ctx.fillRect(0, 0, width, height);

                  // Eased sine camera motion + nhịp thở nhẹ thay cho zoom tuyến tính cứng nhắc
                  const eased = 0.5 - 0.5 * Math.cos(Math.PI * localP);
                  const breath = Math.sin(elapsed * 2.0) * 0.006 + voiceEnergy * 0.008;
                  const baseScale = Math.max(width / img.width, height / img.height);
                  let zoom = 1.07 + breath;
                  let offsetX = 0;
                  let offsetY = Math.sin(elapsed * 1.4) * 5;
                  if (scene.motion_type === 'zoom_in') {
                    zoom = 1.03 + 0.1 * eased + breath;
                  } else if (scene.motion_type === 'zoom_out') {
                    zoom = 1.13 - 0.1 * eased + breath;
                  } else if (scene.motion_type === 'pan_left') {
                    zoom = 1.12 + breath;
                    offsetX = (0.5 - eased) * width * 0.085;
                  } else {
                    zoom = 1.12 + breath;
                    offsetX = (eased - 0.5) * width * 0.085;
                  }

                  const drawW = img.width * baseScale * zoom;
                  const drawH = img.height * baseScale * zoom;
                  const dx = (width - drawW) / 2 + offsetX;
                  const dy = (height - drawH) / 2 + offsetY;
                  ctx.drawImage(img, dx, dy, drawW, drawH);
                }

                const grad = ctx.createLinearGradient(0, height * 0.65, 0, height);
                grad.addColorStop(0, 'rgba(10, 13, 19, 0)');
                grad.addColorStop(1, 'rgba(10, 13, 19, 0.82)');
                ctx.fillStyle = grad;
                ctx.fillRect(0, height * 0.65, width, height * 0.35);

                const margin = Math.round(Math.min(width, height) * 0.036);
                ctx.strokeStyle = 'rgba(197, 160, 89, 0.42)';
                ctx.lineWidth = 2;
                ctx.strokeRect(margin, margin, width - margin * 2, height - margin * 2);

                renderVoiceEqualizerBadge(ctx, voiceEnergy, elapsed, {
                  bgColor: '#0B0F17',
                  inkColor: '#F2EEE4',
                  accentColor: '#C5A059',
                  isDark: true,
                });

                const barX = margin + Math.round(width * 0.04);
                const barY = height - margin - 24;
                const barW = width - barX * 2;
                ctx.fillStyle = 'rgba(255,255,255,0.18)';
                ctx.fillRect(barX, barY, barW, 5);
                ctx.fillStyle = '#C5A059';
                ctx.fillRect(barX, barY, barW * overallProgress, 5);

                if (scene.quote_overlay) {
                  const fontSize = isVertical ? 28 : 30;
                  ctx.font = `600 ${fontSize}px "Plus Jakarta Sans", sans-serif`;
                  const wrapped = wrapCanvasText(
                    ctx,
                    `“${scene.quote_overlay}”`,
                    width - margin * 4
                  );
                  const lineH = fontSize * 1.38;
                  const blockH = wrapped.length * lineH + 28;
                  const boxY = barY - blockH - 26;
                  const boxW = Math.min(width - margin * 3, 940);
                  const boxX = (width - boxW) / 2;

                  ctx.fillStyle = 'rgba(11, 14, 20, 0.78)';
                  ctx.fillRect(boxX, boxY, boxW, blockH);
                  ctx.strokeStyle = 'rgba(197, 160, 89, 0.45)';
                  ctx.lineWidth = 1;
                  ctx.strokeRect(boxX, boxY, boxW, blockH);

                  ctx.fillStyle = '#F2EEE4';
                  ctx.textAlign = 'center';
                  ctx.textBaseline = 'top';
                  wrapped.forEach((line, lIdx) => {
                    ctx.fillText(line, width / 2, boxY + 14 + lIdx * lineH);
                  });
                }
              }
            } catch (frameErr) {
              console.warn('[Studio drawFrame warning]', frameErr);
            }

            if (elapsed < totalDuration) {
              // Dự phòng hẹn giờ nếu người dùng chuyển sang tab khác khiến rAF bị giảm nhịp
              if (timerId !== null) window.clearTimeout(timerId);
              timerId = window.setTimeout(drawFrame, 60);
              rafId = requestAnimationFrame(drawFrame);
            } else {
              finishRecording();
            }
          };

          rafId = requestAnimationFrame(drawFrame);
        });
      } finally {
        beatDeck?.disposeAll();
      }

      const recordedBlob = await recordingDone;
      await audioCtx.close();

      // Tự động đóng gói chuẩn MP4 (H.264 + AAC) và tăng tốc độ chuẩn (mặc định 1.25x, giữ nguyên cao độ giọng) qua FFmpeg máy chủ
      setConvertingMp4(true);
      setStatusMessage(
        `Đang đóng gói chuẩn MP4 (H.264 + AAC) và xử lý tốc độ ${playbackSpeed}x bằng FFmpeg...`
      );
      try {
        const mp4Res = await fetch(`/api/studio/convert-mp4?speed=${playbackSpeed}`, {
          method: 'POST',
          headers: { 'Content-Type': chosenMime || 'video/webm' },
          body: recordedBlob,
        });
        if (!mp4Res.ok) {
          throw new Error('Không thể chuyển đổi sang MP4 trên máy chủ.');
        }
        const mp4Blob = await mp4Res.blob();
        setRenderedVideoUrl(URL.createObjectURL(mp4Blob));
        setRenderedVideoExt('mp4');
        setStatusMessage(
          `Đã xuất tệp MP4 chuẩn (H.264 + AAC · tốc độ ${playbackSpeed}x) thành công!`
        );
      } catch {
        setRenderedVideoUrl(URL.createObjectURL(recordedBlob));
        setRenderedVideoExt('webm');
        setStatusMessage('Đã xuất video (dự phòng .webm do máy chủ chuyển đổi MP4 bận).');
      } finally {
        setConvertingMp4(false);
      }

      setRenderProgress(100);
    } catch (err: unknown) {
      setErrorMessage(
        err instanceof Error ? err.message : 'Lỗi khi render video kèm giọng đọc.'
      );
    } finally {
      setRenderingVideo(false);
      setConvertingMp4(false);
    }
  };

  const totalVoiceDuration = scenes.reduce((acc, s) => acc + (s.audioDuration || 0), 0);
  const totalWordCount = scenes.reduce(
    (acc, s) => acc + (s.narration.trim() ? s.narration.trim().split(/\s+/).length : 0),
    0
  );
  const totalImageCount = scenes.reduce(
    (acc, s) => acc + (s.visual_beats && s.visual_beats.length > 0 ? s.visual_beats.length : 1),
    0
  );
  const allReadyToRender =
    scenes.length > 0 && scenes.every((s) => Boolean(s.audioUrl) && Boolean(s.imageUrl));

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="space-y-1.5 pb-6 border-b border-[#1E2738]">
        <div className="flex flex-wrap items-center gap-2 text-xs text-[#94A3B8]">
          <span>{gcpProjectLabel || 'Google Cloud Vertex AI + Cloud TTS (Service Account JSON)'}</span>
          <span aria-hidden="true">·</span>
          <span>Màu nền riêng: {activeTheme.label} ({activeTheme.bgColor})</span>
          <span aria-hidden="true">·</span>
          <span>72–96 ảnh (~3–4s/ảnh) · Tốc độ {playbackSpeed}x · Xuất MP4</span>
        </div>
        <h1 className="text-2xl font-semibold text-[#F1F5F9]">
          Tạo Video giải thích dày hình 5 phút (~72–96 ảnh) có Giọng đọc AI
        </h1>
        <p className="text-sm text-[#94A3B8] max-w-3xl">
          Tự động tách từng câu nói thành 3–4 hình ảnh riêng theo từng cụm ý (cứ ~3–4 giây đổi 1 ảnh mới),
          đồng bộ bảng màu nền kênh riêng, kèm Thumbnail YouTube 1280×720 và xuất chuẩn MP4 tốc độ {playbackSpeed}x.
        </p>
      </div>

      {/* Controls Card */}
      <div className="bg-[#111722] border border-[#1E2738] rounded-lg p-6 space-y-5">
        {/* Quick Topic Presets */}
        <div className="flex flex-wrap items-center gap-2 pb-4 border-b border-[#1E2738]">
          <span className="text-xs text-[#8B9BB4] mr-1">Chủ đề mẫu dễ làm video giải thích:</span>
          {STUDIO_TOPIC_PRESETS.map((preset) => (
            <button
              key={preset.label}
              type="button"
              onClick={() => {
                setTopic(config.language === 'vi-VN' ? preset.topicVi : preset.topicEn);
                setPhilosopher(preset.philosopher);
              }}
              className="px-2.5 py-1 text-xs font-medium text-[#CBD5E1] bg-[#0B0F17] border border-[#243045] hover:border-[#C8A252] hover:text-[#F1F5F9] rounded transition-colors cursor-pointer"
            >
              {preset.label}
            </button>
          ))}
        </div>

        {/* Row 1: Topic, Philosopher, TTS Model, Voice */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
          <div className="lg:col-span-6 space-y-2">
            <label htmlFor="studio-topic" className="block text-sm font-medium text-[#E2E8F0]">
              Chủ đề / Ý tưởng video
            </label>
            <input
              id="studio-topic"
              type="text"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              className="w-full px-3.5 py-2.5 text-sm text-[#F1F5F9] bg-[#0B0F17] border border-[#243045] rounded-md focus:outline-none focus:border-[#C8A252]"
            />
          </div>

          <div className="lg:col-span-2 space-y-2">
            <label htmlFor="studio-phil" className="block text-sm font-medium text-[#E2E8F0]">
              Tư duy / Triết gia
            </label>
            <select
              id="studio-phil"
              value={philosopher}
              onChange={(e) => setPhilosopher(e.target.value)}
              className="w-full px-3 py-2.5 text-sm text-[#F1F5F9] bg-[#0B0F17] border border-[#243045] rounded-md focus:outline-none focus:border-[#C8A252]"
            >
              <option value="Marcus Aurelius">Marcus Aurelius</option>
              <option value="Seneca">Seneca</option>
              <option value="Epictetus">Epictetus</option>
              <option value="Musonius Rufus">Musonius Rufus</option>
              <option value="Tư duy tối giản Nhật Bản (Kaizen & Stoicism)">Kaizen &amp; Stoicism</option>
            </select>
          </div>

          <div className="lg:col-span-2 space-y-2">
            <label htmlFor="studio-tts-model" className="block text-sm font-medium text-[#E2E8F0]">
              Model Giọng đọc
            </label>
            <select
              id="studio-tts-model"
              value={preferredTtsModel}
              onChange={(e) => setPreferredTtsModel(e.target.value)}
              className="w-full px-3 py-2.5 text-xs font-mono text-[#F1F5F9] bg-[#0B0F17] border border-[#243045] rounded-md focus:outline-none focus:border-[#C8A252]"
            >
              <option value="gemini-3.8-flash-lite-tts">gemini-3.8-flash-lite-tts</option>
              <option value="gemini-3.8-flash-tts">gemini-3.8-flash-tts</option>
            </select>
          </div>

          <div className="lg:col-span-2 space-y-2">
            <label htmlFor="studio-voice" className="block text-sm font-medium text-[#E2E8F0]">
              Chất giọng AI
            </label>
            <select
              id="studio-voice"
              value={voicePersona}
              onChange={(e) => setVoicePersona(e.target.value as GeminiVoicePersona)}
              className="w-full px-3 py-2.5 text-sm text-[#F1F5F9] bg-[#0B0F17] border border-[#243045] rounded-md focus:outline-none focus:border-[#C8A252]"
            >
              {VOICE_PERSONA_OPTIONS.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.id}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Row 2: Duration Mode (24 ảnh vs 6 ảnh), Playback Speed (1.25x), Visual Style */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 pt-3 border-t border-[#1E2738]">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-medium text-[#CBD5E1] inline-flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5 text-[#C8A252]" />
              Số ảnh &amp; độ dài:
            </span>
            <div className="inline-flex gap-1 p-1 bg-[#0B0F17] border border-[#1E2738] rounded-md">
              <button
                type="button"
                onClick={() => setDurationMode('full_5min')}
                className={`px-2.5 py-1.5 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                  durationMode === 'full_5min'
                    ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                    : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                }`}
              >
                5 phút (~72–96 ảnh)
              </button>
              <button
                type="button"
                onClick={() => setDurationMode('quick_45s')}
                className={`px-2.5 py-1.5 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                  durationMode === 'quick_45s'
                    ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                    : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                }`}
              >
                45s (~18–24 ảnh)
              </button>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-medium text-[#CBD5E1]">Tốc độ video:</span>
            <div className="inline-flex gap-1 p-1 bg-[#0B0F17] border border-[#1E2738] rounded-md">
              {[1.0, 1.25, 1.5].map((spd) => (
                <button
                  key={spd}
                  type="button"
                  onClick={() => setPlaybackSpeed(spd)}
                  className={`px-2.5 py-1.5 text-xs font-mono font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                    playbackSpeed === spd
                      ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                      : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                  }`}
                >
                  {spd}x
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-medium text-[#CBD5E1]">Chuyển cảnh:</span>
            <div className="inline-flex flex-wrap gap-1 p-1 bg-[#0B0F17] border border-[#1E2738] rounded-md">
              <button
                type="button"
                onClick={() => setVisualMode('stickman_whiteboard')}
                className={`px-2.5 py-1.5 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                  visualMode === 'stickman_whiteboard'
                    ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                    : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                }`}
              >
                Nhiều ảnh mượt (Không bút)
              </button>
              <button
                type="button"
                onClick={() => setVisualMode('ken_burns_2d')}
                className={`px-2.5 py-1.5 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                  visualMode === 'ken_burns_2d'
                    ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                    : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                }`}
              >
                2D Zoom/Pan
              </button>
              <button
                type="button"
                onClick={() => setVisualMode('pen_sketch')}
                className={`px-2.5 py-1.5 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                  visualMode === 'pen_sketch'
                    ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                    : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                }`}
              >
                Bút vẽ nét
              </button>
            </div>
          </div>
        </div>

        {/* Row 3: Custom Background Palette Picker (Chống trùng nền YouTube) */}
        {visualMode === 'stickman_whiteboard' && (
          <div className="space-y-2.5 pt-3 border-t border-[#1E2738]">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-medium text-[#CBD5E1] inline-flex items-center gap-1.5">
                <Palette className="w-3.5 h-3.5 text-[#C8A252]" />
                Màu nền video (chọn màu riêng để không bị trùng nền kem YouTube — đổi màu xem trước ngay):
              </span>
              <span className="text-[11px] font-mono text-[#8B9BB4]">
                Nền {activeTheme.bgColor} · Nét {activeTheme.inkColor} · Nhấn {activeTheme.accentColor}
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {WHITEBOARD_THEME_PRESETS.map((preset) => {
                const isSelected = activeTheme.id === preset.id;
                return (
                  <button
                    key={preset.id}
                    type="button"
                    onClick={() => applyWhiteboardTheme(preset)}
                    title={preset.tagline}
                    className={`inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-md border transition-colors cursor-pointer ${
                      isSelected
                        ? 'bg-[#1D2536] border-[#C8A252] text-[#F1F5F9]'
                        : 'bg-[#0B0F17] border-[#243045] text-[#CBD5E1] hover:border-[#475569]'
                    }`}
                  >
                    <span
                      className="w-4 h-4 rounded-sm border border-white/20 shrink-0 relative overflow-hidden"
                      style={{ backgroundColor: preset.bgColor }}
                    >
                      <span
                        className="absolute bottom-0 right-0 w-2 h-2"
                        style={{ backgroundColor: preset.accentColor }}
                      />
                    </span>
                    <span>{preset.label}</span>
                  </button>
                );
              })}

              {/* Custom Hex Color Picker */}
              <label
                className={`inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-md border transition-colors cursor-pointer ${
                  activeTheme.id === 'custom'
                    ? 'bg-[#1D2536] border-[#C8A252] text-[#F1F5F9]'
                    : 'bg-[#0B0F17] border-[#243045] text-[#CBD5E1] hover:border-[#475569]'
                }`}
              >
                <input
                  type="color"
                  aria-label="Chọn màu nền video tùy chỉnh"
                  value={activeTheme.bgColor}
                  onChange={(e) =>
                    applyWhiteboardTheme(buildCustomWhiteboardTheme(e.target.value))
                  }
                  className="w-4 h-4 p-0 border-0 bg-transparent cursor-pointer"
                />
                <span>Tự chọn màu nền</span>
              </label>
            </div>
          </div>
        )}

        {visualMode === 'pen_sketch' && (
          <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-[#1E2738]">
            <span className="text-xs font-medium text-[#CBD5E1]">Nền giấy vẽ (chế độ Bút vẽ nét):</span>
            <div className="inline-flex gap-1 p-1 bg-[#0B0F17] border border-[#1E2738] rounded-md">
              <button
                type="button"
                onClick={() => setPaperTheme('classic_parchment')}
                className={`px-3 py-1.5 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                  paperTheme === 'classic_parchment'
                    ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                    : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                }`}
              >
                Giấy sáng · Mực đen
              </button>
              <button
                type="button"
                onClick={() => setPaperTheme('dark_slate')}
                className={`px-3 py-1.5 text-xs font-medium rounded transition-colors whitespace-nowrap cursor-pointer ${
                  paperTheme === 'dark_slate'
                    ? 'bg-[#C8A252] text-[#0B0F17] font-semibold'
                    : 'text-[#94A3B8] hover:text-[#E2E8F0]'
                }`}
              >
                Than chì · Ngòi vàng
              </button>
            </div>
          </div>
        )}

        {/* Action Bar */}
        <div className="flex flex-wrap items-center justify-between gap-4 pt-3 border-t border-[#1E2738]">
          <div className="text-xs text-[#8B9BB4]">
            Giọng: <span className="text-[#CBD5E1]">{selectedPersonaObj.label}</span> · Ngôn ngữ:{' '}
            <span className="font-mono text-[#CBD5E1]">{config.language}</span> · Tỷ lệ:{' '}
            <span className="font-mono text-[#CBD5E1]">{config.aspectRatio}</span>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={handleGenerateScriptImagesAndVoice}
              disabled={generating || renderingVideo}
              className="inline-flex items-center gap-2 px-4 py-2.5 text-xs font-semibold text-[#0B0F17] bg-[#C8A252] hover:bg-[#D7B366] disabled:opacity-60 rounded-md transition-colors whitespace-nowrap cursor-pointer"
            >
              {generating ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Sparkles className="w-4 h-4" />
              )}
              {generating
                ? 'Đang tạo kịch bản, chuỗi ảnh & giọng...'
                : durationMode === 'full_5min'
                  ? 'Tạo Video 5 phút (~72–96 ảnh + Giọng)'
                  : 'Test nhanh 45s (~18–24 ảnh + Giọng)'}
            </button>

            <button
              type="button"
              onClick={handleRenderVideoWithVoice}
              disabled={!allReadyToRender || renderingVideo || generating}
              className="inline-flex items-center gap-2 px-4 py-2.5 text-xs font-semibold text-[#F1F5F9] bg-[#192437] border border-[#2E405E] hover:border-[#C8A252] disabled:opacity-40 rounded-md transition-colors whitespace-nowrap cursor-pointer"
            >
              {renderingVideo ? (
                <Loader2 className="w-4 h-4 animate-spin text-[#C8A252]" />
              ) : (
                <Film className="w-4 h-4 text-[#C8A252]" />
              )}
              {renderingVideo
                ? convertingMp4
                  ? `Đang đóng gói MP4 ${playbackSpeed}x...`
                  : `Đang dựng video (${renderProgress}%)...`
                : `Dựng Video MP4 (${playbackSpeed}x)`}
            </button>
          </div>
        </div>

        {statusMessage && (
          <p className="text-xs font-mono text-[#C8A252]">{statusMessage}</p>
        )}
        {errorMessage && (
          <div className="p-3.5 text-xs text-[#FCA5A5] bg-[#2B1418] border border-[#7F1D1D] rounded-md">
            {errorMessage}
          </div>
        )}
      </div>

      {/* Rendered Video Output + Single Persistent Live Canvas (không bao giờ bị unmount giữa chừng) */}
      <section
        className={`bg-[#111722] border border-[#1E2738] rounded-lg p-6 space-y-4 ${
          renderingVideo || renderedVideoUrl ? '' : 'hidden'
        }`}
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[#1E2738]">
          <div>
            <h2 className="text-base font-semibold text-[#F1F5F9]">
              {renderedVideoUrl
                ? `Video hoàn chỉnh (${renderedVideoExt.toUpperCase()} · ${playbackSpeed}x): ${videoTitle}`
                : convertingMp4
                  ? `Đang đóng gói MP4 chuẩn & tăng tốc ${playbackSpeed}x (giữ nguyên cao độ giọng)...`
                  : `Đang dựng video Motion Graphics 30fps & đồng bộ giọng đọc (${renderProgress}%)...`}
            </h2>
            <p className="text-xs font-mono tabular-nums text-[#8B9BB4] mt-0.5">
              Thời lượng ở {playbackSpeed}x: ~{formatDurationMmSs(totalVoiceDuration / playbackSpeed)} ·{' '}
              {scenes.length} cảnh · {totalWordCount} từ · {config.aspectRatio} ·{' '}
              {renderedVideoExt.toUpperCase()}
            </p>
          </div>
          {renderedVideoUrl && (
            <a
              href={renderedVideoUrl}
              download={`${driveFolderInfo.nextNumber}_${slugifyFilename(videoTitle || topic)}.${renderedVideoExt}`}
              className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-[#0B0F17] bg-[#C8A252] hover:bg-[#D7B366] rounded-md transition-colors whitespace-nowrap shrink-0"
            >
              <Download className="w-4 h-4" />
              Tải Video ({driveFolderInfo.nextNumber}_video.{renderedVideoExt})
            </a>
          )}
        </div>

        <div className="flex justify-center">
          {renderedVideoUrl && (
            <video
              src={renderedVideoUrl}
              controls
              playsInline
              style={{ backgroundColor: activeTheme.bgColor }}
              className={`rounded-md border border-[#243045] ${
                config.aspectRatio === '9:16'
                  ? 'max-h-[540px] aspect-[9/16]'
                  : 'w-full max-w-3xl aspect-video'
              }`}
            />
          )}
          <canvas
            ref={canvasRef}
            style={{ backgroundColor: activeTheme.bgColor }}
            className={`rounded-md border border-[#243045] ${
              renderedVideoUrl || !renderingVideo ? 'hidden' : ''
            } ${
              config.aspectRatio === '9:16'
                ? 'max-h-[520px] aspect-[9/16]'
                : 'w-full max-w-3xl aspect-video'
            }`}
          />
        </div>
      </section>

      {/* YouTube Thumbnail (1280x720) & Google Drive Numbered Topic Folder Card */}
      {(thumbnailData || videoTitle) && (
        <section className="bg-[#111722] border border-[#1E2738] rounded-lg p-6 space-y-5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-[#1E2738]">
            <div>
              <h2 className="text-base font-semibold text-[#F1F5F9] inline-flex items-center gap-2">
                <ImageIcon className="w-4 h-4 text-[#C8A252]" />
                Thumbnail YouTube (1280×720) &amp; Thư mục Google Drive
              </h2>
              <p className="text-xs text-[#8B9BB4] mt-0.5">
                Tự động đồng bộ màu nền kênh ({activeTheme.bgColor}) và lưu cùng video vào thư mục đánh số thứ tự trên Google Drive.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={handleRegenerateThumbnail}
                disabled={Boolean(thumbnailData?.regenerating) || generating}
                className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-[#CBD5E1] bg-[#162032] border border-[#26334B] hover:border-[#C8A252] disabled:opacity-40 rounded-md transition-colors whitespace-nowrap cursor-pointer"
              >
                <RefreshCw
                  className={`w-3.5 h-3.5 ${thumbnailData?.regenerating ? 'animate-spin' : ''}`}
                />
                Vẽ lại Thumbnail
              </button>
              <button
                type="button"
                onClick={handleDownloadThumbnailPng}
                disabled={!thumbnailData?.imageUrl || Boolean(thumbnailData?.regenerating)}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold text-[#0B0F17] bg-[#C8A252] hover:bg-[#D7B366] disabled:opacity-40 rounded-md transition-colors whitespace-nowrap cursor-pointer"
              >
                <Download className="w-3.5 h-3.5" />
                Tải Thumbnail (.png 1280×720)
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
            {/* Thumbnail 16:9 Preview */}
            <div className="lg:col-span-7">
              <div
                style={{ backgroundColor: activeTheme.bgColor }}
                className="aspect-video w-full rounded-md border border-[#243045] overflow-hidden relative"
              >
                {thumbnailData?.imageUrl ? (
                  <img
                    src={thumbnailData.imageUrl}
                    alt={`Thumbnail YouTube cho ${videoTitle}`}
                    referrerPolicy="no-referrer"
                    className="w-full h-full object-contain"
                  />
                ) : (
                  <div
                    style={{ color: activeTheme.inkColor }}
                    className="w-full h-full flex flex-col items-center justify-center gap-2"
                  >
                    <Loader2 className="w-5 h-5 animate-spin" />
                    <span className="text-xs font-medium">
                      Đang thiết kế Thumbnail YouTube 1280×720...
                    </span>
                  </div>
                )}

                {thumbnailData?.regenerating && thumbnailData.imageUrl && (
                  <div
                    style={{
                      backgroundColor: activeTheme.isDark
                        ? 'rgba(15, 23, 42, 0.78)'
                        : 'rgba(238, 242, 247, 0.82)',
                      color: activeTheme.inkColor,
                    }}
                    className="absolute inset-0 flex items-center justify-center gap-2 text-xs font-medium"
                  >
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Đang vẽ lại Thumbnail mới...</span>
                  </div>
                )}
              </div>
            </div>

            {/* Google Drive Auto-Numbered Topic Folder Structure */}
            <div className="lg:col-span-5 bg-[#0B0F17] border border-[#1E2738] rounded-md p-4 space-y-3">
              <div className="flex items-center justify-between gap-2 pb-2.5 border-b border-[#1E2738]">
                <span className="text-xs font-semibold text-[#F1F5F9] inline-flex items-center gap-1.5">
                  <FolderOpen className="w-4 h-4 text-[#C8A252]" />
                  Cấu trúc xuất lên Google Drive
                </span>
                <span className="text-[11px] font-mono text-[#C8A252]">
                  {driveFolderInfo.connected
                    ? `Drive đã có #${driveFolderInfo.maxNumber} → Tiếp theo #${driveFolderInfo.nextNumber}`
                    : `Bắt đầu từ số #${driveFolderInfo.nextNumber}`}
                </span>
              </div>

              <div className="font-mono text-xs space-y-2 text-[#CBD5E1]">
                <div className="p-2.5 rounded bg-[#111722] border border-[#243045] text-[#F1F5F9] break-words">
                  📁 {formatNumberedDriveFolder(driveFolderInfo.nextNumber, videoTitle || topic)}/
                </div>
                <div className="pl-4 space-y-1.5 text-[11px] text-[#94A3B8]">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate">
                      ├── 🎬 {driveFolderInfo.nextNumber}_{slugifyFilename(videoTitle || topic)}.mp4
                    </span>
                    <span className="text-[#64748B] shrink-0">H.264 · {playbackSpeed}x</span>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate">
                      └── 🖼️ {driveFolderInfo.nextNumber}_thumbnail.png
                    </span>
                    <span className="text-[#64748B] shrink-0">1280×720</span>
                  </div>
                </div>
              </div>

              <p className="text-[11px] leading-relaxed text-[#8B9BB4] pt-2 border-t border-[#1E2738]">
                Khi chạy GitHub Actions hàng ngày, hệ thống tự động quét toàn bộ thư mục con trong{' '}
                <code className="text-[#CBD5E1]">GDRIVE_FOLDER_ID</code>, lấy số thứ tự lớn nhất hiện có
                cộng thêm 1 (bắt đầu từ <code className="text-[#CBD5E1]">1</code> nếu chưa có), cấp số liên
                tiếp không trùng cho cả 5 video song song và tải cả Video + Thumbnail vào đúng thư mục chủ đề.
              </p>

              {driveFolderInfo.sampleFolders.length > 0 && (
                <div className="pt-2 border-t border-[#1E2738] space-y-1">
                  <span className="text-[11px] text-[#7C8DA6]">Thư mục gần nhất trên Drive:</span>
                  <div className="space-y-0.5 font-mono text-[11px] text-[#94A3B8]">
                    {driveFolderInfo.sampleFolders.slice(0, 3).map((folderName) => (
                      <div key={folderName} className="truncate">
                        • {folderName}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      {/* Generated Scenes Breakdown */}
      {scenes.length > 0 && (
        <section className="space-y-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-lg font-semibold text-[#F1F5F9]">
              Kịch bản &amp; Chuỗi hình minh họa theo cụm ý — {videoTitle}
            </h2>
            <span className="text-xs font-mono tabular-nums text-[#8B9BB4]">
              {totalImageCount} ảnh ({scenes.length} đoạn thoại · ~3–4s/ảnh) · {totalWordCount} từ · ~
              {formatDurationMmSs(totalVoiceDuration / playbackSpeed)} ({playbackSpeed}x) · Script:{' '}
              {scriptModelUsed}
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {scenes.map((scene, idx) => {
              const beats =
                scene.visual_beats && scene.visual_beats.length > 0 ? scene.visual_beats : null;
              const selectedBeatIdx = beats
                ? Math.min(activeBeatByScene[scene.scene_id] ?? 0, beats.length - 1)
                : 0;
              const activeBeat = beats ? beats[selectedBeatIdx] : null;
              const previewUrl = activeBeat?.imageUrl || scene.imageUrl;
              const isBusy = Boolean(activeBeat?.regenerating || scene.regeneratingImage);

              return (
                <div
                  key={scene.scene_id}
                  className="bg-[#111722] border border-[#1E2738] rounded-lg overflow-hidden flex flex-col"
                >
                  {/* Clean preview frame matching the user's selected background color */}
                  <div
                    style={{ backgroundColor: activeTheme.bgColor }}
                    className="aspect-video relative overflow-hidden border-b border-[#1E2738]"
                  >
                    {previewUrl ? (
                      <img
                        src={previewUrl}
                        alt={`Minh họa cảnh ${scene.scene_id}: ${activeBeat?.short_label || scene.scene_label || scene.chapter_header}`}
                        referrerPolicy="no-referrer"
                        className="w-full h-full object-contain"
                      />
                    ) : (
                      <div
                        style={{ color: activeTheme.inkColor }}
                        className="w-full h-full flex flex-col items-center justify-center gap-2"
                      >
                        <Loader2 className="w-5 h-5 animate-spin" />
                        <span className="text-xs font-medium">
                          Đang vẽ {beats ? `${beats.length} ảnh` : 'minh họa'} cho cảnh {scene.scene_id}...
                        </span>
                      </div>
                    )}

                    {isBusy && previewUrl && (
                      <div
                        style={{
                          backgroundColor: activeTheme.isDark
                            ? 'rgba(15, 23, 42, 0.78)'
                            : 'rgba(238, 242, 247, 0.82)',
                          color: activeTheme.inkColor,
                        }}
                        className="absolute inset-0 flex items-center justify-center gap-2 text-xs font-medium"
                      >
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Đang vẽ lại ảnh mới...</span>
                      </div>
                    )}
                  </div>

                  {/* Multi-Shot Filmstrip Bar (3–4 ảnh con cho từng cụm ý trong cảnh) */}
                  {beats && beats.length > 1 && (
                    <div className="px-3 py-2.5 bg-[#0A0F1A] border-b border-[#1A2232] space-y-2">
                      <div className="grid grid-cols-4 gap-2">
                        {beats.map((b, bIdx) => {
                          const isSelected = bIdx === selectedBeatIdx;
                          return (
                            <button
                              key={b.beat_id ?? bIdx}
                              type="button"
                              onClick={() =>
                                setActiveBeatByScene((prev) => ({ ...prev, [scene.scene_id]: bIdx }))
                              }
                              title={`Ảnh ${bIdx + 1}: "${b.phrase}"`}
                              className={`text-left rounded overflow-hidden border transition-colors cursor-pointer ${
                                isSelected
                                  ? 'border-[#C8A252] ring-1 ring-[#C8A252]/60'
                                  : 'border-[#243045] hover:border-[#475569]'
                              }`}
                            >
                              <div
                                style={{ backgroundColor: activeTheme.bgColor }}
                                className="aspect-video w-full overflow-hidden flex items-center justify-center"
                              >
                                {b.imageUrl ? (
                                  <img
                                    src={b.imageUrl}
                                    alt={b.short_label}
                                    referrerPolicy="no-referrer"
                                    className="w-full h-full object-contain"
                                  />
                                ) : (
                                  <Loader2
                                    style={{ color: activeTheme.inkColor }}
                                    className="w-3.5 h-3.5 animate-spin"
                                  />
                                )}
                              </div>
                              <div className="px-1.5 py-1 bg-[#111722] text-[10px] font-mono text-[#CBD5E1] truncate">
                                #{bIdx + 1} {b.short_label}
                              </div>
                            </button>
                          );
                        })}
                      </div>
                      {activeBeat && (
                        <p className="text-[11px] text-[#94A3B8] truncate">
                          <span className="text-[#C8A252] font-mono">
                            Ảnh {selectedBeatIdx + 1}/{beats.length}:
                          </span>{' '}
                          “{activeBeat.phrase}”
                        </p>
                      )}
                    </div>
                  )}

                  {/* Scene Metadata Strip */}
                  <div className="px-4 py-2 bg-[#0D131F] border-b border-[#1A2232] flex items-center justify-between gap-2 text-[11px] font-mono">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-[#C8A252] shrink-0">
                        Cảnh {String(scene.scene_id).padStart(2, '0')}
                      </span>
                      <span className="text-[#475569]">·</span>
                      <span className="text-[#CBD5E1] truncate">
                        {scene.chapter_header || scene.scene_label}
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() =>
                        handleRegenerateSingleImage(idx, beats ? selectedBeatIdx : undefined)
                      }
                      disabled={isBusy || generating || renderingVideo}
                      className="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] text-[#CBD5E1] hover:text-[#F1F5F9] bg-[#162032] border border-[#26334B] hover:border-[#C8A252] disabled:opacity-40 rounded transition-colors shrink-0 cursor-pointer"
                    >
                      <RefreshCw className={`w-3 h-3 ${isBusy ? 'animate-spin' : ''}`} />
                      {beats && beats.length > 1 ? `Vẽ lại ảnh #${selectedBeatIdx + 1}` : 'Vẽ lại ảnh'}
                    </button>
                  </div>

                  {/* Scene Narration & Audio */}
                  <div className="p-4 flex-1 flex flex-col justify-between space-y-3">
                    <div className="space-y-2">
                      <p className="text-sm leading-relaxed text-[#E2E8F0]">{scene.narration}</p>
                      <div className="flex flex-wrap items-center gap-2 text-[11px] font-mono text-[#7C8DA6]">
                        <span>{beats ? `${beats.length} ảnh nối tiếp` : scene.layout_type || 'stickman_explain'}</span>
                        <span>·</span>
                        <span>{activeBeat?.imageModelUsed || scene.imageModelUsed || 'AI Multi-Shot'}</span>
                      </div>
                    </div>

                    <div className="pt-3 border-t border-[#1A2232] space-y-2">
                      {scene.audioUrl ? (
                        <>
                          <audio controls src={scene.audioUrl} className="w-full h-9" />
                          <div className="flex items-center justify-between text-[11px] font-mono tabular-nums text-[#7C8DA6]">
                            <span className="inline-flex items-center gap-1">
                              <Volume2 className="w-3 h-3 text-[#C8A252]" />
                              {scene.ttsModelUsed || preferredTtsModel}
                            </span>
                            <span>{(scene.audioDuration ?? 0).toFixed(2)}s · WAV 24kHz</span>
                          </div>
                        </>
                      ) : (
                        <div className="flex items-center gap-2 text-xs text-[#8B9BB4] py-1">
                          <Play className="w-3.5 h-3.5 text-[#64748B]" />
                          <span>Đang chờ tổng hợp giọng đọc cho phân cảnh này...</span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
