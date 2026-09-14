/* Independent check of qr.js: rebuild the reserved-module map, read the format
   information back out of the matrix, unmask, walk the data placement in reverse and
   verify the Reed-Solomon syndromes are zero, then compare the decoded payload.

   Run with:  node test_qr.js
*/

const fs = require('fs');
const path = require('path');

global.window = {};
eval(fs.readFileSync(path.join(__dirname, 'qr.js'), 'utf8'));
const QR = global.window.QR;

let failures = 0;
function check(label, ok, detail = '') {
  console.log(`  [${ok ? 'ok  ' : 'FAIL'}] ${label}${detail ? '  -- ' + detail : ''}`);
  if (!ok) failures++;
}

// --- an independent GF(256) for the syndrome check --------------------------
const EXP = new Uint8Array(512), LOG = new Uint8Array(256);
{
  let x = 1;
  for (let i = 0; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 0x100) x ^= 0x11D; }
  for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
}
const mul = (a, b) => (a === 0 || b === 0 ? 0 : EXP[LOG[a] + LOG[b]]);

function reservedMap(size, version) {
  const res = Array.from({ length: size }, () => new Array(size).fill(false));
  const mark = (r, c) => { if (r >= 0 && c >= 0 && r < size && c < size) res[r][c] = true; };

  for (const [row, col] of [[0, 0], [0, size - 7], [size - 7, 0]]) {
    for (let r = -1; r <= 7; r++) for (let c = -1; c <= 7; c++) mark(row + r, col + c);
  }
  for (let i = 0; i < size; i++) { mark(6, i); mark(i, 6); }
  if (version >= 2) {
    const centre = 4 * version + 10;
    for (let r = -2; r <= 2; r++) for (let c = -2; c <= 2; c++) mark(centre + r, centre + c);
  }
  for (let i = 0; i < 9; i++) { mark(8, i); mark(i, 8); }
  for (let i = 0; i < 8; i++) { mark(8, size - 1 - i); mark(size - 1 - i, 8); }
  return res;
}

const MASKS = [
  (r, c) => (r + c) % 2 === 0,
  (r) => r % 2 === 0,
  (r, c) => c % 3 === 0,
  (r, c) => (r + c) % 3 === 0,
  (r, c) => (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0,
  (r, c) => ((r * c) % 2) + ((r * c) % 3) === 0,
  (r, c) => (((r * c) % 2) + ((r * c) % 3)) % 2 === 0,
  (r, c) => (((r + c) % 2) + ((r * c) % 3)) % 2 === 0,
];

function readFormat(m) {
  const bits = [];
  for (let i = 0; i <= 5; i++) bits[i] = m[8][i];
  bits[6] = m[8][7];
  bits[7] = m[8][8];
  bits[8] = m[7][8];
  for (let i = 9; i <= 14; i++) bits[i] = m[14 - i][8];
  let value = 0;
  for (let i = 14; i >= 0; i--) value = (value << 1) | bits[i];
  const data = (value ^ 0b101010000010010) >> 10;
  return { ecLevel: data >> 3, mask: data & 7 };
}

function readCodewords(m, reserved) {
  const size = m.length;
  const bits = [];
  let upward = true;
  for (let right = size - 1; right > 0; right -= 2) {
    if (right === 6) right = 5;
    for (let step = 0; step < size; step++) {
      const row = upward ? size - 1 - step : step;
      for (const col of [right, right - 1]) {
        if (reserved[row][col]) continue;
        bits.push(m[row][col]);
      }
    }
    upward = !upward;
  }
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) {
    bytes.push(bits.slice(i, i + 8).reduce((acc, bit) => (acc << 1) | bit, 0));
  }
  return bytes;
}

function syndromesZero(block, ecCount) {
  for (let i = 0; i < ecCount; i++) {
    let acc = 0;
    for (const byte of block) acc = mul(acc, EXP[i]) ^ byte;
    if (acc !== 0) return false;
  }
  return true;
}

