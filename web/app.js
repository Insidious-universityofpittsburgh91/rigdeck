/* Rig Deck panel client.
   Talks to the server over one websocket: telemetry in, commands out. Every command
   with a telemetry counterpart stays "pending" until the game reports the new state,
   so a button never claims something the truck did not actually do. */

(() => {
  const $ = s => document.querySelector(s);
  const deck = $('#deck');
  const mapCv = $('#map');
  const mctx = mapCv.getContext('2d');

  /* ── fixed landscape canvas, scaled to whatever screen we are on ───────── */
  const W = 1600;
  function fit() {
    const vw = innerWidth, vh = innerHeight;
    const ar = Math.min(2.0, Math.max(1.4, vw / vh));
    const H = Math.round(W / ar);
    deck.style.width = W + 'px';
    deck.style.height = H + 'px';
    deck.style.setProperty('--u', Math.min(W * 0.0098, H * 0.0157) + 'px');
    deck.style.transform = `translate(-50%,-50%) scale(${Math.min(vw / W, vh / H) * 0.995})`;
    mapCv.width = Math.max(2, Math.round(mapCv.clientWidth * 2));
    mapCv.height = Math.max(2, Math.round(mapCv.clientHeight * 2));
  }
  addEventListener('resize', fit);
  addEventListener('orientationchange', () => setTimeout(fit, 200));

  /* ── static chrome ─────────────────────────────────────────────────────── */
  const RPM_SEGS = 26, RED_FROM = 20, rpmEl = $('#rpm');
  for (let i = 0; i < RPM_SEGS; i++) {
    const seg = document.createElement('i');
    if (i >= RED_FROM) seg.classList.add('red');
    rpmEl.appendChild(seg);
  }

  const DAMAGE_ROWS = [
    ['Engine', 'engine'], ['Transmission', 'transmission'], ['Cabin', 'cabin'],
    ['Chassis', 'chassis'], ['Wheels', 'wheels'], ['Cargo', 'cargo'],
  ];
  const dmgEl = $('#dmg'), dmgBars = {};
  DAMAGE_ROWS.forEach(([label, key]) => {
    dmgEl.insertAdjacentHTML('beforeend',
      `<span>${label}</span><div class="track"><div class="fill ok"></div></div><b>—</b>`);
    const cells = dmgEl.children;
    dmgBars[key] = {
      fill: cells[cells.length - 2].firstElementChild,
      text: cells[cells.length - 1],
    };
  });

  const arcFg = $('#arcFg'), arcLim = $('#arcLim');
  const ARC = arcFg.getTotalLength();
  arcFg.style.strokeDasharray = ARC;
  arcLim.style.strokeDasharray = `${ARC * 0.012} ${ARC}`;

  /* ── unit formatting ───────────────────────────────────────────────────── */
  let units = 'metric', currency = 'EUR';
  let restFull = 660, restSeen = false;   // see the fatigue bar, below
  let mapWarned = null;                   // the game an out-of-date map has been reported for
  const SYMBOL = { EUR: '€', USD: '$', GBP: '£', CHF: 'CHF' };
  const imperial = () => units === 'imperial';

  const speedVal = ms => Math.round(ms * (imperial() ? 2.23694 : 3.6));
  const speedUnit = () => (imperial() ? 'mph' : 'km / h');
  const distKm = km => (imperial() ? km * 0.621371 : km);
  const distUnit = () => (imperial() ? 'mi' : 'km');
  const volume = l => (imperial() ? l * 0.264172 : l);
  const volumeUnit = () => (imperial() ? 'gal' : 'l');
  const temp = c => (imperial() ? c * 9 / 5 + 32 : c);
  const tempUnit = () => (imperial() ? '°F' : '°C');
  const pressure = psi => (imperial() ? psi : psi * 0.0689476);
  const pressureUnit = () => (imperial() ? 'psi' : 'bar');
  const mass = kg => (imperial() ? kg * 0.00110231 : kg / 1000);
  const massUnit = () => (imperial() ? 'sh tn' : 't');
  const money = n => `${SYMBOL[currency] || ''} ${Math.round(n).toLocaleString('en-US').replace(/,/g, ' ')}`;

  const pad = n => String(Math.floor(n)).padStart(2, '0');
  const hhmm = min => `${pad((min / 60) % 24)}:${pad(min % 60)}`;
  const hmm = min => `${Math.floor(min / 60)}:${pad(min % 60)}`;
  const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];

  /* ── link state ────────────────────────────────────────────────────────── */
  const pill = $('#link'), linkText = $('#linkText'), linkMs = $('#linkMs');
  let ws = null, retry = 0, lastFrame = 0, latency = null, gameOnline = false, pinger = null;

  function setLink(kind, label, detail) {
    pill.dataset.link = kind;
    linkText.textContent = label;
    linkMs.textContent = detail || '';
    deck.classList.toggle('stale', kind !== 'live');
    deck.classList.toggle('nolink', kind === 'down');
  }

  function connect() {
    // Without this, a retry that fires while a socket is already up opens a second one
    // and abandons the first -- the server keeps both, and the tablet collects
    // connections it will never read from.
    if (ws && (ws.readyState === 0 || ws.readyState === 1)) return;
    const url = `ws://${location.host}/ws`;
    let sock;
    try { sock = new WebSocket(url); } catch (err) { scheduleRetry(); return; }
    ws = sock;
    // Every handler below checks that this socket is still the current one. An earlier
    // socket can close long after its replacement is live, and without the check its
    // onclose would null out the connection that is actually working.
    const current = () => ws === sock;

    ws.onopen = () => {
      retry = 0;
      lastFrame = Date.now();   // so the watchdog measures this socket, not the last one
      setLink('stale', 'LINKED', 'waiting for game');
      clearInterval(pinger);    // every reconnect used to leave its own ping timer behind
      pinger = setInterval(() => {
        if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'ping', t: Date.now() }));
      }, 2000);
    };

    ws.onmessage = ev => {
      if (!current()) return;
      const msg = JSON.parse(ev.data);
      if (msg.type === 'tel') onTelemetry(msg);
      else if (msg.type === 'pong') latency = Date.now() - msg.t;
      else if (msg.type === 'ack') onAck(msg);
      else if (msg.type === 'hello') onHello(msg);
    };

    sock.onclose = () => {
      if (!current()) return;   // an old socket letting go; the live one carries on
      ws = null;
      clearInterval(pinger);
      pinger = null;
      setLink('down', 'NO LINK', 'reconnecting');
      scheduleRetry();
    };
    sock.onerror = () => { try { sock.close(); } catch (err) { /* already going */ } };
  }

  let retryTimer = null;
  function scheduleRetry() {
    if (retryTimer) return;   // one ladder at a time, however many closes arrive
    retry = Math.min(retry + 1, 6);
    retryTimer = setTimeout(() => { retryTimer = null; connect(); },
                            [400, 700, 1200, 2000, 3000, 5000, 5000][retry]);
  }

  pill.addEventListener('click', () => {
    if (ws) ws.close();
    else connect();
    notice('reconnecting…');
  });

  let vjoyReady = false;
  function onHello(msg) {
    vjoyReady = !!(msg.vjoy && msg.vjoy.available);
    if (!vjoyReady) notice(`Controls off: ${msg.vjoy ? msg.vjoy.reason : 'vJoy unavailable'}`, 6000);
    if (msg.config) applyUnitChip(msg.config);
  }

  /* ── notices ───────────────────────────────────────────────────────────── */
  const noticeEl = $('#notice');
  let noticeTimer = null;
  function notice(text, ms = 3200) {
    noticeEl.textContent = text;
    noticeEl.classList.add('show');
    clearTimeout(noticeTimer);
    noticeTimer = setTimeout(() => noticeEl.classList.remove('show'), ms);
  }

  /* ── commands ──────────────────────────────────────────────────────────── */
  let seq = 0;
  const pending = new Map();   // element -> {path, expected, deadline}
  const acks = new Map();      // seq -> element
  let latest = {};

  const haptic = p => navigator.vibrate && navigator.vibrate(p);

  function dig(obj, path) {
    return path.split('.').reduce((node, key) => (node == null ? undefined : node[key]), obj);
  }

  function send(payload) {
    if (!ws || ws.readyState !== 1) { notice('No link to the PC'); return false; }
    ws.send(JSON.stringify(payload));
    return true;
  }

  function fire(el, id, extra = {}) {
    const s = ++seq;
    if (!send({ type: 'cmd', id, seq: s, ...extra })) return;
    haptic(12);
    acks.set(s, el);
    const path = el.dataset.confirm;
    // Read-back needs telemetry, and a menu has none. There the ack is the whole
    // answer -- waiting for a confirmation that cannot come only ends in "failed".
    if (path && gameOnline) {
      // data-cycle marks a control that steps through several values rather than
      // flipping one -- the light switch walks off → parking → low, so the proof it
      // worked is that the reading moved at all, not that it landed on a known value.
      const cycle = el.hasAttribute('data-cycle');
      const expected = cycle ? dig(latest, path)
        : 'value' in extra ? extra.value
        : !dig(latest, path);
      el.classList.add('pending');
      // Telemetry arrives twenty times a second, so a bound control confirms in about a
      // tenth of a second. Anything still waiting near a second was not going to come.
      pending.set(el, { path, expected, cycle, deadline: Date.now() + 900 });
    }
  }

  function onAck(msg) {
    const el = acks.get(msg.seq);
    acks.delete(msg.seq);
    if (!el) return;
    if (!msg.ok) {
      pending.delete(el);
      el.classList.remove('pending');
      el.classList.add('failed');
      setTimeout(() => el.classList.remove('failed'), 400);
      notice(msg.detail || 'Command refused');
      return;
    }
    if (!pending.has(el)) {   // nothing to read back, so flash an acknowledgement
      el.classList.add('ack');
      haptic(22);
      // Short enough to read as a press rather than as a state the button is now in.
      setTimeout(() => el.classList.remove('ack'), 160);
    }
  }

  function resolvePending() {
    const now = Date.now();
    pending.forEach((watch, el) => {
      const current = dig(latest, watch.path);
      if (watch.cycle ? current !== watch.expected : current === watch.expected) {
        pending.delete(el);
        el.classList.remove('pending');
        haptic(22);
      } else if (!gameOnline) {
        // the game went to a menu mid-flight; there is nothing left to read back,
        // and blaming the binding for that would be a lie
        pending.delete(el);
        el.classList.remove('pending');
      } else if (now > watch.deadline) {
        pending.delete(el);
        el.classList.remove('pending');
        el.classList.add('failed');
        setTimeout(() => el.classList.remove('failed'), 400);
        notice('The game did not confirm that — check the button binding');
      }
    });
  }

  // Every control is now one button pressing one bound button, segments included --
  // their children carry their own data-cmd, so there is nothing left to delegate.
  document.querySelectorAll('[data-cmd]').forEach(el => {
    el.addEventListener('click', () => fire(el, el.dataset.cmd));
  });

  document.querySelectorAll('[data-hold]').forEach(btn => {
    const id = btn.dataset.hold;
    const down = () => { btn.classList.add('on'); haptic(12); send({ type: 'cmd', id, down: true, seq: ++seq }); };
    const up = () => { if (btn.classList.contains('on')) { btn.classList.remove('on'); send({ type: 'cmd', id, down: false, seq: ++seq }); } };
    btn.addEventListener('pointerdown', down);
    ['pointerup', 'pointerleave', 'pointercancel'].forEach(e => btn.addEventListener(e, up));
  });

  /* ── units chip ────────────────────────────────────────────────────────── */
  const unitChip = $('#unitChip');
  let unitPref = 'auto';
  function applyUnitChip(cfg) { unitPref = cfg.units || 'auto'; }
  unitChip.addEventListener('click', () => {
    unitPref = unitPref === 'auto' ? 'metric' : unitPref === 'metric' ? 'imperial' : 'auto';
    send({ type: 'config', changes: { units: unitPref } });
    notice(`Units: ${unitPref}`);
  });

  /* ── map ───────────────────────────────────────────────────────────────── */
  // Canvas pixels per metre. Two levels wider than before for looking at the route,
  // two closer for finding the right gate in a yard.
  const ZOOMS = [0.012, 0.035, 0.09, 0.2, 0.45, 1.0, 2.2, 4.5];
  const ZOOM_MIN = ZOOMS[0], ZOOM_MAX = ZOOMS[ZOOMS.length - 1];
  // The zoom is a scale, not one of eight settings, because a pinch is continuous and
  // snapping it to the nearest rung would fight the fingers. The buttons still move
  // between the named levels -- from wherever a pinch happened to leave things.
  let zoom = ZOOMS[3];                       // 0.2, the same view the panel opened on before
  const clampZoom = z => Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z));
  $('#zin').onclick = () => { zoom = ZOOMS.find(z => z > zoom * 1.02) || ZOOM_MAX; };
  $('#zout').onclick = () => {
    const below = ZOOMS.filter(z => z < zoom * 0.98);
    zoom = below.length ? below[below.length - 1] : ZOOM_MIN;
  };

  /* ── dragging the map ──────────────────────────────────────────────────────
     The map is drawn heading-up, so a drag has to be rotated back into world
     coordinates before it means anything. `pan` is that offset, in metres, and the
     view is the truck plus it -- which keeps the truck marker at its real position
     rather than pinned to the middle. */
  const PAN_LIMIT = 60000;                   // metres; far enough to look ahead, not to get lost
  const PAN_RETURN_MS = 8000;                // hands off this long and it drifts home
  let pan = { x: 0, z: 0 }, panning = false, panAt = 0, lastBearing = 0;
  const mapWrap = $('.mapwrap'), recentre = $('#recentre');

  function panned() { return Math.hypot(pan.x, pan.z) > 1; }

  function clearPan() { pan = { x: 0, z: 0 }; }

  /* One finger drags, two pinch, and two do both at once -- the midpoint of the pair
     drags while the gap between them zooms, which is what hands expect and what makes
     it possible to pull one junction into the middle of the screen and open it up in a
     single movement. Everything works off the centroid of whatever is down, so adding
     or lifting a finger changes what is tracked without the map jumping: the movement
     is always measured between two readings of the same set of fingers. */
  const touches = new Map();                 // pointerId -> {x, y}
  let pinchGap = 0, pinchZoom = 0, pinching = false;

  const centroid = () => {
    let x = 0, y = 0;
    for (const point of touches.values()) { x += point.x; y += point.y; }
    return { x: x / touches.size, y: y / touches.size };
  };
  const gap = () => {
    const [a, b] = [...touches.values()];
    return Math.hypot(a.x - b.x, a.y - b.y);
  };

  function dragBy(dx, dy) {
    const rect = mapCv.getBoundingClientRect();
    if (!rect.width) return;
    // Client pixels to canvas pixels. The whole panel is CSS-scaled to fit the screen,
    // and measuring the rendered box is what makes this independent of that scale.
    const ratio = mapCv.width / rect.width;
    const sx = -dx * ratio, sy = -dy * ratio;
    const cos = Math.cos(lastBearing), sin = Math.sin(lastBearing);
    pan.x += (sx * cos - sy * sin) / zoom;
    pan.z += (sx * sin + sy * cos) / zoom;

    const far = Math.hypot(pan.x, pan.z);
    if (far > PAN_LIMIT) { pan.x *= PAN_LIMIT / far; pan.z *= PAN_LIMIT / far; }
  }

  function markPinch() {
    pinching = touches.size >= 2;
    if (pinching) { pinchGap = gap(); pinchZoom = zoom; }
  }

  mapWrap.addEventListener('pointerdown', event => {
    if (event.target.closest('button')) return;   // the zoom keys are not a drag
    touches.set(event.pointerId, { x: event.clientX, y: event.clientY });
    mapWrap.setPointerCapture(event.pointerId);
    panning = true;
    mapWrap.classList.add('dragging');
    markPinch();
  });

  mapWrap.addEventListener('pointermove', event => {
    if (!touches.has(event.pointerId)) return;
    const before = centroid();
    touches.set(event.pointerId, { x: event.clientX, y: event.clientY });
    const after = centroid();

    if (pinching && touches.size === 2 && pinchGap > 0) {
      const now = gap();
      if (now > 0) zoom = clampZoom(pinchZoom * (now / pinchGap));
    }
    dragBy(after.x - before.x, after.y - before.y);
  });

  const endPan = event => {
    if (!touches.delete(event.pointerId)) return;
    // Lifting one of two finishes the pinch but leaves the other one dragging, so the
    // baseline is taken again rather than the gesture being abandoned mid-movement.
    markPinch();
    if (touches.size) return;
    panning = false;
    panAt = Date.now();
    mapWrap.classList.remove('dragging');
  };
  // No pointerleave: the capture keeps the finger ours until it lifts, and a leave
  // during the drag would drop it halfway across the map.
  ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(e => mapWrap.addEventListener(e, endPan));
  recentre.addEventListener('click', clearPan);

  // A mouse has no second finger. The wheel is the same gesture by other means, and it
  // costs nothing to support on the desktop where the panel is developed.
  mapWrap.addEventListener('wheel', event => {
    event.preventDefault();
    zoom = clampZoom(zoom * Math.pow(0.9987, event.deltaY));
  }, { passive: false });

  function easePan() {
    if (panning || !panned()) return;
    if (Date.now() - panAt < PAN_RETURN_MS) return;
    pan.x *= 0.86;
    pan.z *= 0.86;
    if (!panned()) clearPan();
  }

  // No breadcrumb trail. Where the truck has already been is the one thing on a GPS
  // nobody needs to look at, and drawn in the accent colour it read as a route.
  const cssVar = name => getComputedStyle(deck).getPropertyValue(name).trim();

  /* The road network is drawn north-up into an off-screen buffer that is a little
     larger than the map window, then blitted rotated each frame. Redrawing tens of
     thousands of road segments at 20 Hz would not hold; blitting one image does. */
  const MARGIN = 150;                       // device pixels of slack around the view
  const buf = document.createElement('canvas');
  const bctx = buf.getContext('2d');
  let bufAnchor = null, bufScale = 0, bufRevision = -1, bufAt = 0, bufSize = 0;
  let bufCities = [], bufPlaces = [];
  let lastCellCount = -1, lastRoadCount = -1;

  /* Places worth stopping at, as the game's own map draws them.
   *
   * Glyphs are stroked into a filled chip rather than written as text: at this size a
   * word is unreadable and a bare dot says nothing, but a pump, a bed and a spanner
   * are recognised without being read. `from` is the zoom each kind earns its place at
   * -- fuel and parking are what you scan for and come in early; a weighbridge you only
   * care about once it is close enough to matter. Without that the wide views turn into
   * a field of chips with no map under them.
   */
  const PLACES = {
    parking:  { colour: '--poi-rest', from: 0.09, text: 'P' },
    sleep:    { colour: '--poi-rest', from: 0.09,
                d: 'M3.4 17.6V8m0 4.2h11.2a4 4 0 0 1 4 4v1.4M6.6 12.2a1.8 1.8 0 1 0 0-3.6 1.8 1.8 0 0 0 0 3.6z' },
    fuel:     { colour: '--poi-fuel', from: 0.09,
                d: 'M6 20V5.2A1.6 1.6 0 0 1 7.6 3.6h3.6a1.6 1.6 0 0 1 1.6 1.6V20M4.6 20h10M7.6 7h4v2.8h-4z'
                 + 'M13.2 10h2.4a1.4 1.4 0 0 1 1.4 1.4v4.8a1.2 1.2 0 0 0 2.4 0V10.6l-2-2.2' },
    service:  { colour: '--poi-fix', from: 0.09,
                d: 'M15.4 4.6a4.6 4.6 0 0 0-6 6l-5 5a1.8 1.8 0 0 0 2.6 2.6l5-5a4.6 4.6 0 0 0 6-6l-2.6 2.6-2.2-2.2z' },
    garage:   { colour: '--poi-fix', from: 0.09,
                d: 'M3.4 20V9.4L12 4l8.6 5.4V20zM7.6 20v-6h8.8v6' },
    dealer:   { colour: '--poi-misc', from: 0.2,
                d: 'M2.8 16.4V7.6h9.6v8.8M12.4 10.4h3.4l2.8 3v3H12.4M6 18.6a1.6 1.6 0 1 0 0-3.2 1.6 1.6 0 0 0 0 3.2z'
                 + 'M15.6 18.6a1.6 1.6 0 1 0 0-3.2 1.6 1.6 0 0 0 0 3.2z' },
    weigh:    { colour: '--poi-misc', from: 0.2,
                d: 'M12 4.4v15.2M6.4 19.6h11.2M4 9.2h16M8 9.2l-3.4 6h6.8zM16 9.2l3.4 6h-6.8z' },
    recruit:  { colour: '--poi-misc', from: 0.2,
                d: 'M12 11.2a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM5 20.2c0-3.9 3.1-6.2 7-6.2s7 2.3 7 6.2' },
    border:   { colour: '--poi-misc', from: 0.2, d: 'M5.4 3.2v17.6M5.4 4.8h11l-2.6 3.2 2.6 3.2h-11' },
    viewpoint:{ colour: '--poi-misc', from: 0.45,
                d: 'M2.8 8.4h4.2l1.9-2.6h6.6l1.9 2.6h4.2v10.8H2.8zM12 10.4a3.4 3.4 0 1 0 0 6.8 3.4 3.4 0 0 0 0-6.8z' },
    company:  { colour: '--poi-company', from: 0.45, label: 1.0,
                d: 'M3.6 20V11l5-3v3l5-3v3l5-3v12z' },
  };
  // Listed most useful first, and that order is the tie-break when two chips want the
  // same patch of screen: a services area carries a pump, a bed and a spanner within a
  // few metres of each other, and at this size only one of them can be drawn.
  Object.keys(PLACES).forEach((kind, rank) => {
    const place = PLACES[kind];
    place.rank = rank;
    if (place.d) place.path = new Path2D(place.d);
  });

  function rebuildBuffer(world, scale) {
    const size = bufSize;
    const half = size / 2 / scale;
    const cells = MapData.inBox(world.x - half, world.z - half, world.x + half, world.z + half);

    bctx.setTransform(1, 0, 0, 1, 0, 0);
    bctx.clearRect(0, 0, size, size);
    bctx.setTransform(scale, 0, 0, scale, size / 2 - world.x * scale, size / 2 - world.z * scale);
    bctx.lineCap = 'round';
    bctx.lineJoin = 'round';

    const detail = scale >= 0.08;           // company yards and side roads clutter a wide view
    const pen = 1 / scale;                  // one device pixel, in world units

    if (detail) {
      bctx.fillStyle = cssVar('--map-area');
      bctx.beginPath();
      for (const cell of cells) {
        for (const ring of cell.a || []) {
          bctx.moveTo(ring[0], ring[1]);
          for (let i = 2; i < ring.length; i += 2) bctx.lineTo(ring[i], ring[i + 1]);
          bctx.closePath();
        }
      }
      bctx.fill();
    }

    bctx.strokeStyle = cssVar('--map-ferry');
    bctx.lineWidth = Math.max(2 * pen, 30);
    bctx.setLineDash([90, 70]);
    bctx.beginPath();
    for (const cell of cells) {
      for (const line of cell.f || []) {
        bctx.moveTo(line[0], line[1]);
        for (let i = 2; i < line.length; i += 2) bctx.lineTo(line[i], line[i + 1]);
      }
    }
    bctx.stroke();
    bctx.setLineDash([]);

    // Three weights: motorways read first, lanes last. Each is one path, because a
    // stroke per segment would cost more than the geometry itself.
    const LANES = [
      { min: 15, colour: '--map-major', floor: 3.0 },
      { min: 8, colour: '--map-road', floor: 2.2 },
      { min: 0, colour: '--map-minor', floor: 1.6 },
    ];
    for (let band = 0; band < LANES.length; band++) {
      const lane = LANES[band];
      if (band === 2 && !detail) continue;
      const max = band === 0 ? Infinity : LANES[band - 1].min;
      bctx.strokeStyle = cssVar(lane.colour);
      bctx.lineWidth = Math.max(lane.floor * pen, 6);
      bctx.beginPath();
      let drew = false;
      for (const cell of cells) {
        for (const road of cell.r) {
          const width = road[0];
          if (width < lane.min || width >= max) continue;
          bctx.moveTo(road[2], road[3]);
          for (let i = 4; i < road.length; i += 2) bctx.lineTo(road[i], road[i + 1]);
          drew = true;
        }
      }
      if (drew) bctx.stroke();
    }

    bufCities = [];
    bufPlaces = [];
    for (const cell of cells) {
      for (const city of cell.c || []) bufCities.push(city);
      for (const place of cell.p || []) bufPlaces.push(place);
    }
    bufPlaces.sort((a, b) => ((PLACES[a[2]] || {}).rank ?? 99) - ((PLACES[b[2]] || {}).rank ?? 99));
    lastCellCount = cells.length;
    lastRoadCount = cells.reduce((n, c) => n + c.r.length, 0);

    bufAnchor = [world.x, world.z];
    bufScale = scale;
    bufRevision = MapData.revision;
    bufAt = Date.now();
  }

  /* Chips stay upright while the map turns, the same way city names do -- an icon
     rotated with the heading is a puzzle rather than a sign. */
  function drawPlaces(w, h, view, scale, bearing) {
    const cos = Math.cos(-bearing), sin = Math.sin(-bearing);
    const r = Math.max(9, Math.min(w, h) * 0.028);
    const left = -w / 2 - r, right = w / 2 + r, top = -h * 0.62 - r, bottom = h * 0.38 + r;

    // One chip per square of screen, whatever kind. bufPlaces is already in priority
    // order, so the pump wins the square over the viewpoint next door rather than the
    // two of them overlapping into an unreadable smudge.
    const step = r * 1.9;
    const taken = new Set();

    mctx.save();
    mctx.translate(w / 2, h * 0.62);
    mctx.lineJoin = 'round';
    mctx.lineCap = 'round';
    mctx.textAlign = 'center';

    const ground = cssVar('--map-ground');
    const labels = [];

    for (const place of bufPlaces) {
      const kind = PLACES[place[2]];
      if (!kind || scale < kind.from) continue;

      const dx = (place[0] - view.x) * scale, dz = (place[1] - view.z) * scale;
      const sx = dx * cos - dz * sin, sy = dx * sin + dz * cos;
      if (sx < left || sx > right || sy < top || sy > bottom) continue;

      const slot = `${Math.round(sx / step)},${Math.round(sy / step)}`;
      if (taken.has(slot)) continue;
      taken.add(slot);

      mctx.fillStyle = cssVar(kind.colour);
      mctx.beginPath();
      mctx.arc(sx, sy, r, 0, Math.PI * 2);
      mctx.fill();

      mctx.save();
      mctx.translate(sx, sy);
      if (kind.text) {
        mctx.fillStyle = ground;
        mctx.font = `800 ${Math.round(r * 1.5)}px system-ui, sans-serif`;
        mctx.textBaseline = 'middle';
        mctx.fillText(kind.text, 0, r * 0.06);
      } else {
        const unit = (r * 1.34) / 24;   // the glyphs are drawn in a 24-wide box
        mctx.scale(unit, unit);
        mctx.translate(-12, -12);
        mctx.strokeStyle = ground;
        mctx.lineWidth = 2.4;
        mctx.stroke(kind.path);
      }
      mctx.restore();

      if (kind.label && scale >= kind.label && place[3]) labels.push([sx, sy + r * 2.1, place[3]]);
    }

    // Names go on after every chip, so a neighbouring chip cannot land on top of one.
    if (labels.length) {
      mctx.font = `600 ${Math.round(r * 1.05)}px system-ui, sans-serif`;
      mctx.textBaseline = 'top';
      mctx.lineWidth = 3.5;
      mctx.strokeStyle = ground;
      mctx.fillStyle = cssVar('--poi-company');
      for (const [x, y, name] of labels) {
        mctx.strokeText(name, x, y);
        mctx.fillText(name, x, y);
      }
    }

    mctx.restore();
  }

  function drawMap(world) {
    const w = mapCv.width, h = mapCv.height;
    if (!w || !h) return;
    mctx.setTransform(1, 0, 0, 1, 0, 0);
    mctx.fillStyle = cssVar('--map-ground');
    mctx.fillRect(0, 0, w, h);
    if (!world) return;

    const bearing = ((1 - (world.heading || 0)) % 1) * Math.PI * 2;
    const scale = zoom;
    const haveRoads = MapData.state === 'ready';
    lastBearing = bearing;
    easePan();
    // What the window is centred on. Without a drag this is the truck exactly.
    const view = { x: world.x + pan.x, z: world.z + pan.z };
    recentre.classList.toggle('show', panned());

    if (haveRoads) {
      const want = Math.ceil(Math.hypot(w, h)) + MARGIN * 2;
      if (buf.width !== want) { buf.width = buf.height = want; bufSize = want; bufAnchor = null; }
      const moved = bufAnchor
        ? Math.hypot(view.x - bufAnchor[0], view.z - bufAnchor[1]) * scale
        : Infinity;
      const stale = MapData.revision !== bufRevision && Date.now() - bufAt > 300;
      // Mid-pinch the buffer is stretched rather than redrawn: rebuilding tens of
      // thousands of segments on every frame of a gesture turns it into a slideshow.
      // Stretching costs a blit, and the drawing is exact again the moment the fingers
      // lift. It is redrawn part-way through anyway once the stretch gets far enough to
      // show as blur or as bare ground creeping in at the edges.
      const ratio = bufScale ? scale / bufScale : 0;
      const overstretched = ratio < 0.8 || ratio > 1.7;
      if (!bufAnchor || overstretched ||
          (!pinching && (bufScale !== scale || moved > MARGIN - 24 || stale))) {
        rebuildBuffer(view, scale);
      }
    }

    mctx.save();
    mctx.translate(w / 2, h * 0.62);
    mctx.rotate(-bearing);

    if (haveRoads) {
      const span = bufSize * (scale / bufScale);
      mctx.drawImage(buf,
        (bufAnchor[0] - view.x) * scale - span / 2,
        (bufAnchor[1] - view.z) * scale - span / 2,
        span, span);
    }

    mctx.scale(scale, scale);
    mctx.translate(-view.x, -view.z);

    if (!haveRoads) {
      // No exported map: fall back to a kilometre grid, so movement still reads.
      const step = 1000, span = Math.max(w, h) / scale;
      const x0 = Math.floor((view.x - span) / step) * step;
      const z0 = Math.floor((view.z - span) / step) * step;
      mctx.strokeStyle = cssVar('--line');
      mctx.lineWidth = 1.5 / scale;
      mctx.beginPath();
      for (let x = x0; x < view.x + span; x += step) { mctx.moveTo(x, z0); mctx.lineTo(x, z0 + 2 * span + step); }
      for (let z = z0; z < view.z + span; z += step) { mctx.moveTo(x0, z); mctx.lineTo(x0 + 2 * span + step, z); }
      mctx.stroke();
    }

    mctx.restore();

    // City names ride on top and stay upright -- a rotated label is unreadable at a glance.
    if (haveRoads && bufCities.length && scale >= 0.05) {
      const cos = Math.cos(-bearing), sin = Math.sin(-bearing);
      mctx.save();
      mctx.translate(w / 2, h * 0.62);
      mctx.font = `600 ${Math.round(h * 0.052)}px system-ui, sans-serif`;
      mctx.textAlign = 'center';
      mctx.lineWidth = 4;
      mctx.strokeStyle = cssVar('--map-ground');
      mctx.fillStyle = cssVar('--map-city');
      for (const city of bufCities) {
        const dx = (city[0] - view.x) * scale, dz = (city[1] - view.z) * scale;
        const sx = dx * cos - dz * sin, sy = dx * sin + dz * cos;
        if (sx < -w / 2 || sx > w / 2 || sy < -h * 0.62 || sy > h * 0.38) continue;
        mctx.strokeText(city[2], sx, sy);
        mctx.fillText(city[2], sx, sy);
      }
      mctx.restore();
    }

    // After the city names, not before: a fuel stop hidden under a word is a fuel stop
    // missed, and the names carry a halo that keeps them readable underneath.
    if (haveRoads && bufPlaces.length) drawPlaces(w, h, view, scale, bearing);

    mctx.save();
    // The truck sits where it really is. Dragging moves the window, not the lorry.
    const tdx = (world.x - view.x) * scale, tdz = (world.z - view.z) * scale;
    const tcos = Math.cos(-bearing), tsin = Math.sin(-bearing);
    mctx.translate(w / 2 + tdx * tcos - tdz * tsin, h * 0.62 + tdx * tsin + tdz * tcos);
    mctx.fillStyle = cssVar('--text');
    mctx.strokeStyle = cssVar('--ground');
    mctx.lineWidth = 4;
    const s = Math.min(w, h) * 0.05;
    mctx.beginPath();
    mctx.moveTo(0, -s * 1.5); mctx.lineTo(s, s); mctx.lineTo(0, s * 0.42); mctx.lineTo(-s, s);
    mctx.closePath(); mctx.fill(); mctx.stroke();
    mctx.restore();

    const barMetres = (4.5 * parseFloat(getComputedStyle(deck).getPropertyValue('--u')) * 2) / scale;
    $('#scaleTxt').textContent = barMetres >= 1000
      ? `${distKm(barMetres / 1000).toFixed(1)} ${distUnit()}`
      : `${Math.round(imperial() ? barMetres * 3.28084 : barMetres)} ${imperial() ? 'ft' : 'm'}`;

    const deg = ((1 - (world.heading || 0)) * 360) % 360;
    $('#headingV').textContent = `${COMPASS[Math.round(deg / 45) % 8]} ${Math.round(deg)}°`;
    $('#coordTxt').textContent = `${Math.round(world.x)} , ${Math.round(world.z)}`;
    if (location.search.includes('debug')) {
      $('#coordTxt').textContent =
        `${MapData.state} rev${MapData.revision} q${MapData.loading} buf${bufSize} ` +
        `cells${lastCellCount} roads${lastRoadCount} sc${scale}`;
    }
  }

  /* ── render ────────────────────────────────────────────────────────────── */
  function onTelemetry(msg) {
    lastFrame = Date.now();
    units = msg.units || 'metric';
    currency = msg.currency || 'EUR';
    unitChip.textContent = `${imperial() ? 'MI' : 'KM'} · ${SYMBOL[currency] || currency}`;
    // In a menu the telemetry says "unknown"; the running process still says which game.
    const game = msg.game && msg.game !== 'unknown' ? msg.game : msg.running;
    $('#game').textContent = game || '—';
    if (game) MapData.setGame(game);

    // The exported map cannot notice on its own that ProMods has been updated or a DLC
    // bought; the server compares what the export was made from against what is there
    // now and says so. Once per game, not every frame -- it is a job for later, not an
    // alarm, and a driver being told the same thing at 20 Hz stops reading any of it.
    if (msg.map_warning && mapWarned !== game) {
      mapWarned = game;
      notice(msg.map_warning, 9000);
    }

    gameOnline = !!msg.online;
    if (!gameOnline) {
      resolvePending();   // before the return, or a button pressed in a menu sticks
      if (msg.error) setLink('stale', 'PLUGIN ERROR', 'check the PC');
      else if (msg.running) setLink('stale', 'IN MENU', 'buttons still work');
      else setLink('stale', 'NO GAME', 'start ETS2 / ATS');
      return;
    }
    setLink('live', msg.paused ? 'PAUSED' : 'LIVE', latency == null ? '' : `${latency} ms`);

    const d = msg.data || {};
    latest = d;
    resolvePending();

    /* cluster */
    const maxSpeed = imperial() ? 90 : 140;
    const shown = speedVal(d.speed_ms || 0);
    $('#kph').textContent = shown;
    $('#speedUnit').textContent = speedUnit();
    arcFg.style.strokeDashoffset = ARC * (1 - Math.min(shown, maxSpeed) / maxSpeed);

    const limit = speedVal(d.speed_limit_ms || 0);
    $('#limit').textContent = limit > 0 ? limit : '—';
    $('#limit').classList.toggle('none', !(limit > 0));
    arcLim.style.strokeDashoffset = -ARC * (Math.min(limit, maxSpeed) / maxSpeed);
    arcLim.style.opacity = limit > 0 ? 0.55 : 0;

    const rpmMax = d.rpm_max || 2500;
    const lit = Math.round(((d.rpm || 0) / rpmMax) * RPM_SEGS);
    rpmEl.querySelectorAll('i').forEach((s, i) => s.classList.toggle('on', i < lit));

    const gear = d.gear_dash || d.gear || 0;
    $('#gearVal').textContent = gear === 0 ? 'N' : gear < 0 ? `R${gear < -1 ? -gear : ''}` : gear;

    const ccOn = !!d.cruise_on;
    $('#ccBox').classList.toggle('on', ccOn);
    $('#ccVal').textContent = ccOn ? speedVal(d.cruise_speed_ms || 0) : '—';

    const lights = d.lights || {};
    $('#tL').classList.toggle('on', !!lights.blinker_left);
    $('#tR').classList.toggle('on', !!lights.blinker_right);
    $('#tH').classList.toggle('on', !!lights.high);
    $('#tB').classList.toggle('on', !!lights.beacon);
    $('#tP').classList.toggle('on', !!d.park_brake);
    $('#tW').classList.toggle('on', !!d.fuel_warn);

    /* control states straight from the game */
    setToggle('lights_low', lights.beam > 0);   // parking or low: the switch is not at off
    setToggle('high_beam', lights.high);
    setToggle('beacon', lights.beacon);
    setToggle('hazard', lights.hazard);
    setToggle('wipers', d.wipers);
    setToggle('park_brake', d.park_brake);
    setToggle('diff_lock', d.diff_lock);
    setToggle('motor_brake', d.motor_brake);
    setToggle('engine', d.engine);
    setToggle('cruise_set', d.cruise_on);

    /* vitals */
    const cap = d.fuel_capacity_l || 1;
    const fuelPct = Math.max(0, Math.min(100, (d.fuel_l || 0) / cap * 100));
    $('#fuelLbl').textContent = msg.game === 'ATS' ? 'Fuel' : 'Diesel';
    $('#fuelV').innerHTML = `${volume(d.fuel_l || 0).toFixed(0)} ${volumeUnit()} <em>· ${distKm(d.fuel_range_km || 0).toFixed(0)} ${distUnit()}</em>`;
    setBar('#fuelB', fuelPct, fuelPct < 12 ? 'bad' : fuelPct < 25 ? 'warn' : 'ok');


    const airPct = Math.max(0, Math.min(100, (d.air_psi || 0) / 145 * 100));
    $('#airV').textContent = `${pressure(d.air_psi || 0).toFixed(imperial() ? 0 : 1)} ${pressureUnit()}`;
    setBar('#airB', airPct, d.air_emergency ? 'bad' : d.air_warn ? 'warn' : 'ok');

    $('#tmpV').innerHTML = `${temp(d.water_temp_c || 0).toFixed(0)} ${tempUnit()} <em>· ${temp(d.oil_temp_c || 0).toFixed(0)} ${tempUnit()}</em>`;
    const tmpPct = Math.max(0, Math.min(100, (d.water_temp_c || 0) / 120 * 100));
    setBar('#tmpB', tmpPct, d.water_warn ? 'bad' : 'ok');

    const wear = d.wear || {};
    DAMAGE_ROWS.forEach(([, key]) => {
      const pct = Math.max(0, Math.min(100, (wear[key] || 0) * 100));
      const bar = dmgBars[key];
      bar.fill.style.width = pct + '%';
      bar.fill.className = 'fill ' + (pct >= 25 ? 'bad' : pct >= 10 ? 'warn' : 'ok');
      bar.text.textContent = pct.toFixed(0) + '%';
    });

    $('#odoV').textContent = `${Math.round(distKm(d.odometer_km || 0)).toLocaleString('en-US').replace(/,/g, ' ')} ${distUnit()}`;

    /* clock and rest */
    const nowMin = d.time_abs || 0;
    $('#clock').textContent = hhmm(nowMin);
    const rest = Math.max(0, d.rest_stop_min || 0);
    $('#rest').textContent = rest > 0 ? hmm(rest) : '—';
    $('#restBox').classList.toggle('low', rest > 0 && rest < 60);

    // Fatigue, under the damage bars: filled is worn out, the same way round as the
    // wear above it. The game reports minutes of driving left and never the length of
    // a full shift, so the full bar is the longest stretch seen this session -- eleven
    // hours until something larger turns up, which a mod may well do. And a game with
    // fatigue switched off just reports zero for ever, indistinguishable from a driver
    // who must stop now, so the bar stays out of it until a positive figure has been
    // seen at least once.
    if (rest > 0) { restSeen = true; restFull = Math.max(restFull, rest); }
    if (!restSeen) {
      $('#restV').textContent = 'off';
      setBar('#restB', 0, 'ok');
    } else {
      $('#restV').textContent = rest > 0 ? `${hmm(rest)} left` : 'rest now';
      setBar('#restB', Math.max(0, Math.min(100, (1 - rest / restFull) * 100)),
             rest < 45 ? 'bad' : rest < 120 ? 'warn' : 'ok');
    }

    /* job and navigation */
    const job = d.job || {};
    const hasJob = !!job.on_job;
    $('#cargoV').textContent = hasJob
      ? `${job.cargo || '—'} · ${mass(job.cargo_mass_kg || 0).toFixed(1)} ${massUnit()} · ${money(job.income || 0)}`
      : 'No active job';
    $('#dstV').textContent = hasJob ? `${job.city_dst || '—'}${job.comp_dst ? ' · ' + job.comp_dst : ''}` : '—';

    const remainingKm = (job.route_distance_m || 0) / 1000;
    $('#distV').textContent = hasJob ? `${distKm(remainingKm).toFixed(0)} ${distUnit()}` : '—';

    const etaMin = nowMin + (job.route_time_s || 0) / 60;
    $('#etaV').textContent = hasJob && job.route_time_s > 0 ? hhmm(etaMin) : '—';

    const deadline = job.delivery_time_abs || 0;
    if (hasJob && deadline > 0) {
      const days = Math.floor(deadline / 1440) - Math.floor(nowMin / 1440);
      $('#deadlineV').textContent = hhmm(deadline) + (days > 0 ? ` +${days}d` : '');
      const slack = (deadline - nowMin) - (job.route_time_s || 0) / 60;
      const late = slack < 0;
      $('#slackV').textContent = `${late ? '−' : '+'}${hmm(Math.abs(slack))}`;
      $('#slackBox').className = 'item ' + (late ? 'late' : 'good');
      $('#etaBox').className = 'item ' + (late ? 'late' : 'good');
    } else {
      $('#deadlineV').textContent = '—';
      $('#slackV').textContent = '—';
      $('#slackBox').className = 'item';
      $('#etaBox').className = 'item';
    }

    /* map */
    const world = d.world;
    if (world) drawMap(world);
  }

  function setBar(sel, pct, cls) {
    const el = $(sel);
    el.style.width = pct + '%';
    el.className = 'fill ' + cls;
  }

  function setToggle(cmd, on) {
    const el = document.querySelector(`[data-cmd="${cmd}"]`);
    if (el && !el.classList.contains('pending')) el.classList.toggle('on', !!on);
  }

  /* ── watchdog: a silent socket is worse than a closed one ──────────────── */
  setInterval(() => {
    if (!ws || ws.readyState !== 1) return;
    const age = Date.now() - lastFrame;
    // Frames arrive whether or not a game is running, so silence means the socket,
    // not the game -- worth saying even while the panel is showing IN MENU.
    if (age > 2000) setLink('stale', 'STALE', `no data ${Math.round(age / 1000)} s`);
    // An open socket that has gone quiet never heals itself: the tablet still calls it
    // OPEN, so nothing here would ever retry. Close it and let the retry ladder run.
    if (age > 5000) { try { ws.close(); } catch (err) { /* already going */ } }
  }, 500);

  /* ── boot ──────────────────────────────────────────────────────────────── */
  fit();
  drawMap(null);
  connect();
  if ('wakeLock' in navigator) {
    const hold = () => navigator.wakeLock.request('screen').catch(() => {});
    hold();
    document.addEventListener('visibilitychange', () => document.visibilityState === 'visible' && hold());
  }
  if ('serviceWorker' in navigator && !location.search.includes('nosw')) {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  }
})();
