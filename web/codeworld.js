/* SeedVille Workshops: plays back CodeWorld replays recorded by the engine
   (worldseeds/codeworld/replay.py), so the picture is always what the engine did.

   The town is several maps joined at their edges (worldseeds/codeworld/townmap.py): in every district a
   town with a farm to the west, the mountain to the north and the beach to the south. Workshops are rooms
   without a roof, their machines along the walls. Apprentices walk the engine's shortest routes, from map
   to map, to study a machine, to ask a master, and deliver orders. */
"use strict";

const A = "assets/";
const GW = 1280, GH = 800;            // canvas size
const TW = 32, TH = 16;               // isometric tile
const AREA_DX = 620, AREA_DY = 380;   // spacing of maps in the world (by their place on the minimap)
const DIRS = ["down", "left", "right", "up"];
const COLORS = { red: "#c8463a", blue: "#3f6fc4", green: "#3d8a3a", yellow: "#c9a227", purple: "#8a4fb0", orange: "#d8782e" };
const KIND_COLOR = { bakery: "#e0823a", smithy: "#59606e", florist: "#e86a8a", mine: "#8a5a32", clinic: "#3f7fd0",
                     inn: "#a0402a", shop: "#3f6fc4", farm: "#c8463a" };
const KIND_TITLE = { bakery: "Bakery", smithy: "Smithy", florist: "Florist", mine: "Mine", clinic: "Clinic", inn: "Inn",
                     shop: "Shop", farm: "Farm" };
const THEME_BG = { town: "#4f9a3a", farm: "#5aa040", beach: "#3f8ed8", mountain: "#6a8a48" };
const TOP = 1e5;                      // depth of labels and speech above the maps
const NAMES = ["Rosa", "Tomas", "Ivy", "Bram", "Lena", "Otto", "Mira", "Finn", "Hana", "Leo", "Clara", "Abe"];
const ALL_LOOKS = NAMES.flatMap(n => Object.keys(COLORS).map(c => `${n}_${c}`));
const WALK_PX = 70;                   // townsfolk walking speed, pixels per second

const $ = id => document.getElementById(id);
const cap = s => s.charAt(0).toUpperCase() + s.slice(1);

/* ===================================================================== state */
const S = {
  runs: [], run: null, sprint: 0, pos: 0, playing: false, speed: 3, timer: null, scene: null,
  follow: true, followDev: null, view: null,
  // reconstructed from the replay up to `pos`
  books: {}, budget: {}, loc: {}, orders: {}, active: {}, tally: null, fresh: {}, gone: {},
};

function devOf(name) { return S.run.devs.find(d => d.name === name); }
function nick(name) { const d = devOf(name); return d ? d.look[0] : name; }
function colorOf(name) { const d = devOf(name); return d ? COLORS[d.look[1]] : "#777"; }
function workshop(module) {
  for (const d of S.run.world.districts) for (const w of d.workshops) if (w.module === module) return { d, w };
  return null;
}
const BUILDING_TITLE = { library: "library", post: "post office", board: "notice board" };
function placeTitle(module) {
  if (!module) return "the plaza";
  if (module.includes(":")) {
    const [kind, d] = module.split(":");
    return (S.run.world.districts.length > 1 ? cap(S.run.world.districts[+d].name) + " " : "the ") + BUILDING_TITLE[kind];
  }
  const ws = workshop(module); if (!ws) return module;
  const t = KIND_TITLE[ws.w.kind] || cap(ws.w.kind);
  return S.run.world.districts.length > 1 ? `${cap(ws.d.name)} ${t}` : `the ${t.toLowerCase()}`;
}
function owner(module) {
  if (S.run.mode.startsWith("solo")) return null;
  const d = S.run.devs.find(d => d.owns.includes(module)); return d ? d.name : null; }
function moduleOf(fn) { return fn.split(".")[0]; }
function verbOf(fn) { return fn.split(".")[1]; }

/* ===================================================================== geometry */
function worldMap() { return S.run.world.map; }
function areaOf(name) { return worldMap().areas.find(a => a.name === name); }
function areaTitle(a) { return (S.run.world.districts.length > 1 ? cap(S.run.world.districts[a.district].name) + " " : "") + a.title; }
/* the maps lie in one world grid (their offsets come from the engine), touching at their exits */
function bounds() {
  if (S.B && S.B.run === S.run) return S.B;
  const m = worldMap(), xs = m.areas.map(a => a.offset[0]), ys = m.areas.map(a => a.offset[1]);
  S.B = { run: S.run, x0: Math.min(...xs) - 3, y0: Math.min(...ys) - 3,
          x1: Math.max(...xs) + m.W + 2, y1: Math.max(...ys) + m.H + 2 };
  return S.B;
}
/* top vertex of world tile (X, Y) in pixels */
function isoG(X, Y) {
  const b = bounds();
  return { x: (b.y1 - b.y0 + 1 + (X - b.x0) - (Y - b.y0)) * TW / 2, y: 60 + ((X - b.x0) + (Y - b.y0)) * TH / 2 };
}
/* top vertex of tile (gx, gy) of an area; a tile's centre is 8 px lower */
function iso(area, gx, gy) {
  const a = typeof area === "string" ? areaOf(area) : area;
  return isoG(gx + a.offset[0], gy + a.offset[1]);
}
function centre(area, gx, gy) { const p = iso(area, gx, gy); return { x: p.x, y: p.y + TH / 2 }; }
/* where an apprentice stands at a place: a free floor tile of the workshop, spread by apprentice */
function placeSpot(module, name) {
  const k = S.run.devs.findIndex(d => d.name === name);
  if (!module) {
    const p = worldMap().plaza, c = centre(p.area, p.x, p.y);
    return { area: p.area, x: c.x + ((k % 4) - 1.5) * 7, y: c.y + Math.floor(k / 4) * 4 };
  }
  if (module.includes(":")) {  // a town building: "library:0", "post:1", "board:0"
    const [kind, d] = module.split(":");
    const a = worldMap().areas.find(x => x.theme === "town" && x.district === +d), t = a.places[kind];
    const c = centre(a, t[0], t[1]);
    return { area: a.name, x: c.x + ((k % 4) - 1.5) * 6, y: c.y + Math.floor(k / 4) * 3 };
  }
  const { w } = workshop(module), r = w.room;
  const free = [];
  for (let y = r.y + 2; y <= r.y + 3; y++) for (let x = r.x + 2; x <= r.x + 4; x++) free.push([x, y]);
  const [gx, gy] = free[k % free.length], c = centre(w.area, gx, gy);
  const j = Math.floor(k / free.length);
  return { area: w.area, x: c.x + j * 4, y: c.y + j * 2 };
}

