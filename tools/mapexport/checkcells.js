/* Draws the exported road cells the way the panel draws them, straight to a PNG.
 *
 * The point is to check the export itself rather than the browser: if this picture
 * shows the roads around a city, then the cells, their coordinates and the widths
 * are all sound, and anything wrong on the tablet is the tablet's own doing.
 *
 *   node checkcells.js <ets2|ats> <city name> <metres across> <out.png>
 */

'use strict';
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const [, , game = 'ets2', wanted = 'Duisburg', spanArg = '6000', out = 'cells.png'] = process.argv;
const root = path.join(__dirname, '..', '..', 'web', 'maps', game);
const span = Number(spanArg);
const SIZE = 900;

const meta = JSON.parse(fs.readFileSync(path.join(root, 'meta.json'), 'utf8'));
const cellSize = meta.cellSize;

function readCell(cx, cz) {
  const file = path.join(root, 'cells', `${cx}_${cz}.json`);
  if (!fs.existsSync(file)) return null;
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

// Find the city by name, the same way the panel would if you searched for it.
let centre = null;
outer:
for (const name of fs.readdirSync(path.join(root, 'cells'))) {
  const cell = JSON.parse(fs.readFileSync(path.join(root, 'cells', name), 'utf8'));
  for (const city of cell.c || []) {
    if (city[2].toLowerCase() === wanted.toLowerCase()) { centre = city; break outer; }
  }
}
if (!centre) { console.error(`no city named ${wanted} in the ${game} export`); process.exit(1); }
console.log(`  ${centre[2]} at ${centre[0]}, ${centre[1]}`);

const scale = SIZE / span;
const px = (x, z) => [(x - centre[0]) * scale + SIZE / 2, (z - centre[1]) * scale + SIZE / 2];

const buf = new Uint8Array(SIZE * SIZE * 3).fill(0x14);

function dot(x, y, r, g, b) {
  x |= 0; y |= 0;
  if (x < 0 || y < 0 || x >= SIZE || y >= SIZE) return;
  const i = (y * SIZE + x) * 3;
  buf[i] = r; buf[i + 1] = g; buf[i + 2] = b;
}

function line(x0, y0, x1, y1, weight, r, g, b) {
  const steps = Math.max(1, Math.ceil(Math.hypot(x1 - x0, y1 - y0)));
  const half = Math.max(0, Math.round(weight / 2));
  for (let s = 0; s <= steps; s++) {
    const t = s / steps;
    const x = x0 + (x1 - x0) * t, y = y0 + (y1 - y0) * t;
    for (let dx = -half; dx <= half; dx++)
      for (let dy = -half; dy <= half; dy++) dot(x + dx, y + dy, r, g, b);
  }
}

let drawn = 0, cellsUsed = 0;
const half = span / 2;
for (let cx = Math.floor((centre[0] - half) / cellSize); cx <= Math.floor((centre[0] + half) / cellSize); cx++) {
  for (let cz = Math.floor((centre[1] - half) / cellSize); cz <= Math.floor((centre[1] + half) / cellSize); cz++) {
    const cell = readCell(cx, cz);
    if (!cell) continue;
    cellsUsed++;

    for (const ring of cell.a || []) {
      for (let i = 0; i + 3 < ring.length; i += 2) {
        const a = px(ring[i], ring[i + 1]), b2 = px(ring[i + 2], ring[i + 3]);
        line(a[0], a[1], b2[0], b2[1], 0, 0x2a, 0x24, 0x1c);
      }
    }

    for (const road of cell.r) {
      const width = road[0];
      const weight = Math.max(1, Math.round(width * scale));
      const shade = width >= 15 ? [0xf1, 0xe9, 0xda] : width >= 8 ? [0xb8, 0xae, 0x9e] : [0x6e, 0x65, 0x59];
      for (let i = 2; i + 3 < road.length; i += 2) {
        const a = px(road[i], road[i + 1]), b2 = px(road[i + 2], road[i + 3]);
        line(a[0], a[1], b2[0], b2[1], weight, shade[0], shade[1], shade[2]);
      }
      drawn++;
    }

    for (const city of cell.c || []) {
      const p = px(city[0], city[1]);
      for (let dx = -4; dx <= 4; dx++) for (let dy = -4; dy <= 4; dy++) dot(p[0] + dx, p[1] + dy, 0xff, 0xc9, 0x64);
    }
  }
}
console.log(`  ${cellsUsed} cells, ${drawn} roads drawn across ${span} m`);
if (!drawn) { console.error('  nothing was drawn -- the export is empty here'); process.exit(1); }

// -- minimal PNG writer -------------------------------------------------------
const raw = Buffer.alloc((SIZE * 3 + 1) * SIZE);
for (let y = 0; y < SIZE; y++) {
  raw[y * (SIZE * 3 + 1)] = 0;
  Buffer.from(buf.buffer, y * SIZE * 3, SIZE * 3).copy(raw, y * (SIZE * 3 + 1) + 1);
}
const chunk = (type, data) => {
  const head = Buffer.alloc(8);
  head.writeUInt32BE(data.length, 0);
  head.write(type, 4, 'ascii');
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([head.slice(4), data])) >>> 0, 0);
  return Buffer.concat([head, data, crc]);
};
let table = null;
function crc32(buffer) {
  if (!table) {
    table = new Int32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      table[n] = c;
    }
  }
  let c = -1;
  for (const byte of buffer) c = table[(c ^ byte) & 0xff] ^ (c >>> 8);
  return c ^ -1;
}
const ihdr = Buffer.alloc(13);
ihdr.writeUInt32BE(SIZE, 0); ihdr.writeUInt32BE(SIZE, 4);
ihdr[8] = 8; ihdr[9] = 2;
fs.writeFileSync(out, Buffer.concat([
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
  chunk('IHDR', ihdr),
  chunk('IDAT', zlib.deflateSync(raw)),
  chunk('IEND', Buffer.alloc(0)),
]));
console.log(`  wrote ${out}`);
