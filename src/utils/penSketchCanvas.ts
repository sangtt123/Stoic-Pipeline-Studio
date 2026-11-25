import type { PenSketchPaperTheme } from '../types/pipeline';

export interface StrokeCell {
  cx: number;
  cy: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface PenSketchAsset {
  width: number;
  height: number;
  theme: PenSketchPaperTheme;
  targetCanvas: HTMLCanvasElement;
  paperCanvas: HTMLCanvasElement;
  lineArtCanvas: HTMLCanvasElement;
  strokeCells: StrokeCell[];
}

function drawCover(
  ctx: CanvasRenderingContext2D,
  img: HTMLImageElement,
  width: number,
  height: number
) {
  const scale = Math.max(width / img.width, height / img.height);
  const drawW = img.width * scale;
  const drawH = img.height * scale;
  const dx = (width - drawW) / 2;
  const dy = (height - drawH) / 2;
  ctx.drawImage(img, dx, dy, drawW, drawH);
}

/**
 * Chuẩn bị dữ liệu vẽ nét bút mực (Edge-traced line art + lộ trình nét vẽ theo vùng mực đậm)
 * từ ảnh 2D đầu vào. Chạy 1 lần duy nhất cho mỗi phân cảnh trước khi render.
 */
export function preparePenSketchAsset(
  img: HTMLImageElement,
  width: number,
  height: number,
  theme: PenSketchPaperTheme
): PenSketchAsset {
  // 1. Canvas ảnh gốc đã cắt vừa khung hình
  const targetCanvas = document.createElement('canvas');
  targetCanvas.width = width;
  targetCanvas.height = height;
  const tCtx = targetCanvas.getContext('2d')!;
  drawCover(tCtx, img, width, height);

  // 2. Canvas nền giấy vẽ có vân hạt tinh tế
  const paperCanvas = document.createElement('canvas');
  paperCanvas.width = width;
  paperCanvas.height = height;
  const pCtx = paperCanvas.getContext('2d')!;
  const paperImgData = pCtx.createImageData(width, height);
  const pData = paperImgData.data;

  const baseR = theme === 'classic_parchment' ? 236 : 16;
  const baseG = theme === 'classic_parchment' ? 228 : 21;
  const baseB = theme === 'classic_parchment' ? 212 : 30;

  let seed = 1337;
  for (let i = 0; i < pData.length; i += 4) {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    const grain = ((seed >>> 24) & 15) - 7;
    pData[i] = Math.max(0, Math.min(255, baseR + grain));
    pData[i + 1] = Math.max(0, Math.min(255, baseG + grain));
    pData[i + 2] = Math.max(0, Math.min(255, baseB + grain));
    pData[i + 3] = 255;
  }
  pCtx.putImageData(paperImgData, 0, 0);

  // 3. Tách đường nét mực (Sobel Edge Detection) lên canvas line-art
  const srcData = tCtx.getImageData(0, 0, width, height).data;
  const gray = new Float32Array(width * height);
  for (let i = 0, p = 0; i < gray.length; i++, p += 4) {
    gray[i] = srcData[p] * 0.299 + srcData[p + 1] * 0.587 + srcData[p + 2] * 0.114;
  }

  const lineArtCanvas = document.createElement('canvas');
  lineArtCanvas.width = width;
  lineArtCanvas.height = height;
  const lCtx = lineArtCanvas.getContext('2d')!;
  const lineImg = lCtx.createImageData(width, height);
  const lData = lineImg.data;

  // Màu nét vẽ: Vàng đồng sáng trên nền than chì, hoặc mực đen trên giấy da cừu
  const inkR = theme === 'classic_parchment' ? 28 : 218;
  const inkG = theme === 'classic_parchment' ? 26 : 194;
  const inkB = theme === 'classic_parchment' ? 24 : 142;

  const edgeStrength = new Float32Array(width * height);
  for (let y = 1; y < height - 1; y++) {
    const row = y * width;
    for (let x = 1; x < width - 1; x++) {
      const idx = row + x;
      const gx =
        -gray[idx - width - 1] +
        gray[idx - width + 1] -
        2 * gray[idx - 1] +
        2 * gray[idx + 1] -
        gray[idx + width - 1] +
        gray[idx + width + 1];
      const gy =
        -gray[idx - width - 1] -
        2 * gray[idx - width] -
        gray[idx - width + 1] +
        gray[idx + width - 1] +
        2 * gray[idx + width] +
        gray[idx + width + 1];

      const mag = Math.min(255, Math.hypot(gx, gy) * 0.55);
      edgeStrength[idx] = mag;

      const p = idx * 4;
      if (mag > 26) {
        const strength = Math.min(1, (mag - 22) / 110);
        lData[p] = inkR;
        lData[p + 1] = inkG;
        lData[p + 2] = inkB;
        lData[p + 3] = Math.round(strength * 245);
      } else {
        lData[p + 3] = 0;
      }
    }
  }
  lCtx.putImageData(lineImg, 0, 0);

  // 4. Gom các vùng có nét mực thành lộ trình vẽ tự nhiên (vẽ chủ thể trung tâm trước, lan dần ra xung quanh)
  const cols = width >= height ? 22 : 14;
  const rows = width >= height ? 13 : 22;
  const cellW = Math.ceil(width / cols);
  const cellH = Math.ceil(height / rows);

  const rawCells: { cell: StrokeCell; density: number; priority: number }[] = [];
  const focusX = width * 0.5;
  const focusY = height * 0.45;

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const x0 = c * cellW;
      const y0 = r * cellH;
      const w = Math.min(cellW, width - x0);
      const h = Math.min(cellH, height - y0);

      let sumEdge = 0;
      let samples = 0;
      for (let yy = y0; yy < y0 + h; yy += 3) {
        const rOff = yy * width;
        for (let xx = x0; xx < x0 + w; xx += 3) {
          sumEdge += edgeStrength[rOff + xx];
          samples++;
        }
      }

      const density = samples > 0 ? sumEdge / samples : 0;
      if (density < 7) continue;

      const cx = x0 + w / 2;
      const cy = y0 + h / 2;
      const distCenter = Math.hypot(cx - focusX, cy - focusY) / Math.max(width, height);

      // Lộ trình vẽ tự nhiên kiểu họa sĩ: đi từ chủ thể chính, theo các dải ngang chéo mềm mại
      const bandOrder = Math.floor(r / 2) * 0.16 + ((r % 2 === 0 ? c : cols - c) / cols) * 0.14;
      const priority = distCenter * 0.58 + bandOrder - Math.min(density / 220, 0.25);

      rawCells.push({
        cell: { cx, cy, x: x0, y: y0, w, h },
        density,
        priority,
      });
    }
  }

  rawCells.sort((a, b) => a.priority - b.priority);

  return {
    width,
    height,
    theme,
    targetCanvas,
    paperCanvas,
    lineArtCanvas,
    strokeCells: rawCells.map((item) => item.cell),
  };
}