/* shortest way between two outdoor tiles of one map (for the townsfolk) */
function areaPath(a, from, to) {
  const key = (x, y) => x * 100 + y, ok = (x, y) => y >= 0 && y < a.grid.length && x >= 0 && x < a.grid[0].length && "=pb.".includes(a.grid[y][x]);
  const prev = new Map([[key(...from), null]]), q = [from];
  while (q.length) {
    const [x, y] = q.shift();
    if (x === to[0] && y === to[1]) break;
    for (const [nx, ny] of [[x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]])
      if (ok(nx, ny) && !prev.has(key(nx, ny))) { prev.set(key(nx, ny), [x, y]); q.push([nx, ny]); }
  }
  if (!prev.has(key(...to))) return [from];
  const out = []; let c = to;
  while (c) { out.push(c); c = prev.get(key(...c)); }
  return out.reverse();
}

/* ===================================================================== Phaser */
class Boot extends Phaser.Scene {
  constructor() { super("boot"); }
  preload() {
    const bar = this.add.rectangle(GW / 2 - 150, GH / 2, 0, 10, 0xf2b632).setOrigin(0, .5);
    this.add.rectangle(GW / 2, GH / 2, 304, 14).setStrokeStyle(2, 0x7a4a26);
    this.load.on("progress", p => bar.width = 300 * p);
    this.load.atlas("k", `${A}kairo.png`, `${A}kairo.json`);
    this.load.atlas("ui", `${A}ui.png`, `${A}ui.json`);
    for (const k of ALL_LOOKS) this.load.spritesheet(`ch_${k}`, `${A}chars/${k}.png`, { frameWidth: 16, frameHeight: 32 });
  }
  create() {
    for (const k of this.textures.getTextureKeys().filter(k => k.startsWith("ch_")))
      DIRS.forEach((dir, r) => this.anims.create({ key: `${k}_${dir}`, frameRate: 8, repeat: -1,
        frames: this.anims.generateFrameNumbers(k, { start: r * 4, end: r * 4 + 3 }) }));
    this.scene.start("town");
  }
}

class Town extends Phaser.Scene {
  constructor() { super("town"); }
  create() {
    S.scene = this;
    this.build();
    const cam = this.cameras.main;
    this.input.on("wheel", (p, o, dx, dy) => {
      const z = Phaser.Math.Clamp(cam.zoom * (dy > 0 ? .9 : 1.1), .3, 5);
      const before = cam.getWorldPoint(p.x, p.y);
      cam.setZoom(z);
      const after = cam.getWorldPoint(p.x, p.y);
      cam.scrollX += before.x - after.x; cam.scrollY += before.y - after.y;
    });
    this.input.on("pointermove", p => {
      if (!p.isDown) return;
      S.follow = false; renderMaps();
      cam.scrollX -= (p.x - p.prevPosition.x) / cam.zoom; cam.scrollY -= (p.y - p.prevPosition.y) / cam.zoom;
    });
    this.input.on("pointerdown", p => { if (p.event.detail === 2) this.overview(); });
    seek(S.pos, true);
    this.view(S.view || worldMap().plaza.area, true);
  }

  update() {  // names of the maps when zoomed out; labels of workshops when zoomed in
    const far = this.cameras.main.zoom < 1.2;
    for (const t of this.titles || []) t.setVisible(far);
  }

  build() {
    this.tweens.killAll(); this.time.removeAllEvents();
    this.children.removeAll(true);
    this.sprites = {}; this.shops = {}; this.machines = {}; this.waters = [];
    this.cameras.main.setBackgroundColor("#1f3326");
    const rnd = new Phaser.Math.RandomDataGenerator(["seedville"]);
    this.titles = [];
    this.wild(rnd);
    for (const a of worldMap().areas) this.area(a, rnd);
    this.links = this.add.graphics().setDepth(-2e4);
    this.time.addEvent({ delay: 600, loop: true, callback: () => {
      const f = (this.time.now / 600 | 0) % 2 ? "water1" : "water0";
      for (const w of this.waters) w.setFrame(f);
    } });
    for (const d of S.run.devs) this.dev(d);
    this.customers = {}; this.customerKey = null;
    this.townsfolk(rnd);
  }

  /* the land between and around the maps: woods, and the sea south of the beaches */
  /* the tiles of every forest trail (a shortcut between two maps), as world tiles */
  trailTiles() {
    const m = worldMap(), out = new Map();
    for (const a of m.areas) for (const e of a.exits) {
      if ((e.steps || 1) <= 1 || a.name > e.to) continue;
      const b = areaOf(e.to);
      const A = [a.offset[0] + e.at[0], a.offset[1] + e.at[1]], B = [b.offset[0] + e.arrive[0], b.offset[1] + e.arrive[1]];
      const dy = Math.sign(B[1] - A[1]) || 1, dx = Math.sign(B[0] - A[0]) || 1;
      for (let Y = A[1] + dy; Y !== B[1] + dy; Y += dy) out.set(`${A[0]},${Y}`, [A[0], Y]);
      for (let X = A[0]; X !== B[0]; X += dx) out.set(`${X},${B[1]}`, [X, B[1]]);
    }
    return out;
  }

  wild(rnd) {
    const m = worldMap(), b = bounds(), trails = this.trailTiles();
    const inside = (X, Y) => m.areas.some(a => X >= a.offset[0] && X < a.offset[0] + m.W && Y >= a.offset[1] && Y < a.offset[1] + m.H);
    const seaY = Math.max(...m.areas.map(a => a.offset[1])) + m.H - 4;
    for (let Y = b.y0; Y <= b.y1; Y++) for (let X = b.x0; X <= b.x1; X++) {
      if (inside(X, Y)) continue;
      const p = isoG(X, Y), sea = Y >= seaY, trail = trails.has(`${X},${Y}`);
      const img = this.add.image(p.x, p.y, "k", sea ? "water0" : trail ? "path_dirt" : "g_town").setOrigin(.5, 0).setDepth(-1e4);
      if (sea) { this.waters.push(img); continue; }
      if (trail) continue;
      if (rnd.frac() < .5) this.add.image(p.x, p.y + TH, "k", Y < 0 ? "tree_pine" : rnd.pick(["tree_round0", "tree_round1", "tree_pine"]))
        .setOrigin(.5, 1).setDepth(p.y + TH / 2);
    }
  }

