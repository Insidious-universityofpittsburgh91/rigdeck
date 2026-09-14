/* Minimal QR encoder: byte mode, error-correction level L, versions 1-6.
   That covers 134 bytes, far more than a LAN URL needs, and stops short of version 7
   where the extra version-information block would be required. */

window.QR = (() => {
  const EXP = new Uint8Array(512);
  const LOG = new Uint8Array(256);
  (() => {
    let x = 1;
    for (let i = 0; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 0x100) x ^= 0x11D; }
    for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
  })();
  const mul = (a, b) => (a === 0 || b === 0 ? 0 : EXP[LOG[a] + LOG[b]]);

  // level L only: [total codewords, ec codewords per block, data codewords per block...]
  const VERSIONS = {
    1: { total: 26,  ec: 7,  blocks: [19] },
    2: { total: 44,  ec: 10, blocks: [34] },
    3: { total: 70,  ec: 15, blocks: [55] },
    4: { total: 100, ec: 20, blocks: [80] },
    5: { total: 134, ec: 26, blocks: [108] },
    6: { total: 172, ec: 18, blocks: [68, 68] },
  };

  function genPoly(n) {
    let g = [1];
    for (let i = 0; i < n; i++) {
      const ng = new Array(g.length + 1).fill(0);
      for (let j = 0; j < g.length; j++) {
        ng[j] ^= g[j];
        ng[j + 1] ^= mul(g[j], EXP[i]);
      }
      g = ng;
    }
    return g;
  }

  function rsRemainder(data, n) {
    const g = genPoly(n);
    const res = new Array(n).fill(0);
    for (const byte of data) {
      const factor = byte ^ res[0];
      res.shift();
      res.push(0);
      for (let j = 0; j < n; j++) res[j] ^= mul(g[j + 1], factor);
    }
    return res;
  }

  function pickVersion(byteLength) {
    for (let v = 1; v <= 6; v++) {
      const spec = VERSIONS[v];
      const dataCodewords = spec.blocks.reduce((a, b) => a + b, 0);
      if (byteLength + 2 <= dataCodewords) return v;
    }
    throw new Error('payload too long for this encoder');
  }

  function buildCodewords(bytes, version) {
    const spec = VERSIONS[version];
    const dataCodewords = spec.blocks.reduce((a, b) => a + b, 0);

    const bits = [];
    const push = (value, len) => { for (let i = len - 1; i >= 0; i--) bits.push((value >> i) & 1); };
    push(0b0100, 4);            // byte mode
    push(bytes.length, 8);      // versions 1-9 use an 8 bit count
    bytes.forEach(b => push(b, 8));
    for (let i = 0; i < 4 && bits.length < dataCodewords * 8; i++) bits.push(0);
    while (bits.length % 8) bits.push(0);

    const data = [];
    for (let i = 0; i < bits.length; i += 8) {
      data.push(bits.slice(i, i + 8).reduce((acc, bit) => (acc << 1) | bit, 0));
    }
    const PAD = [0xEC, 0x11];
    for (let i = 0; data.length < dataCodewords; i++) data.push(PAD[i % 2]);

    // split into blocks, then interleave data and error correction
    const dataBlocks = [];
    const ecBlocks = [];
    let cursor = 0;
    spec.blocks.forEach(size => {
      const block = data.slice(cursor, cursor + size);
      cursor += size;
      dataBlocks.push(block);
      ecBlocks.push(rsRemainder(block, spec.ec));
    });

    const out = [];
    const maxData = Math.max(...spec.blocks);
    for (let i = 0; i < maxData; i++) {
      dataBlocks.forEach(block => { if (i < block.length) out.push(block[i]); });
    }
    for (let i = 0; i < spec.ec; i++) {
      ecBlocks.forEach(block => out.push(block[i]));
    }
    return out;
  }

  function newMatrix(size) {
    return Array.from({ length: size }, () => new Array(size).fill(null));
  }

  function placeFunctionPatterns(m, version) {
    const size = m.length;
    const finder = (row, col) => {
      for (let r = -1; r <= 7; r++) {
        for (let c = -1; c <= 7; c++) {
          const rr = row + r, cc = col + c;
          if (rr < 0 || cc < 0 || rr >= size || cc >= size) continue;
          const edge = r === 0 || r === 6 || c === 0 || c === 6;
          const core = r >= 2 && r <= 4 && c >= 2 && c <= 4;
          m[rr][cc] = edge || core ? 1 : 0;
        }
      }
    };
    finder(0, 0);
    finder(0, size - 7);
    finder(size - 7, 0);

    for (let i = 8; i < size - 8; i++) {
      const bit = i % 2 === 0 ? 1 : 0;
      m[6][i] = bit;
      m[i][6] = bit;
    }

    if (version >= 2) {
      const centre = 4 * version + 10;   // versions 2-6 carry exactly one alignment pattern
      for (let r = -2; r <= 2; r++) {
        for (let c = -2; c <= 2; c++) {
          const ring = Math.max(Math.abs(r), Math.abs(c));
          m[centre + r][centre + c] = ring === 1 ? 0 : 1;
        }
      }
    }

    m[size - 8][8] = 1;   // always-dark module

    // reserve the format information strips
    for (let i = 0; i < 9; i++) {
      if (m[8][i] === null) m[8][i] = 2;
      if (m[i][8] === null) m[i][8] = 2;
    }
    for (let i = 0; i < 8; i++) {
      if (m[8][size - 1 - i] === null) m[8][size - 1 - i] = 2;
      if (m[size - 1 - i][8] === null) m[size - 1 - i][8] = 2;
    }
  }

  function placeData(m, codewords) {
    const size = m.length;
    const bits = [];
    codewords.forEach(byte => { for (let i = 7; i >= 0; i--) bits.push((byte >> i) & 1); });

    let index = 0;
    let upward = true;
    for (let right = size - 1; right > 0; right -= 2) {
      if (right === 6) right = 5;   // the vertical timing column is skipped entirely
      for (let step = 0; step < size; step++) {
        const row = upward ? size - 1 - step : step;
        for (const col of [right, right - 1]) {
          if (m[row][col] !== null) continue;
          m[row][col] = index < bits.length ? bits[index++] : 0;
        }
      }
      upward = !upward;
    }
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

  function applyMask(m, reserved, maskIndex) {
    const size = m.length;
    const out = m.map(row => row.slice());
    for (let r = 0; r < size; r++) {
      for (let c = 0; c < size; c++) {
        if (reserved[r][c]) continue;
        if (MASKS[maskIndex](r, c)) out[r][c] ^= 1;
      }
    }
    return out;
  }

  function penalty(m) {
    const size = m.length;
    let score = 0;

    const runScore = line => {
      let total = 0, run = 1;
      for (let i = 1; i < line.length; i++) {
        if (line[i] === line[i - 1]) run++;
        else { if (run >= 5) total += run - 2; run = 1; }
      }
      if (run >= 5) total += run - 2;
      return total;
    };

    const PATTERN_A = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0];
    const PATTERN_B = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1];
    const patternScore = line => {
      let total = 0;
      for (let i = 0; i + 11 <= line.length; i++) {
        const slice = line.slice(i, i + 11);
        if (PATTERN_A.every((v, j) => v === slice[j])) total += 40;
        if (PATTERN_B.every((v, j) => v === slice[j])) total += 40;
      }
      return total;
    };

    for (let r = 0; r < size; r++) {
      const row = m[r];
      const col = m.map(line => line[r]);
      score += runScore(row) + runScore(col) + patternScore(row) + patternScore(col);
    }

    for (let r = 0; r < size - 1; r++) {
      for (let c = 0; c < size - 1; c++) {
        const v = m[r][c];
        if (v === m[r][c + 1] && v === m[r + 1][c] && v === m[r + 1][c + 1]) score += 3;
      }
    }

    let dark = 0;
    m.forEach(row => row.forEach(v => { if (v) dark++; }));
    const pct = (dark * 100) / (size * size);
    score += Math.floor(Math.abs(pct - 50) / 5) * 10;
    return score;
  }

  function formatBits(maskIndex) {
    const data = (0b01 << 3) | maskIndex;   // 01 = error correction level L
    let value = data << 10;
    for (let i = 14; i >= 10; i--) {
      if ((value >> i) & 1) value ^= 0b10100110111 << (i - 10);
    }
    return ((data << 10) | value) ^ 0b101010000010010;
  }

  function placeFormat(m, maskIndex) {
    const size = m.length;
    const bits = formatBits(maskIndex);
    const bit = i => (bits >> i) & 1;

    for (let i = 0; i <= 5; i++) m[8][i] = bit(i);
    m[8][7] = bit(6);
    m[8][8] = bit(7);
    m[7][8] = bit(8);
    for (let i = 9; i <= 14; i++) m[14 - i][8] = bit(i);

    for (let i = 0; i <= 7; i++) m[size - 1 - i][8] = bit(i);
    for (let i = 8; i <= 14; i++) m[8][size - 15 + i] = bit(i);
    m[size - 8][8] = 1;
  }

  function encode(text) {
    const bytes = Array.from(new TextEncoder().encode(text));
    const version = pickVersion(bytes.length);
    const size = 17 + version * 4;

    const m = newMatrix(size);
    placeFunctionPatterns(m, version);
    const reserved = m.map(row => row.map(v => v !== null));
    for (let r = 0; r < size; r++) {
      for (let c = 0; c < size; c++) if (m[r][c] === 2) m[r][c] = 0;
    }

    placeData(m, buildCodewords(bytes, version));

    let best = null, bestScore = Infinity;
    for (let mask = 0; mask < 8; mask++) {
      const candidate = applyMask(m, reserved, mask);
      placeFormat(candidate, mask);
      const score = penalty(candidate);
      if (score < bestScore) { bestScore = score; best = candidate; }
    }
    return best;
  }

  function draw(canvas, text, options = {}) {
    const matrix = encode(text);
    const quiet = options.quiet ?? 4;
    const size = matrix.length + quiet * 2;
    const scale = Math.max(1, Math.floor((options.size || 320) / size));
    canvas.width = canvas.height = size * scale;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = options.light || '#FFFFFF';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = options.dark || '#000000';
    matrix.forEach((row, r) => row.forEach((v, c) => {
      if (v) ctx.fillRect((c + quiet) * scale, (r + quiet) * scale, scale, scale);
    }));
    return matrix.length;
  }

  return { encode, draw };
})();