/**
 * Vẽ cây bút máy cổ điển (ngòi vàng + thân sơn mài đen + bóng mềm) với đầu ngòi đặt tại đúng (tipX, tipY).
 */
export function drawFountainPen(
  ctx: CanvasRenderingContext2D,
  tipX: number,
  tipY: number,
  scale = 1,
  tiltRad = -0.68
) {
  ctx.save();
  ctx.translate(tipX, tipY);
  ctx.rotate(tiltRad);
  ctx.scale(scale, scale);

  // Bóng đổ mềm trên mặt giấy
  ctx.save();
  ctx.translate(7, 10);
  ctx.fillStyle = 'rgba(0, 0, 0, 0.32)';
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(36, -12);
  ctx.lineTo(220, -14);
  ctx.lineTo(226, 4);
  ctx.lineTo(36, 10);
  ctx.closePath();
  ctx.fill();
  ctx.restore();

  // Đầu ngòi bút vàng đồng sắc nhọn
  const nibGrad = ctx.createLinearGradient(0, -10, 44, 10);
  nibGrad.addColorStop(0, '#F5DFA4');
  nibGrad.addColorStop(0.55, '#C8A252');
  nibGrad.addColorStop(1, '#7D5E23');
  ctx.fillStyle = nibGrad;
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(38, -11);
  ctx.lineTo(48, -7);
  ctx.lineTo(48, 7);
  ctx.lineTo(38, 11);
  ctx.closePath();
  ctx.fill();

  ctx.strokeStyle = '#3C2C10';
  ctx.lineWidth = 1.2;
  ctx.stroke();

  // Khe mực & lỗ thở đặc trưng trên ngòi bút máy
  ctx.strokeStyle = '#1B140A';
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  ctx.moveTo(1, 0);
  ctx.lineTo(28, 0);
  ctx.stroke();
  ctx.fillStyle = '#1B140A';
  ctx.beginPath();
  ctx.arc(28, 0, 2.2, 0, Math.PI * 2);
  ctx.fill();

  // Cổ bút cầm tay (section)
  ctx.fillStyle = '#151B26';
  ctx.beginPath();
  ctx.moveTo(46, -8.5);
  ctx.lineTo(74, -10.5);
  ctx.lineTo(74, 10.5);
  ctx.lineTo(46, 8.5);
  ctx.closePath();
  ctx.fill();

  // Khoen vàng trang trí
  ctx.fillStyle = '#D4B062';
  ctx.fillRect(72, -11, 8, 22);
  ctx.fillStyle = '#8F6F2E';
  ctx.fillRect(78, -11, 2, 22);

  // Thân bút sơn mài obsidian dài
  const bodyGrad = ctx.createLinearGradient(80, -12, 80, 12);
  bodyGrad.addColorStop(0, '#2A3548');
  bodyGrad.addColorStop(0.35, '#141A24');
  bodyGrad.addColorStop(1, '#090C12');
  ctx.fillStyle = bodyGrad;
  ctx.beginPath();
  ctx.moveTo(80, -11.5);
  ctx.lineTo(240, -10);
  ctx.lineTo(246, -6);
  ctx.lineTo(246, 6);
  ctx.lineTo(240, 10);
  ctx.lineTo(80, 11.5);
  ctx.closePath();
  ctx.fill();

  ctx.strokeStyle = 'rgba(200, 162, 82, 0.45)';
  ctx.lineWidth = 1;
  ctx.stroke();

  // Viền sáng dọc thân bút
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.16)';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(84, -6.5);
  ctx.lineTo(236, -5.5);
  ctx.stroke();

  ctx.restore();
}