  /* townsfolk strolling along the paths of every map (scenery; the apprentices carry the name tags) */
  townsfolk(rnd) {
    const used = new Set(S.run.devs.map(d => d.look.join("_")));
    const looks = ALL_LOOKS.filter(k => !used.has(k));
    this.folk = [];
    for (const a of worldMap().areas) {
      const paths = [];
      a.grid.forEach((row, y) => [...row].forEach((ch, x) => { if ("=pb".includes(ch)) paths.push([x, y]); }));
      const n = a.theme === "town" ? 4 : 2;
      for (let k = 0; k < n && paths.length; k++) {
        const key = `ch_${rnd.pick(looks)}`, start = rnd.pick(paths), c = centre(a, ...start);
        const sp = this.add.sprite(c.x, c.y, key, 0).setOrigin(.5, 1).setDepth(c.y + 2);
        const f = { sp, key, a, at: start };
        this.folk.push(f);
        const stroll = () => {
          if (!sp.active) return;
          const to = rnd.pick(paths), way = areaPath(a, f.at, to);
          f.at = to;
          if (way.length < 2) { this.time.delayedCall(800, stroll); return; }
          const pts = way.map(t => centre(a, ...t));
          let i = 0;
          const next = () => {
            if (!sp.active) return;
            if (++i >= pts.length) { sp.anims.stop(); sp.setFrame(0); this.time.delayedCall(rnd.between(800, 3500), stroll); return; }
            const p = pts[i], q = pts[i - 1], dx = p.x - q.x, dy = p.y - q.y;
            sp.play(`${key}_${dy < 0 ? (dx < 0 ? "left" : "up") : (dx < 0 ? "down" : "right")}`, true);
            this.tweens.add({ targets: sp, x: p.x, y: p.y, duration: 1000 * Math.hypot(dx, dy) / WALK_PX,
              onUpdate: () => sp.setDepth(sp.y + 2), onComplete: next });
          };
          next();
        };
        this.time.delayedCall(rnd.between(0, 3000), stroll);
      }
    }
  }

  /* the customers of this sprint's orders: they wait at the plaza and leave when served */
  syncCustomers(animate) {
    const sp = sprint(), key = `${S.runs.indexOf(S.run)}/${S.sprint}`;
    if (this.customerKey !== key) {
      for (const c of Object.values(this.customers)) c.sp.destroy();
      this.customers = {}; this.customerKey = key;
      const used = new Set(S.run.devs.map(d => d.look.join("_")));
      const looks = ALL_LOOKS.filter(k => !used.has(k));
      sp.projects.forEach((p, i) => {
        const dev = devOf(p.dev), home = dev && dev.home ? workshop(dev.home).d.index : 0;
        const town = worldMap().areas.find(a => a.theme === "town" && a.district === home);
        const slots = [];
        town.grid.forEach((row, y) => [...row].forEach((ch, x) => { if (ch === "p") slots.push([x, y]); }));
        const n = sp.projects.filter((q, j) => j < i && (devOf(q.dev).home ? workshop(devOf(q.dev).home).d.index : 0) === home).length;
        const t = slots[n % slots.length], c = centre(town, ...t), j = Math.floor(n / slots.length);
        const look = looks[(i * 7 + S.sprint * 3) % looks.length];
        const s2 = this.add.sprite(c.x + j * 5 - 4, c.y + j * 2, `ch_${look}`, 0).setOrigin(.5, 1).setDepth(c.y + 2);
        this.customers[p.id] = { sp: s2, town, left: false, key: `ch_${look}` };
      });
    }
    for (const [id, c] of Object.entries(this.customers)) {
      const st = S.orders[id].state, gone = st === "done" || st === "failed";
      if (!gone) { c.left = false; c.sp.setVisible(true).setAlpha(1); continue; }
      if (c.left) continue;
      c.left = true;
      if (!animate) { c.sp.setVisible(false); continue; }
      const e = this.add.image(c.sp.x, c.sp.y - 40, "ui", st === "done" ? "emote_heart" : "emote_bang").setDepth(TOP + 2);
      this.tweens.add({ targets: e, y: e.y - 8, alpha: 0, duration: 1200, onComplete: () => e.destroy() });
      const out = centre(c.town, 11, worldMap().H - 2);
      c.sp.play(`${c.key}_down`, true);
      this.tweens.add({ targets: c.sp, x: out.x, y: out.y, alpha: .2, duration: 1600, delay: 300,
        onUpdate: () => c.sp.setDepth(c.sp.y + 2), onComplete: () => c.sp.setVisible(false) });
    }
  }