function verify(text, expectVersion) {
  console.log(`\n  payload: ${JSON.stringify(text)}`);
  const matrix = QR.encode(text);
  const size = matrix.length;
  const version = (size - 17) / 4;

  check('version as expected', version === expectVersion, `v${version}, ${size}x${size}`);

  // structure
  const finderOk = [[0, 0], [0, size - 7], [size - 7, 0]].every(([row, col]) => {
    for (let r = 0; r < 7; r++) for (let c = 0; c < 7; c++) {
      const edge = r === 0 || r === 6 || c === 0 || c === 6;
      const core = r >= 2 && r <= 4 && c >= 2 && c <= 4;
      if (matrix[row + r][col + c] !== (edge || core ? 1 : 0)) return false;
    }
    return true;
  });
  check('three finder patterns intact', finderOk);

  let timingOk = true;
  for (let i = 8; i < size - 8; i++) {
    const want = i % 2 === 0 ? 1 : 0;
    if (matrix[6][i] !== want || matrix[i][6] !== want) timingOk = false;
  }
  check('timing patterns alternate', timingOk);
  check('dark module set', matrix[size - 8][8] === 1);

  const fmt = readFormat(matrix);
  check('format says error level L', fmt.ecLevel === 0b01, `bits ${fmt.ecLevel.toString(2)}`);
  check('format mask in range', fmt.mask >= 0 && fmt.mask <= 7, `mask ${fmt.mask}`);

  // unmask and read the data back out
  const reserved = reservedMap(size, version);
  const plain = matrix.map((row, r) => row.map((v, c) =>
    reserved[r][c] ? v : v ^ (MASKS[fmt.mask](r, c) ? 1 : 0)));

  const stream = readCodewords(plain, reserved);
  const SPEC = {
    1: { ec: 7, blocks: [19] }, 2: { ec: 10, blocks: [34] }, 3: { ec: 15, blocks: [55] },
    4: { ec: 20, blocks: [80] }, 5: { ec: 26, blocks: [108] }, 6: { ec: 18, blocks: [68, 68] },
  }[version];

  // de-interleave
  const dataBlocks = SPEC.blocks.map(() => []);
  const ecBlocks = SPEC.blocks.map(() => []);
  let cursor = 0;
  const maxData = Math.max(...SPEC.blocks);
  for (let i = 0; i < maxData; i++) {
    SPEC.blocks.forEach((len, b) => { if (i < len) dataBlocks[b].push(stream[cursor++]); });
  }
  for (let i = 0; i < SPEC.ec; i++) {
    SPEC.blocks.forEach((_, b) => ecBlocks[b].push(stream[cursor++]));
  }

  const allZero = dataBlocks.every((block, b) => syndromesZero(block.concat(ecBlocks[b]), SPEC.ec));
  check('reed-solomon syndromes are zero', allZero);

  // decode the byte-mode payload from the first block sequence
  const data = dataBlocks.flat();
  const bitstream = [];
  data.forEach(byte => { for (let i = 7; i >= 0; i--) bitstream.push((byte >> i) & 1); });
  const take = (start, len) => bitstream.slice(start, start + len).reduce((a, b) => (a << 1) | b, 0);
  const mode = take(0, 4);
  const length = take(4, 8);
  check('mode is byte', mode === 0b0100, mode.toString(2));
  check('length matches', length === Buffer.byteLength(text), `${length} vs ${Buffer.byteLength(text)}`);

  const out = [];
  for (let i = 0; i < length; i++) out.push(take(12 + i * 8, 8));
  const decoded = Buffer.from(out).toString('utf8');
  check('payload round-trips', decoded === text, JSON.stringify(decoded));
}

console.log('\nQR encoder self test');
verify('http://192.168.1.23:8384', 2);
verify('http://192.168.100.240:8384/index.html?panel=main&rig=scania', 4);
verify('http://10.0.0.5:8384/index.html?a=' + 'x'.repeat(60), 5);
// version 6 is the first with two blocks, so it exercises the interleaving path
verify('http://10.0.0.5:8384/index.html?a=' + 'x'.repeat(95), 6);

console.log();
if (failures) { console.log(`${failures} check(s) failed\n`); process.exit(1); }
console.log('all checks passed\n');
