// @ts-nocheck  (canvas pixel code ported 1:1 from the Caduceus for OM-3 Look Lab; typed loosely on purpose)
// Vendored from androidfanman/caduceus-om3 @ daa453b (Apache-2.0, see NOTICE), unchanged. Update by copying; our glue is in ./targets/om3.ts.
// NAMES.BIN v1 for Caduceus for OM-3 v0.17+: one picture per profile number, shown under the wheel on the Profiles
// page. 'OM3N' | total | crc32(12..) | u16 1 | u16 20 | u16 175 | u16 50 | 12 zero | 4 groups {u32 offset, u32 length}
// at 32 (COLOR k's five pictures, contiguous from 144, each group <= 16384 B) | 20 entries {u16 offset in group,
// u16 length} at 64 | group data. Picture = OM-3 OSD type-11 stream, 175 x 50, palette indices 0 clear, 7 dark edge,
// 9 faint rim, 10 white, 11 light edge, 12 grey. A number with no profile is labelled "Empty".
import { crc32 } from './format';

const NM_W = 175, NM_H = 50, NM_GROUP_MAX = 16384;
// The camera's own guide-label look (card/mkguides.py): its condensed sans fitted to the stock metrics (cap height
// 31 px, 'o' 15 px wide, baseline row 40), white fill with the camera's outline (1-px edge, light corners, 2-px dark
// line, faint rim). Font: a renamed ASCII subset of DejaVu Sans Condensed (Bitstream Vera licence: public/fonts/FONT-LICENSE.txt).
const NM_FONT = './fonts/om3label.woff2';
let nmFontReady = null;
const nmFont = () => nmFontReady || (nmFontReady = (async () => {
  const f = new FontFace('OM3 Label Condensed', 'url(' + NM_FONT + ')'); await f.load(); document.fonts.add(f);
})());
function nmRaster(txt, fs, sq) {          // grayscale (0..255) rows, cropped to the ink's columns, like mkguides.raster
  const S = 4, c = document.createElement('canvas'); c.width = fs * S * txt.length + 200; c.height = fs * S * 2;
  const x = c.getContext('2d', { willReadFrequently: true });
  x.font = (fs * S) + 'px "OM3 Label Condensed"'; x.textBaseline = 'top'; x.fillStyle = '#fff'; x.fillText(txt, 50, 20);
  const d = x.getImageData(0, 0, c.width, c.height).data; let x0 = c.width, x1 = -1;
  for (let yy = 0; yy < c.height; yy++) for (let xx = 0; xx < c.width; xx++) if (d[(yy * c.width + xx) * 4 + 3]) { if (xx < x0) x0 = xx; if (xx > x1) x1 = xx; }
  if (x1 < 0) return { w: 1, h: Math.round(c.height / S), a: new Uint8Array(Math.round(c.height / S)) };
  const W = Math.max(1, Math.round((x1 - x0 + 1) / S * sq)), H = Math.round(c.height / S);
  const o = document.createElement('canvas'); o.width = W; o.height = H; const ox = o.getContext('2d', { willReadFrequently: true });
  ox.imageSmoothingEnabled = true; ox.imageSmoothingQuality = 'high'; ox.drawImage(c, x0, 0, x1 - x0 + 1, c.height, 0, 0, W, H);
  const od = ox.getImageData(0, 0, W, H).data, a = new Uint8Array(W * H);
  for (let k = 0; k < W * H; k++) a[k] = od[k * 4 + 3];
  return { w: W, h: H, a };
}
const nmRows = (r, thr) => { const out = []; for (let yy = 0; yy < r.h; yy++) { for (let xx = 0; xx < r.w; xx++) if (r.a[yy * r.w + xx] > thr) { out.push(yy); break; } } return out; };
const nmCols = (r, thr) => { const out = []; for (let xx = 0; xx < r.w; xx++) for (let yy = 0; yy < r.h; yy++) if (r.a[yy * r.w + xx] > thr) { out.push(xx); break; } return out; };
let nmMetrics = null;
function nmFit() {                        // the stock size: 'H' fill 31 rows high, 'o' fill 15 px wide
  if (nmMetrics) return nmMetrics;
  let fs = 20, sq = 0.6;
  for (; fs < 60; fs++) { const r = nmRows(nmRaster('H', fs, 1), 128); if (r.length && r[r.length - 1] - r[0] + 1 >= 31) break; }
  for (let k = 60; k <= 110; k++) { sq = k / 100; const c = nmCols(nmRaster('o', fs, sq), 128); if (c.length && c[c.length - 1] - c[0] + 1 >= 15) break; }
  return (nmMetrics = { fs, sq });
}
/** A name picture (175 x 50 palette indices) in the camera's label style; the word centred, up to 167 px wide. */
export function nameIndices(text, shrink = 0) {
  let { fs, sq } = nmFit(); fs -= shrink; let r = nmRaster(text, fs, sq);
  while (r.w > 167 && sq > 0.6) { sq = Math.round((sq - 0.02) * 100) / 100; r = nmRaster(text, fs, sq); }
  while (r.w > 167 && fs > 16) { fs--; r = nmRaster(text, fs, sq); }
  const first = nmRows(nmRaster(text[0], fs, sq), 128), base = first.length ? first[first.length - 1] : 30;
  const ink = nmRows(r, 40), DESC = 6;
  let rows = []; for (let yy = 0; yy < r.h; yy++) rows.push(r.a.subarray(yy * r.w, (yy + 1) * r.w));
  if (ink.length && ink[ink.length - 1] - base > DESC) {      // squeeze a descender's tail into rows 41..46
    const tail = rows.slice(base + 1, ink[ink.length - 1] + 1), n = tail.length, sq2 = [];
    for (let k = 0; k < DESC; k++) {
      const lo = k * n / DESC, hi = (k + 1) * n / DESC, row = new Uint8Array(r.w);
      for (let xx = 0; xx < r.w; xx++) { let sum = 0, wsum = 0; for (let t = Math.floor(lo); t < Math.ceil(hi); t++) { const wgt = Math.min(hi, t + 1) - Math.max(lo, t); sum += tail[t][xx] * wgt; wsum += wgt; } row[xx] = Math.round(sum / wsum); }
      sq2.push(row);
    }
    rows = [...rows.slice(0, base + 1), ...sq2, ...rows.slice(ink[ink.length - 1] + 1).map(() => new Uint8Array(r.w))];
  }
  const lay = new Uint8Array(NM_W * NM_H), x0 = Math.floor((NM_W - r.w) / 2), shift = 40 - base;
  rows.forEach((row, yy) => {
    const y2 = yy + shift; if (y2 < 0 || y2 >= NM_H) return;
    for (let xx = 0; xx < r.w; xx++) { const v = row[xx], X = x0 + xx; if (X < 0 || X >= NM_W) continue; if (v > 128) lay[y2 * NM_W + X] = 10; else if (v > 40) lay[y2 * NM_W + X] = 11; }
  });
  const out = new Uint8Array(NM_W * NM_H);
  for (let yy = 0; yy < NM_H; yy++) for (let xx = 0; xx < NM_W; xx++) {
    const k = yy * NM_W + xx; if (lay[k] === 10) { out[k] = 10; continue; }
    let d2 = 99;                                         // squared distance to the nearest white fill pixel (radius 3)
    for (let dy = -3; dy <= 3; dy++) { const y2 = yy + dy; if (y2 < 0 || y2 >= NM_H) continue;
      for (let dx = -3; dx <= 3; dx++) { const x2 = xx + dx; if (x2 < 0 || x2 >= NM_W) continue; if (lay[y2 * NM_W + x2] === 10) { const q = dx * dx + dy * dy; if (q < d2) d2 = q; } } }
    const e = Math.sqrt(d2);
    if (e <= 1.0) out[k] = lay[k] === 11 ? 11 : 7;         // orthogonal neighbours: dark, or light where the glyph edge is soft
    else if (e < 1.5) out[k] = 12;                          // diagonal neighbours: light grey
    else if (e <= 2.0) out[k] = 7;                          // the dark line
    else if (e <= 2.9) out[k] = 9;                          // faint rim
  }
  return out;
}
export function encode11(px, w, h) {
  const toks = []; for (let i = 0; i < px.length;) { const v = px[i]; let r = 1; while (r < 16 && i + r < px.length && px[i + r] === v) r++; toks.push(v << 4 | (r - 1)); i += r; }
  const out = new Uint8Array(4 + 8 * Math.ceil(toks.length / 5));
  out.set([(h - 1) & 255, ((h - 1) >> 8 & 3) | (((w - 1) & 15) << 4), ((w - 1) >> 4) & 63, 11]);
  for (let k = 0; k < toks.length; k += 5) {
    let lo = 0, hi = 0;                                  // 5 x 12 bits = 60 bits: tokens 0..1 and part of 2 in the low word
    for (let s = 0; s < 5 && k + s < toks.length; s++) { const t = BigInt(toks[k + s]) << BigInt(12 * s); lo |= Number(t & 0xffffffffn); hi |= Number(t >> 32n); }
    const v = new DataView(out.buffer, 4 + 8 * (k / 5), 8); v.setUint32(0, lo >>> 0, true); v.setUint32(4, hi >>> 0, true);
  }
  return out;
}
/** Picture name for COLOR k look j (0-based): its name; "Empty" for a number with no look. */
const nameText = (prof, k, j) => prof[k][j] ? (prof[k][j].name.trim() || 'Look ' + (j + 1)) : 'Empty';
export async function namesBin(prof) {
  await nmFont();
  const groups = [];
  for (let k = 0; k < 4; k++) {
    let shrink = 0, pics;
    for (;;) {                                           // smaller lettering until COLOR k's five pictures fit 16 KB
      pics = [0, 1, 2, 3, 4].map((j) => encode11(nameIndices(nameText(prof, k, j), shrink), NM_W, NM_H));
      const tot = pics.reduce((a, b) => a + ((b.length + 3) & ~3), 0);
      if (tot <= NM_GROUP_MAX || shrink >= 16) break;
      shrink += 2;
    }
    groups.push(pics);
  }
  const glen = groups.map((pics) => pics.reduce((a, b) => a + ((b.length + 3) & ~3), 0));
  const total = 144 + glen.reduce((a, b) => a + b, 0), b = new Uint8Array(total), v = new DataView(b.buffer);
  b.set([0x4f, 0x4d, 0x33, 0x4e]); v.setUint32(4, total, true); v.setUint16(12, 1, true); v.setUint16(14, 20, true); v.setUint16(16, NM_W, true); v.setUint16(18, NM_H, true);
  let at = 144;
  groups.forEach((pics, k) => {
    v.setUint32(32 + 8 * k, at, true); v.setUint32(36 + 8 * k, glen[k], true);
    let off = 0;
    pics.forEach((pic, j) => { v.setUint16(64 + 4 * (5 * k + j), off, true); v.setUint16(66 + 4 * (5 * k + j), pic.length, true); b.set(pic, at + off); off += (pic.length + 3) & ~3; });
    at += glen[k];
  });
  v.setUint32(8, crc32(b.subarray(12)), true);
  return b;
}