  /* one map: ground, things standing on it, workshops, exits */
  area(a, rnd) {
    const W = worldMap().W, H = worldMap().H, theme = a.theme;
    const pathFrame = { town: "path_town", farm: "path_dirt", mountain: "path_dirt", beach: "pier" }[theme];
    const rooms = [];
    for (const d of S.run.world.districts) for (const w of d.workshops) if (w.area === a.name) rooms.push(w);
    const roomAt = (x, y) => rooms.find(w => x >= w.room.x && x < w.room.x + 6 && y >= w.room.y && y < w.room.y + 5);
    for (let gy = 0; gy < H; gy++) for (let gx = 0; gx < W; gx++) {
      const ch = a.grid[gy][gx], p = iso(a, gx, gy);
      let f = `g_${theme}`;
      if (ch === "=" || ch === "d") f = pathFrame;
      else if (ch === "p") f = "plaza";
      else if (ch === "f") f = "field";
      else if (ch === "~" || ch === "b") f = "water0";
      else if ("wim".includes(ch)) { const w = roomAt(gx, gy); f = w ? `floor_${w.kind}` : f; }
      const img = this.add.image(p.x, p.y, "k", f).setOrigin(.5, 0).setDepth(-1e4);
      if (f === "water0") this.waters.push(img);
      if (ch === "b") this.add.image(p.x, p.y, "k", "pier").setOrigin(.5, 0).setDepth(-9e3);
      const stand = fr => this.stand(a, gx, gy, fr);
      if (ch === "T") stand({ town: rnd.pick(["tree_round0", "tree_round1"]), farm: rnd.pick(["tree_round0", "tree_round1"]),
        mountain: "tree_pine", beach: "tree_palm" }[theme]);
      else if (ch === "^") stand(theme === "mountain" ? "rock_big" : "rock");
      else if (ch === "h") stand(`house${rnd.between(0, 2)}`);
      else if (ch === "F") stand("fountain");
      else if (ch === "o") stand(rnd.pick({ town: ["lamp", "bush_flower", "bush"], farm: ["crate", "barrel", "bush"],
        beach: ["umbrella", "crate", "rock"], mountain: ["rock", "bush"] }[theme]));
    }
    for (const w of rooms) this.room(a, w);
    for (const bd of a.buildings || []) this.building(a, bd);
    // the map's name, shown when zoomed out (the maps touch, so the roads themselves are the exits)
    const c = centre(a, W / 2, H / 2);
    const title = this.add.text(c.x, c.y, areaTitle(a), { fontFamily: "Pixelify Sans", fontSize: "28px", color: "#fff6df",
      backgroundColor: THEME_BG[theme], padding: { x: 10, y: 3 } }).setOrigin(.5).setResolution(2).setDepth(TOP + 10).setAlpha(.85);
    (this.titles = this.titles || []).push(title);
  }

  /* a town building (library, post office, notice board) */
  building(a, bd) {
    if (bd.kind === "board") { this.stand(a, bd.x, bd.y, "b_board"); return; }
    const f = this.textures.getFrame("k", `b_${bd.kind}`), p = iso(a, bd.x, bd.y), n = bd.w + bd.h;
    const img = this.add.image(p.x, p.y, "k", `b_${bd.kind}`)
      .setOrigin(bd.h / n, (f.height - n * TH / 2) / f.height).setDepth(iso(a, bd.x + bd.w / 2, bd.y + bd.h / 2).y + TH / 2);
    const top = iso(a, bd.x + bd.w / 2, bd.y);
    this.add.text(top.x, top.y - 30, { library: "Library", post: "Post office" }[bd.kind], { fontFamily: "Pixelify Sans",
      fontSize: "10px", color: "#fff6df", backgroundColor: "#4a2a14", padding: { x: 4, y: 1 } })
      .setOrigin(.5, 1).setResolution(4).setDepth(TOP);
    return img;
  }

  /* something standing on tile (gx, gy): its tile diamond is the bottom 16 rows of the frame */
  stand(a, gx, gy, frame, dz = 0) {
    const p = iso(a, gx, gy);
    return this.add.image(p.x, p.y + TH, "k", frame).setOrigin(.5, 1).setDepth(p.y + TH / 2 + dz);
  }

  room(a, w) {
    const r = w.room, k = w.kind;
    for (let i = 0; i < 6; i++) {           // back wall along x, a window every other tile
      this.stand(a, r.x + i, r.y, (i % 2 ? `wall_xw_${k}` : `wall_x_${k}`), -6);
      if (r.x + i !== r.door[0]) this.stand(a, r.x + i, r.y + 4, `low_x_${k}`, 6);  // the front, but its door
    }
    for (let j = 0; j < 5; j++) {           // back wall along y, and the low wall on the right
      this.stand(a, r.x, r.y + j, (j % 2 ? `wall_yw_${k}` : `wall_y_${k}`), -5);
      this.stand(a, r.x + 5, r.y + j, `low_y_${k}`, 6);
    }
    w.machines.forEach((m, i) => {
      const img = this.stand(a, m.tile[0], m.tile[1], m.look ? `mc_${m.look}` : `m_${k}_${i % 2}`);
      const bulb = this.add.circle(img.x, img.y - 24, 3, 0xffd24a).setStrokeStyle(1, 0x26160e).setDepth(TOP - 3).setVisible(false);
      img.setInteractive({ useHandCursor: true, pixelPerfect: true })
        .on("pointerover", () => toast(machineText(w, m))).on("pointerout", () => toast(null));
      this.machines[m.name] = { img, bulb };
    });
    const own = owner(w.module), top = iso(a, r.x + 3, r.y);
    const label = this.add.text(top.x, top.y - 22, `${KIND_TITLE[k]}${own ? " · " + nick(own) : ""}`, {
      fontFamily: "Pixelify Sans", fontSize: "10px", color: "#fff6df", backgroundColor: own ? colorOf(own) : KIND_COLOR[k],
      padding: { x: 4, y: 1 } }).setOrigin(.5, 1).setResolution(4).setDepth(TOP);
    this.shops[w.module] = { label, area: a.name };
  }

  dev(d) {
    const key = `ch_${d.look.join("_")}`;
    const p = placeSpot(d.home, d.name);
    const sh = this.add.ellipse(p.x, p.y, 12, 5, 0x000000, .3);
    const sp = this.add.sprite(p.x, p.y, key, 0).setOrigin(.5, 1);
    const tag = this.add.text(p.x, p.y - 33, d.look[0], { fontFamily: "Pixelify Sans", fontSize: "8px", color: "#fff6df",
      backgroundColor: COLORS[d.look[1]], padding: { x: 2, y: 0 } }).setOrigin(.5, 1).setResolution(4);
    this.sprites[d.name] = { sp, sh, tag, key, tween: null, area: p.area };
    this.put(d.name, p);
  }

  put(name, p) {
    const s = this.sprites[name];
    if (p.area) s.area = p.area;
    s.sp.setPosition(p.x, p.y).setDepth(p.y + 2);
    s.sh.setPosition(p.x, p.y - 1).setDepth(p.y + 1);
    s.tag.setPosition(p.x, p.y - 33).setDepth(TOP + 1);
  }

