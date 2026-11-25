// QR code of the public page as SVG and PNG, large enough to print (used by /qr.svg, /qr.png and scripts/qr.js).
// Error correction level Q: the code still reads when up to a quarter of it is dirty or folded.
import qrcode from 'qrcode-generator';

const QUIET = 4;   // white border in modules, as the QR standard requires

function matrix(text) {
  const q = qrcode(0, 'Q');
  q.addData(text, 'Byte');
  q.make();
  const n = q.getModuleCount();
  return { n, dark: (r, c) => q.isDark(r, c) };
}

export function qrSvg(text) {
  const { n, dark } = matrix(text);
  const size = n + 2 * QUIET;
  let d = '';
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      if (!dark(r, c)) continue;
      let w = 1;
      while (c + w < n && dark(r, c + w)) w++;
      d += `M${c + QUIET} ${r + QUIET}h${w}v1h-${w}z`;
      c += w - 1;
    }
  }
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" width="100mm" height="100mm" shape-rendering="crispEdges">
<rect width="${size}" height="${size}" fill="#fff"/><path fill="#000" d="${d}"/></svg>`;
}

// PNG, 8-bit greyscale; scale = pixels per module (40 → about 1500 × 1500 px, enough for A4 at 300 dpi)
export async function qrPng(text, scale = 40) {
  const { n, dark } = matrix(text);
  const px = (n + 2 * QUIET) * scale;
  const raw = new Uint8Array(px * (px + 1));
  for (let y = 0; y < px; y++) {
    const row = y * (px + 1);
    raw[row] = 0;   // filter: none
    const r = Math.floor(y / scale) - QUIET;
    for (let x = 0; x < px; x++) {
      const c = Math.floor(x / scale) - QUIET;
      raw[row + 1 + x] = r >= 0 && r < n && c >= 0 && c < n && dark(r, c) ? 0 : 255;
    }
  }
  const idat = new Uint8Array(await new Response(new Blob([raw]).stream().pipeThrough(new CompressionStream('deflate'))).arrayBuffer());
  const ihdr = new Uint8Array(13);
  const v = new DataView(ihdr.buffer);
  v.setUint32(0, px); v.setUint32(4, px); ihdr[8] = 8; ihdr[9] = 0;   // 8-bit greyscale
  // pHYs: 300 dpi = 11811 pixels per metre, so the printed size is right
  const phys = new Uint8Array(9);
  new DataView(phys.buffer).setUint32(0, 11811); new DataView(phys.buffer).setUint32(4, 11811); phys[8] = 1;
  return concat([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', ihdr), chunk('pHYs', phys), chunk('IDAT', idat), chunk('IEND', new Uint8Array(0))]);
}

const CRC = (() => {
  const t = new Uint32Array(256);
  for (let i = 0; i < 256; i++) { let c = i; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[i] = c >>> 0; }
  return t;
})();
function crc32(bytes) {
  let c = 0xffffffff;
  for (const b of bytes) c = CRC[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const out = new Uint8Array(12 + data.length);
  const v = new DataView(out.buffer);
  v.setUint32(0, data.length);
  for (let i = 0; i < 4; i++) out[4 + i] = type.charCodeAt(i);
  out.set(data, 8);
  v.setUint32(8 + data.length, crc32(out.subarray(4, 8 + data.length)));
  return out;
}
function concat(parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}
