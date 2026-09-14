/* The road network, as exported from the game's own .scs files (mods included).
 *
 * The map is cut into square cells of a few kilometres each and fetched only as the
 * truck drives into range, so the panel never pulls a continent to draw the next
 * junction. Cells are immutable until the map is exported again, which is why the
 * server lets the tablet cache them.
 *
 * Coordinates are the game's own world units -- the same ones telemetry reports --
 * so nothing has to be projected or reconciled.
 *
 * Every cell is asked for with the export's timestamp on the URL. Re-exporting a map
 * writes the same filenames with different roads in them, and without that token a
 * tablet that has already driven the old map goes on drawing it for a week out of its
 * own cache. meta.json itself is served uncached, so the new token always arrives.
 */

window.MapData = (function () {
  const MEMORY_CELLS = 800;   // roughly 20 MB of road geometry
  const MAX_INFLIGHT = 8;

  let game = null, cellSize = 4096, bounds = null, version = '';
  let counts = null, mods = [];
  let state = 'idle';         // idle | loading | ready | absent
  let revision = 0;           // bumped whenever drawable data changes

  const cells = new Map();    // "cx_cz" -> cell object, or null once known missing
  const queue = [];
  let inflight = 0;

  function base() { return `maps/${game.toLowerCase()}`; }

  /** Point the loader at ETS2 or ATS. Harmless to call on every telemetry frame. */
  function setGame(next) {
    if (!next || next === game || next === 'unknown') return;
    game = next;
    bounds = counts = null;
    version = '';
    mods = [];
    cells.clear();
    queue.length = 0;
    state = 'loading';
    revision++;

    const forGame = game;
    // no-store, not merely an uncached response: a tablet that fetched this before the
    // server stopped marking it cacheable would otherwise hold the old one for a week
    // and never learn the map had been exported again.
    fetch(`${base()}/meta.json`, { cache: 'no-store' })
      .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(meta => {
        if (forGame !== game) return;
        cellSize = meta.cellSize || 4096;
        version = encodeURIComponent(meta.exported || '');
        bounds = meta.bounds || null;
        counts = meta.counts || null;
        mods = meta.mods || [];
        state = 'ready';
        revision++;
      })
      .catch(() => {
        if (forGame !== game) return;
        state = 'absent';
        revision++;
      });
  }

  function pump() {
    while (inflight < MAX_INFLIGHT && queue.length) {
      const key = queue.shift();
      const forGame = game;
      inflight++;
      fetch(`${base()}/cells/${key}.json${version ? `?v=${version}` : ''}`)
        .then(r => (r.ok ? r.json() : null))
        .then(cell => {
          if (forGame !== game) return;
          cells.set(key, cell);
          if (cell) revision++;
        })
        .catch(() => { if (forGame === game) cells.set(key, null); })
        .finally(() => { inflight--; pump(); });
    }
  }

  /** Drop the cells furthest from what is on screen once memory gets silly. */
  function evict(keep) {
    if (cells.size <= MEMORY_CELLS) return;
    for (const key of cells.keys()) {
      if (cells.size <= MEMORY_CELLS) break;
      if (!keep.has(key)) cells.delete(key);
    }
  }

  /**
   * Everything loaded inside a world-space box, queueing whatever is missing.
   * Returns immediately -- the caller redraws when `revision` moves on.
   */
  function inBox(x0, z0, x1, z1) {
    if (state !== 'ready') return [];
    const found = [];
    const keep = new Set();
    for (let cx = Math.floor(x0 / cellSize); cx <= Math.floor(x1 / cellSize); cx++) {
      for (let cz = Math.floor(z0 / cellSize); cz <= Math.floor(z1 / cellSize); cz++) {
        const key = cx + '_' + cz;
        keep.add(key);
        if (cells.has(key)) {
          const cell = cells.get(key);
          if (cell) found.push(cell);
        } else if (!queue.includes(key)) {
          queue.push(key);
        }
      }
    }
    evict(keep);
    pump();
    return found;
  }

  return {
    setGame,
    inBox,
    get revision() { return revision; },
    get state() { return state; },
    get cellSize() { return cellSize; },
    get bounds() { return bounds; },
    get counts() { return counts; },
    get mods() { return mods; },
    get loading() { return queue.length + inflight; },
  };
})();