  /* the camera on one map (like walking into it), or on all of them */
  view(areaName, instant) {
    const a = areaOf(areaName); if (!a) return;
    S.view = areaName;
    const W = worldMap().W, H = worldMap().H, cam = this.cameras.main;
    const l = iso(a, 0, H).x - 8, r = iso(a, W, 0).x + 8, t = iso(a, 0, 0).y - 50, b = iso(a, W, H).y + 10;
    const z = Math.min(GW / (r - l), GH / (b - t));
    const cx = (l + r) / 2, cy = (t + b) / 2;
    this.glide(cx, cy, z, instant);
  }

  /* move the camera to a centre and zoom together (one tween, so they cannot fight) */
  glide(cx, cy, z, instant) {
    const cam = this.cameras.main;
    if (this.camTween) this.camTween.stop();
    if (instant) { cam.setZoom(z).centerOn(cx, cy); return; }
    const from = { x: cam.midPoint.x, y: cam.midPoint.y, z: cam.zoom }, o = { t: 0 };
    this.camTween = this.tweens.add({ targets: o, t: 1, duration: 450, ease: "Sine.easeInOut",
      onUpdate: () => { cam.setZoom(from.z + (z - from.z) * o.t).centerOn(from.x + (cx - from.x) * o.t, from.y + (cy - from.y) * o.t); } });
  }

  overview() {
    S.follow = false; S.view = null;
    const cam = this.cameras.main, as = worldMap().areas;
    const W = worldMap().W, H = worldMap().H;
    const xs = as.flatMap(a => [iso(a, 0, H).x, iso(a, W, 0).x]), ys = as.flatMap(a => [iso(a, 0, 0).y - 60, iso(a, W, H).y]);
    const l = Math.min(...xs), r = Math.max(...xs), t = Math.min(...ys), b = Math.max(...ys);
    this.glide((l + r) / 2, (t + b) / 2, Math.min(GW / (r - l + 40), GH / (b - t + 40)));
    renderMaps();
  }

  follow(name) {
    if (!S.follow || !name) return;
    const a = this.sprites[name].area;
    if (a && a !== S.view) { this.view(a); renderMaps(); }
  }

  /* walk to a place: along each leg of the engine's route (one leg per map), stepping from map to map */
  walk(name, to, ms, legs) {
    const s = this.sprites[name], end = placeSpot(to, name);
    if (s.tween) { s.tween.stop(); s.tween = null; }
    if (!ms || !legs) { this.put(name, end); s.sp.anims.stop(); s.sp.setFrame(0); return; }
    const pts = [];  // {x, y, area, jump}
    legs.forEach((leg, i) => leg.path.forEach((t, j) => {
      const c = centre(leg.area, t[0], t[1]);
      pts.push({ x: c.x, y: c.y, area: leg.area, jump: false });
    }));
    pts.push({ ...end, jump: false });
    pts.unshift({ x: s.sp.x, y: s.sp.y, area: s.area, jump: false });
    for (let i = 1; i < legs.length; i++) {  // a forest trail between two maps: follow its corner
      const a = areaOf(legs[i - 1].area), b = areaOf(legs[i].area);
      const A = legs[i - 1].path[legs[i - 1].path.length - 1], B = legs[i].path[0];
      const XA = a.offset[0] + A[0], YA = a.offset[1] + A[1], XB = b.offset[0] + B[0], YB = b.offset[1] + B[1];
      if (Math.abs(XA - XB) + Math.abs(YA - YB) <= 1) continue;
      const c = isoG(XA, YB), at = pts.findIndex(p => p.area === legs[i].area);
      if (at > 0) pts.splice(at, 0, { x: c.x, y: c.y + TH / 2, area: legs[i - 1].area, jump: false });
    }
    // its route, in its colour, on every map it crosses
    const col = Phaser.Display.Color.HexStringToColor(colorOf(name)).color;
    const g = this.add.graphics().setDepth(-8e3);
    for (let i = 1; i < pts.length; i++) if (!pts[i].jump) g.lineStyle(2, col, .9).lineBetween(pts[i - 1].x, pts[i - 1].y, pts[i].x, pts[i].y);
    this.tweens.add({ targets: g, alpha: 0, delay: ms, duration: Math.max(ms * 2, 400), onComplete: () => g.destroy() });
    const legsLen = []; let total = 0;
    for (let i = 1; i < pts.length; i++) { const d = pts[i].jump ? 0 : Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y); legsLen.push(d); total += d; }
    const pos = { d: 0 };
    s.tween = this.tweens.add({ targets: pos, d: total || 1, duration: ms,
      onUpdate: () => {
        let d = pos.d, i = 0;
        while (i < legsLen.length - 1 && d > legsLen[i]) { d -= legsLen[i]; i++; }
        const a = pts[i], b = pts[i + 1] || a, f = legsLen[i] ? Math.min(1, d / legsLen[i]) : 1;
        const dx = b.x - a.x, dy = b.y - a.y;
        if (dx || dy) s.sp.play(`${s.key}_${dy < 0 ? (dx < 0 ? "left" : "up") : (dx < 0 ? "down" : "right")}`, true);
        this.put(name, { x: a.x + dx * f, y: a.y + dy * f, area: f >= 1 ? b.area : a.area });
        if (S.follow && S.followDev === name) this.follow(name);
      },
      onComplete: () => { s.sp.anims.stop(); s.sp.setFrame(0); s.tween = null; this.put(name, end); } });
  }

  /* inside the workshop: step up to the machine being studied */
  study(name, fn, ms) {
    const ws = workshop(moduleOf(fn)); if (!ws || !ms) return;
    const m = ws.w.machines.find(x => x.name === fn); if (!m) return;
    const s = this.sprites[name]; if (s.tween) return;
    const c = centre(ws.w.area, m.stand[0], m.stand[1]);
    const o = { x: s.sp.x, y: s.sp.y };
    s.tween = this.tweens.add({ targets: o, x: c.x, y: c.y, duration: ms * .4,
      onUpdate: () => this.put(name, o), onComplete: () => { s.tween = null; } });
  }

  emote(name, frame, ms) {
    if (!ms) return;
    const s = this.sprites[name];
    const e = this.add.image(s.sp.x, s.sp.y - 42, "ui", frame).setDepth(TOP + 2);
    this.tweens.add({ targets: e, y: e.y - 6, alpha: { from: 1, to: 0 }, duration: Math.max(ms * 1.6, 300),
      ease: "Cubic.easeIn", onComplete: () => e.destroy() });
  }

  float(name, text, color, ms) {
    if (!ms) return;
    const s = this.sprites[name];
    const t = this.add.text(s.sp.x, s.sp.y - 48, text, { fontFamily: "VT323", fontSize: "11px", color,
      stroke: "#1b271f", strokeThickness: 3 }).setOrigin(.5, 1).setResolution(4).setDepth(TOP + 3);
    this.tweens.add({ targets: t, y: t.y - 14, alpha: { from: 1, to: 0 }, duration: Math.max(ms * 2, 500),
      onComplete: () => t.destroy() });
  }

  link(a, b, ok, ms) {
    if (!ms) return;
    const A1 = this.sprites[a].sp, B1 = this.sprites[b].sp;
    const g = this.add.graphics().setDepth(TOP);
    g.lineStyle(2, ok ? 0xf2b632 : 0xb23a2a, 1).lineBetween(A1.x, A1.y - 18, B1.x, B1.y - 18);
    this.tweens.add({ targets: g, alpha: 0, duration: Math.max(ms * 1.6, 300), onComplete: () => g.destroy() });
  }

  /* a letter: an envelope flies to the master and back */
  letter(a, b, ms) {
    if (!ms) return;
    const A1 = this.sprites[a].sp, B1 = this.sprites[b].sp;
    const env = this.add.container(A1.x, A1.y - 24).setDepth(TOP + 4);
    env.add(this.add.rectangle(0, 0, 9, 6, 0xffffff).setStrokeStyle(1, 0x26160e));
    env.add(this.add.rectangle(0, 0, 2, 2, 0xc8463a));
    this.tweens.chain({ targets: env, tweens: [
      { x: B1.x, y: B1.y - 24, duration: Math.max(ms * .45, 200), ease: "Sine.easeInOut" },
      { x: A1.x, y: A1.y - 24, duration: Math.max(ms * .45, 200), ease: "Sine.easeInOut", onComplete: () => env.destroy() }] });
  }

  flash(fn, ms) {
    const m = this.machines[fn]; if (!m || !ms) return;
    m.img.setTint(0xfff1b0);
    this.time.delayedCall(Math.max(ms, 150), () => m.img.clearTint());
  }

  /* a light over each machine whose rule someone keeps in mind, in that person's colour */
  bulbs() {
    for (const [fn, m] of Object.entries(this.machines)) {
      const who = S.run.devs.find(d => S.books[d.name].includes(fn));
      m.bulb.setVisible(!!who);
      if (who) m.bulb.setFillStyle(Phaser.Display.Color.HexStringToColor(COLORS[who.look[1]]).color);
    }
  }

  highlight(active) {
    for (const [n, s] of Object.entries(this.sprites)) s.tag.setStyle({ color: active === n ? "#f2b632" : "#fff6df" });
  }
}
/* ===================================================================== replay */
function sprint() { return S.run.sprints[S.sprint]; }