/**
 * Vẽ 1 frame hoàn chỉnh tại thời điểm `progress` (0.0 -> 1.0):
 * - 0.00 -> 0.65: Bút chuyển động vẽ dần từng nét mực lên giấy vẽ.
 * - 0.65 -> 0.85: Bút lướt ra khỏi khung hình, lớp đổ bóng màu hiện dần hoàn chỉnh.
 * - 0.85 -> 1.00: Khung hình 2D hoàn chỉnh sắc nét.
 */
export function renderPenSketchFrame(
  ctx: CanvasRenderingContext2D,
  asset: PenSketchAsset,
  progress: number
) {
  const { width, height, paperCanvas, lineArtCanvas, targetCanvas, strokeCells } = asset;
  const p = Math.max(0, Math.min(1, progress));
  const drawPhaseEnd = 0.66;
  const washPhaseEnd = 0.86;
  const penScale = Math.max(0.55, Math.min(1.05, width / 1080));

  // Vẽ nền giấy trước
  ctx.drawImage(paperCanvas, 0, 0);

  if (p < drawPhaseEnd) {
    const drawP = p / drawPhaseEnd;
    const totalCells = Math.max(1, strokeCells.length);
    const exactFloat = drawP * totalCells;
    const fullCount = Math.floor(exactFloat);
    const partial = exactFloat - fullCount;

    // Hiện dần các vùng nét mực đã vẽ xong
    for (let i = 0; i < fullCount; i++) {
      const c = strokeCells[i];
      ctx.drawImage(
        lineArtCanvas,
        c.x,
        c.y,
        c.w,
        c.h,
        c.x,
        c.y,
        c.w,
        c.h
      );
    }

    // Vùng đang được bút vẽ trực tiếp + tính tọa độ đầu ngòi bút sống động
    let tipX = width * 0.5;
    let tipY = height * 0.5;

    if (fullCount < totalCells) {
      const curr = strokeCells[fullCount];
      const revealW = Math.max(2, curr.w * partial);
      ctx.drawImage(
        lineArtCanvas,
        curr.x,
        curr.y,
        revealW,
        curr.h,
        curr.x,
        curr.y,
        revealW,
        curr.h
      );

      // Chuyển động đưa nét zig-zag tự nhiên của cổ tay khi phác họa
      const strokeOsc = Math.sin(p * 110) * (curr.h * 0.32);
      const jitterX = Math.cos(p * 85) * 4;
      tipX = curr.x + revealW + jitterX;
      tipY = curr.cy + strokeOsc;
    } else if (strokeCells.length > 0) {
      const last = strokeCells[strokeCells.length - 1];
      tipX = last.cx;
      tipY = last.cy;
    }

    // Vẽ đốm sáng mực tinh tế ngay tại mũi ngòi bút
    ctx.save();
    ctx.fillStyle =
      asset.theme === 'classic_parchment'
        ? 'rgba(30, 26, 22, 0.35)'
        : 'rgba(214, 179, 104, 0.45)';
    ctx.beginPath();
    ctx.arc(tipX, tipY, 3.2 * penScale, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    const tilt = -0.68 + Math.sin(p * 65) * 0.045;
    drawFountainPen(ctx, tipX, tipY, penScale, tilt);
    return;
  }

  if (p < washPhaseEnd) {
    // Giai đoạn 2: Đổ bóng & màu hoàn chỉnh dần lên trên bản phác họa + bút lướt rời khung
    const washP = (p - drawPhaseEnd) / (washPhaseEnd - drawPhaseEnd);
    ctx.drawImage(lineArtCanvas, 0, 0);

    ctx.save();
    ctx.globalAlpha = washP;
    ctx.drawImage(targetCanvas, 0, 0);
    ctx.restore();

    const last = strokeCells[strokeCells.length - 1] ?? {
      cx: width * 0.65,
      cy: height * 0.5,
    };
    const easeOut = 1 - Math.pow(1 - washP, 2);
    const exitX = last.cx + (width - last.cx + 160) * easeOut;
    const exitY = last.cy - 90 * easeOut;
    drawFountainPen(ctx, exitX, exitY, penScale, -0.58 - washP * 0.15);
    return;
  }

  // Giai đoạn 3: Hình hoàn chỉnh sắc nét với chuyển động zoom cực nhẹ
  const holdP = (p - washPhaseEnd) / (1 - washPhaseEnd);
  const microZoom = 1 + 0.025 * holdP;
  const zw = width * microZoom;
  const zh = height * microZoom;
  ctx.drawImage(targetCanvas, (width - zw) / 2, (height - zh) / 2, zw, zh);
}
