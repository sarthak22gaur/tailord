// Zero-dependency PNG generator for Chrome/Firefox extension icons.
// Writes icons/icon{16,48,128}.png as a simple Tailord monogram.
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import zlib from 'node:zlib';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = join(__dirname, '..', 'icons');

const SAMPLES = 4;
const BG_TOP = [30, 64, 175, 255];
const BG_BOTTOM = [15, 23, 42, 255];
const BG_GLOW = [20, 184, 166, 255];
const WHITE = [255, 255, 255, 255];
const WHITE_SOFT = [226, 232, 240, 255];
const TEAL = [20, 184, 166, 255];
const SHADOW = [2, 6, 23, 72];

function crc32(buf) {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  let crc = 0xffffffff;
  for (const b of buf) crc = (table[(crc ^ b) & 0xff] ^ (crc >>> 8)) >>> 0;
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const typeBuf = Buffer.from(type, 'ascii');
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0);
  return Buffer.concat([len, typeBuf, data, crc]);
}

function mix(a, b, t) {
  return a.map((value, index) => Math.round(value + (b[index] - value) * t));
}

function roundedRectContains(x, y, left, top, right, bottom, radius) {
  const px = Math.max(left + radius, Math.min(x, right - radius));
  const py = Math.max(top + radius, Math.min(y, bottom - radius));
  const dx = x - px;
  const dy = y - py;
  return dx * dx + dy * dy <= radius * radius;
}

function circleContains(x, y, cx, cy, radius) {
  const dx = x - cx;
  const dy = y - cy;
  return dx * dx + dy * dy <= radius * radius;
}

function distanceToSegment(x, y, x1, y1, x2, y2) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((x - x1) * dx + (y - y1) * dy) / len2));
  const px = x1 + t * dx;
  const py = y1 + t * dy;
  return Math.hypot(x - px, y - py);
}

function drawSample(size, x, y) {
  const r = size * 0.22;
  if (!roundedRectContains(x, y, 0, 0, size, size, r)) return [0, 0, 0, 0];

  const vertical = y / size;
  const diagonal = (x + y) / (size * 2);
  let color = mix(BG_TOP, BG_BOTTOM, vertical * 0.86);

  const glow = Math.max(0, 1 - Math.hypot(x - size * 0.76, y - size * 0.24) / (size * 0.72));
  color = mix(color, BG_GLOW, glow * 0.22);
  color = mix(color, [59, 130, 246, 255], Math.max(0, 0.42 - diagonal) * 0.18);

  const shadowOffset = size * 0.025;
  const topBar = [size * 0.24 + shadowOffset, size * 0.28 + shadowOffset, size * 0.76 + shadowOffset, size * 0.41 + shadowOffset];
  const stem = [size * 0.43 + shadowOffset, size * 0.35 + shadowOffset, size * 0.57 + shadowOffset, size * 0.74 + shadowOffset];
  if (
    roundedRectContains(x, y, ...topBar, size * 0.025) ||
    roundedRectContains(x, y, ...stem, size * 0.025)
  ) {
    color = mix(color, SHADOW, SHADOW[3] / 255);
  }

  if (
    roundedRectContains(x, y, size * 0.24, size * 0.28, size * 0.76, size * 0.41, size * 0.025) ||
    roundedRectContains(x, y, size * 0.43, size * 0.35, size * 0.57, size * 0.74, size * 0.025)
  ) {
    color = WHITE;
  }

  if (size >= 32) {
    const cx = size * 0.72;
    const cy = size * 0.72;
    const outer = size * 0.18;
    const inner = size * 0.145;
    if (circleContains(x, y, cx, cy, outer)) color = WHITE_SOFT;
    if (circleContains(x, y, cx, cy, inner)) color = TEAL;
    const check =
      distanceToSegment(x, y, cx - size * 0.07, cy, cx - size * 0.025, cy + size * 0.045) <= size * 0.018 ||
      distanceToSegment(x, y, cx - size * 0.025, cy + size * 0.045, cx + size * 0.08, cy - size * 0.07) <= size * 0.018;
    if (check && circleContains(x, y, cx, cy, inner * 0.98)) color = WHITE;
  }

  return color;
}

function makePng(size) {
  const sig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8;  // 8-bit depth
  ihdr[9] = 6;  // color type: RGBA
  // ihdr[10..12] = 0 (compression / filter / interlace)

  const raw = Buffer.alloc(size * (1 + size * 4));
  for (let y = 0; y < size; y++) {
    const rowStart = y * (1 + size * 4);
    raw[rowStart] = 0; // filter type: none
    for (let x = 0; x < size; x++) {
      const acc = [0, 0, 0, 0];
      for (let sy = 0; sy < SAMPLES; sy++) {
        for (let sx = 0; sx < SAMPLES; sx++) {
          const sample = drawSample(
            size,
            x + (sx + 0.5) / SAMPLES,
            y + (sy + 0.5) / SAMPLES,
          );
          for (let i = 0; i < 4; i++) acc[i] += sample[i];
        }
      }
      const px = rowStart + 1 + x * 4;
      for (let i = 0; i < 4; i++) raw[px + i] = Math.round(acc[i] / (SAMPLES * SAMPLES));
    }
  }
  const idat = zlib.deflateSync(raw);
  return Buffer.concat([sig, chunk('IHDR', ihdr), chunk('IDAT', idat), chunk('IEND', Buffer.alloc(0))]);
}

for (const size of [16, 48, 128]) {
  const path = join(OUT_DIR, `icon${size}.png`);
  writeFileSync(path, makePng(size));
  console.log(`wrote ${path}`);
}