function reset() {
  const sp = sprint();
  S.books = {}; S.budget = {}; S.loc = {}; S.orders = {}; S.active = {}; S.fresh = {}; S.gone = {};
  S.tally = { done: 0, failed: 0, study: 0, ask: 0, unanswered: 0, walk: 0, forgot: 0, wrong: 0, read: 0, wrote: 0,
              board: 0, letters: 0 };
  for (const d of S.run.devs) {
    S.books[d.name] = [...(sp.start_notebooks[d.name] || [])];
    S.budget[d.name] = sp.budget; S.loc[d.name] = d.home; S.fresh[d.name] = null; S.gone[d.name] = [];
  }
  for (const p of sp.projects) S.orders[p.id] = { p, state: "pending", by: p.dev };
  S.log = [];
}

/* apply one event; ms > 0 animates it */
function apply(e, ms) {
  const sc = S.scene, who = e.dev, t = S.tally;
  if (e.budget !== undefined) S.budget[who] = e.budget;
  S.fresh[who] = null; S.gone[who] = [];
  switch (e.kind) {
    case "start":
      S.orders[e.project].state = "working"; S.orders[e.project].by = who; S.active[who] = e.project;
      sc.emote(who, "emote_q", ms);
      say(`${nick(who)} takes order ${e.project}: ${orderText(S.orders[e.project].p)}.`);
      break;
    case "walk":
      S.loc[who] = e.to; t.walk += e.cost || 0;
      if (ms) S.followDev = who;
      sc.walk(who, e.to, ms ? ms * .85 : 0, e.legs);
      say(`${nick(who)} walks to ${placeTitle(e.to)}` + (e.steps !== undefined ?
        ` (${e.steps} tiles, ${e.remembered ? "a way it knows" : "a new way, now remembered"}).` : "."), true);
      break;
    case "learn": {
      const b = S.books[who], i = b.indexOf(e.fn);
      if (i >= 0) b.splice(i, 1);
      b.push(e.fn);
      for (const f of e.forgot || []) { const j = b.indexOf(f); if (j >= 0) b.splice(j, 1); }
      t.study++; t.forgot += (e.forgot || []).length; if (!e.correct) t.wrong++;
      S.fresh[who] = e.fn; S.gone[who] = e.forgot || [];
      sc.study(who, e.fn, ms); sc.emote(who, e.correct ? "emote_note" : "emote_bang", ms); sc.flash(e.fn, ms);
      sc.float(who, `+${verbOf(e.fn)}`, "#f2b632", ms);
      if ((e.forgot || []).length) sc.time.delayedCall(ms * .5, () => sc.float(who, `−${e.forgot.map(verbOf).join(" −")}`, "#ff8a7a", ms));
      say(`${nick(who)} studies ${e.fn}: ${e.law.replace(" (mod 101)", "")}` +
          ((e.forgot || []).length ? ` and forgets ${e.forgot.join(", ")}.` : "."));
      break;
    }
    case "read":
      t.read++;
      sc.emote(who, "emote_note", ms);
      sc.float(who, `library +${1 + (e.also || []).length}`, "#bfe6ff", ms);
      say(`${nick(who)} reads ${e.fn} at the library` + ((e.also || []).length ? ` and ${e.also.length} more rule${e.also.length > 1 ? "s" : ""}.` : "."));
      break;
    case "deposit":
      t.wrote++;
      sc.float(who, "wrote it down", "#f2d27a", ms);
      say(`${nick(who)} writes ${e.fn} down at the library.`);
      break;
    case "board":
      t.board++;
      sc.emote(who, "emote_q", ms);
      sc.float(who, `board: ${e.entries}`, "#fff6df", ms);
      say(`${nick(who)} reads the notice board: ${e.entries} entries of who knows what.`);
      break;
    case "ask":
      t.ask++; S.budget[e.to] = Math.max(0, (S.budget[e.to] || 0) - 1);
      if (e.by === "post") { t.letters++; sc.letter(who, e.to, ms); } else sc.link(who, e.to, e.answered, ms);
      sc.emote(who, "emote_q", ms);
      if (e.answered) {
        sc.time.delayedCall(ms * .4, () => sc.emote(e.to, "emote_note", ms));
        const also = (e.also || []).length;
        say(`${nick(who)} ${e.by === "post" ? "writes to" : "asks"} ${nick(e.to)} about ${e.fn}${also ? ` and gets ${also} more rule${also > 1 ? "s" : ""} ${e.by === "post" ? "in the reply" : "on the same visit"}` : ""}.`);
      } else {
        t.unanswered++;
        sc.time.delayedCall(ms * .4, () => sc.emote(e.to, "emote_dots", ms));
        say(`${nick(who)} asks ${nick(e.to)} about ${e.fn}: no idea.`);
      }
      break;
    case "submit":
      S.orders[e.project].state = e.ok ? "done" : "failed"; S.active[who] = null;
      t[e.ok ? "done" : "failed"]++;
      sc.emote(who, e.ok ? "emote_heart" : "emote_bang", ms);
      say(e.ok ? `${nick(who)} delivers ${e.project} (${e.program.length} machines, ${e.tried} tried).`
               : `${nick(who)} delivers ${e.project}, but it is wrong.`);
      break;
    case "give_up":
      S.orders[e.project].state = "failed"; S.active[who] = null; t.failed++;
      sc.emote(who, "emote_zzz", ms);
      say(`${nick(who)} gives up on ${e.project}: ${e.reason}.`);
      break;
  }
}

function seek(n, instant) {
  const ev = sprint().events;
  n = Math.max(0, Math.min(n, ev.length));
  if (instant || n < S.pos) { reset(); S.pos = 0; }
  const animate = !instant && n === S.pos + 1;
  while (S.pos < n) {
    const e = ev[S.pos++];
    apply(e, animate ? 1000 / S.speed : 0);
  }
  if (!animate) for (const d of S.run.devs) S.scene.walk(d.name, S.loc[d.name], 0);
  const last = ev[S.pos - 1];
  S.scene.highlight(last && last.dev);
  S.scene.bulbs();
  S.scene.syncCustomers(animate);
  if (last && S.follow) { S.followDev = last.dev; if (!animate) S.scene.follow(last.dev); else if (last.kind !== "walk") S.scene.follow(last.dev); }
  render(last);
}

function step() {
  if (S.pos >= sprint().events.length) {
    if (S.sprint < S.run.sprints.length - 1) { S.sprint++; $("sprint").value = S.sprint; seek(0, true); return; }
    play(false); return;
  }
  seek(S.pos + 1);
}

function play(on) {
  S.playing = on; $("bPlay").textContent = on ? "Pause" : "Play"; $("bPlay").classList.toggle("on", on);
  clearInterval(S.timer);
  if (on) S.timer = setInterval(step, 1000 / S.speed);
}

/* ===================================================================== DOM */
function say(text, minor) { if (!minor || S.speed <= 3) S.log.unshift(text); if (S.log.length > 80) S.log.length = 80; }
function orderText(p) { return `${p.in} → ${p.out}, ${p.target.length} machines`; }
function toast(text) { const t = $("toast"); t.hidden = !text; if (text) t.textContent = text; }

function machineText(w, m) {
  const k = S.run.devs.filter(d => S.books[d.name].includes(m.name)).map(d => d.look[0]);
  return `${KIND_TITLE[w.kind]} · ${m.title || verbOf(m.name)}: ${m.in} → ${m.out}. ` +
    (k.length ? `Knows its rule: ${k.join(", ")}.` : "Nobody knows its rule yet.");
}

/* the map switcher: every map, how many apprentices are there; follow the action or look around */
function renderMaps() {
  const box = $("maps"); if (!box || !S.run || !S.scene || !S.scene.sprites) return;
  const here = {};
  for (const [n, s] of Object.entries(S.scene.sprites)) here[s.area] = (here[s.area] || 0) + 1;
  box.innerHTML = `<button id="bFollow" class="${S.follow ? "on" : ""}">Follow</button>` +
    `<button id="bAll" class="${S.view ? "" : "on"}">All maps</button>` +
    worldMap().areas.map(a => `<button data-area="${a.name}" class="${S.view === a.name ? "on" : ""}">` +
      `${areaTitle(a)}${here[a.name] ? ` · ${here[a.name]}` : ""}</button>`).join("");
  $("bFollow").onclick = () => { S.follow = !S.follow; if (S.follow && S.followDev) S.scene.follow(S.followDev); renderMaps(); };
  $("bAll").onclick = () => S.scene.overview();
  for (const b of box.querySelectorAll("[data-area]")) b.onclick = () => { S.follow = false; S.scene.view(b.dataset.area); renderMaps(); };
}

function render(last) {
  const sp = sprint(), ev = sp.events, t = S.tally;
  $("scrub").max = ev.length; $("scrub").value = S.pos;
  const known = new Set(Object.values(S.books).flat());
  const total = S.run.world.districts.reduce((n, d) => n + d.workshops.reduce((m, w) => m + w.machines.length, 0), 0);
  const stat = (v, l) => `<div><b>${v}</b> <span>${l}</span></div>`;
  $("stats").innerHTML = [
    stat(`${t.done}/${sp.projects.length}`, "delivered"), stat(t.failed, "failed"),
    stat(`${S.pos}/${ev.length}`, "steps"),
    stat(t.study, "studied"), stat(`${t.ask}`, `asked${t.unanswered ? ` (${t.unanswered} no idea)` : ""}`),
    stat(t.walk, "walked"),
    ...(S.run.board || S.run.library || S.run.post ? [stat(t.board, "board reads"), stat(`${t.read}/${t.wrote}`, "library read/wrote"),
      stat(t.letters, "letters")] : []),
    stat(`${known.size}/${total}`, "rules in heads"), stat(t.forgot, "forgotten"),
    stat(S.pos >= ev.length ? `${Math.round(100 * sp.metrics.done / sp.metrics.projects)}%` : "…", "sprint score"),
  ].join("");
  $("orders").innerHTML = sp.projects.map(p => {
    const o = S.orders[p.id];
    const st = { pending: "·", working: "…", done: "✓", failed: "✗" }[o.state];
    const late = o.state === "pending" && S.pos >= ev.length ? " (not reached)" : "";
    return `<div class="order ${o.state}" title="${p.text}"><span class="st">${st}</span>` +
      `<span>${p.id}: ${orderText(p)}${late}</span><span class="who">${nick(o.by)}</span></div>`;
  }).join("");
  const capacity = S.run.capacity;
  $("devs").innerHTML = S.run.devs.map(d => {
    const book = S.books[d.name];
    const chips = book.map(fn => {
      const own = owner(moduleOf(fn));
      const ws = workshop(moduleOf(fn));
      const bg = own ? colorOf(own) : (ws && KIND_COLOR[ws.w.kind]) || "#6e4b2c";
      return `<span class="chip${S.fresh[d.name] === fn ? " new" : ""}" style="background:${bg}" title="${fn}">${verbOf(fn)}</span>`;
    }).concat(S.gone[d.name].map(fn => `<span class="chip gone" title="${fn}">${verbOf(fn)}</span>`)).join("");
    const role = d.owns.length && S.run.mode !== "solo" ? `master of ${d.owns.map(placeTitle).join(", ").replace(/the /g, "")}` : "works alone";
    const pct = Math.max(0, 100 * S.budget[d.name] / sp.budget);
    const doing = S.active[d.name] ? ` · on ${S.active[d.name]}` : "";
    return `<div class="dev${last && last.dev === d.name ? " active" : ""}"><img alt="" src="${A}portraits/${d.look.join("_")}.png">` +
      `<div><div class="nm">${d.look[0]} <span class="role">${role}${doing}</span></div>` +
      `<div class="budget" title="${S.budget[d.name]} of ${sp.budget} actions left"><i style="width:${pct}%"></i></div>` +
      `<div class="chips">${chips || '<span class="cap">nothing in mind yet</span>'}</div>` +
      `<div class="cap">${book.length}${capacity ? " / " + capacity : ""} rules in mind · ${S.budget[d.name]} actions left</div></div></div>`;
  }).join("");
  renderMaps();
  $("log").innerHTML = S.log.slice(0, 40).map(x => `<div>${esc(x)}</div>`).join("");
}
function esc(s) { return s.replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

function chooseRun(k) {
  play(false);
  S.run = S.runs[k]; S.sprint = 0; S.pos = 0;
  $("sprint").innerHTML = S.run.sprints.map((s, i) =>
    `<option value="${i}">Sprint ${s.index}: ${s.metrics.done}/${s.metrics.projects} delivered</option>`).join("");
  const r = S.run, n = r.world.districts.reduce((m, d) => m + d.workshops.reduce((a, w) => a + w.machines.length, 0), 0);
  $("runDesc").textContent = `${r.description} ${r.team} apprentice${r.team > 1 ? "s" : ""}, ${n} machines in ` +
    `${r.world.districts.length} district${r.world.districts.length > 1 ? "s" : ""}, ` +
    `${r.capacity ? r.capacity + " rules per head" : "unlimited memory"}, ${r.budget} actions each per sprint` +
    `${r.walk ? ", walking costs time" : ""}.`;
  reset();
  if (S.scene) { S.scene.build(); S.view = null; seek(0, true); S.scene.view(worldMap().plaza.area, true); }
}

function wire() {
  $("runs").innerHTML = S.runs.map((r, i) => `<option value="${i}">${r.title}</option>`).join("");
  $("runs").onchange = e => chooseRun(+e.target.value);
  $("sprint").onchange = e => { play(false); S.sprint = +e.target.value; seek(0, true); };
  $("bFirst").onclick = () => { play(false); seek(0, true); };
  $("bLast").onclick = () => { play(false); seek(sprint().events.length, true); };
  $("bPrev").onclick = () => { play(false); seek(S.pos - 1, true); };
  $("bNext").onclick = () => { play(false); seek(S.pos + 1); };
  $("bPlay").onclick = () => play(!S.playing);
  $("speed").onchange = e => { S.speed = +e.target.value; if (S.playing) play(true); };
  $("scrub").oninput = e => { play(false); seek(+e.target.value, true); };
  $("fileIn").onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    try { load(JSON.parse(await f.text())); } catch (err) { toast(`Could not read ${f.name}: ${err.message}`); }
  };
  document.addEventListener("keydown", e => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.key === " ") { e.preventDefault(); play(!S.playing); }
    if (e.key === "ArrowRight") $("bNext").click();
    if (e.key === "ArrowLeft") $("bPrev").click();
  });
}

let game = null;
function load(data) {
  const runs = Array.isArray(data) ? data : data.replays || [data];
  if (!runs.length || runs[0].kind !== "codeworld") throw new Error("not a CodeWorld replay");
  S.runs = runs; S.speed = +$("speed").value;
  wire(); chooseRun(0);
  if (game) { game.destroy(true); S.scene = null; }
  game = new Phaser.Game({ type: Phaser.AUTO, parent: "game", width: GW, height: GH, pixelArt: true,
    backgroundColor: "#1b271f", scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_HORIZONTALLY },
    scene: [Boot, Town] });
  const q = new URLSearchParams(location.search);
  if (q.has("run")) { $("runs").value = q.get("run"); chooseRun(+q.get("run")); }
}

(async () => {
  try {
    const r = await fetch("replays/codeworld.json");
    if (!r.ok) throw new Error(r.status);
    load(await r.json());
  } catch (e) {
    toast("No replays/codeworld.json yet: run scripts/build_codeworld_web.py, or load a replay file.");
    wire();
  }
})();
