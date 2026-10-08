/* SeedVille Workshops: plays back CodeWorld replays recorded by the engine
   (worldseeds/codeworld/replay.py), so the picture is always what the engine did.

   An isometric city. A district is 8 x 8 tiles with a road every 4 tiles; its eight workshops are
   towers on the streets, two in each block, and districts join into one road grid. Apprentices walk
   the roads to a workshop to study its machines, to a master to ask, and deliver orders. */
"use strict";

const A = "assets/";
const GW = 1280, GH = 800;            // canvas size
const TW = 64, TH = 32;               // isometric tile
const QUADS = [[1, 1], [7, 1], [1, 7], [7, 7]];  // blocks inside a district (5 x 5 tiles each)
const DIRS = ["down", "left", "right", "up"];
const COLORS = { red: "#c8463a", blue: "#3f6fc4", green: "#3d8a3a", yellow: "#c9a227", purple: "#8a4fb0", orange: "#d8782e" };
const KIND_COLOR = { bakery: "#c98a3a", smithy: "#4c5262", florist: "#b0563e", mine: "#9a7a5a", clinic: "#8a8f9c",
                     inn: "#a0503a", shop: "#4a8a8a", farm: "#5a8a42" };
const KIND_TITLE = { bakery: "Bakery", smithy: "Smithy", florist: "Florist", mine: "Mine", clinic: "Clinic", inn: "Inn",
                     shop: "Shop", farm: "Farm" };
const TOP = 1e5;                      // depth of labels and speech above the city

const $ = id => document.getElementById(id);
const cap = s => s.charAt(0).toUpperCase() + s.slice(1);

/* ===================================================================== state */
const S = {
  runs: [], run: null, sprint: 0, pos: 0, playing: false, speed: 3, timer: null, scene: null,
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
function placeTitle(module) {
  if (!module) return "the plaza";
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
function grid() { return S.run.world.map; }  // the engine's street map (worldseeds/codeworld/citymap.py)
function corner(index) { const m = grid(); return [(index % m.cols) * m.block, Math.floor(index / m.cols) * m.block]; }
const isRoad = (gx, gy) => gx % grid().road === 0 || gy % grid().road === 0;
let ORIGIN = { x: 0, y: 0 };
/* top vertex of tile (gx, gy) in world pixels; the tile's centre is 16 px lower */
function iso(gx, gy) { return { x: ORIGIN.x + (gx - gy) * TW / 2, y: ORIGIN.y + (gx + gy) * TH / 2 }; }
function centre(gx, gy) { const p = iso(gx, gy); return { x: p.x, y: p.y + TH / 2 }; }
function tileOfPlace(module) { return module ? workshop(module).w.door : grid().plaza; }
function devOffset(name) {
  const k = S.run.devs.findIndex(d => d.name === name);
  return { x: ((k % 4) - 1.5) * 7, y: (Math.floor(k / 4) % 3) * 4 - 4 };
}
function spot(module, name) {
  const [gx, gy] = tileOfPlace(module), c = centre(gx, gy), o = devOffset(name);
  return { x: c.x + o.x, y: c.y + o.y };
}
/* shortest way along the roads, as a list of road tiles (only for replays that do not record their paths) */
function route(from, to) {
  const { GX, GY } = grid(), key = (x, y) => x * 1000 + y;
  const prev = new Map([[key(...from), null]]), q = [from];
  while (q.length) {
    const [x, y] = q.shift();
    if (x === to[0] && y === to[1]) break;
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const nx = x + dx, ny = y + dy;
      if (nx < 0 || ny < 0 || nx > GX || ny > GY || !isRoad(nx, ny) || prev.has(key(nx, ny))) continue;
      prev.set(key(nx, ny), [x, y]); q.push([nx, ny]);
    }
  }
  if (!prev.has(key(...to))) return [to];
  const out = []; let c = to;
  while (c) { out.push(c); c = prev.get(key(...c)); }
  out.reverse();
  // keep only the corners
  return out.filter((p, i) => i === 0 || i === out.length - 1 ||
    (out[i - 1][0] - p[0]) !== (p[0] - out[i + 1][0]) || (out[i - 1][1] - p[1]) !== (p[1] - out[i + 1][1]));
}

/* ===================================================================== Phaser */
class Boot extends Phaser.Scene {
  constructor() { super("boot"); }
  preload() {
    const bar = this.add.rectangle(GW / 2 - 150, GH / 2, 0, 10, 0xf2b632).setOrigin(0, .5);
    this.add.rectangle(GW / 2, GH / 2, 304, 14).setStrokeStyle(2, 0x7a4a26);
    this.load.on("progress", p => bar.width = 300 * p);
    this.load.atlas("iso", `${A}iso.png`, `${A}iso.json`);
    this.load.atlas("ui", `${A}ui.png`, `${A}ui.json`);
    const looks = new Set();
    for (const r of S.runs) for (const d of r.devs) looks.add(d.look.join("_"));
    for (const k of looks) this.load.spritesheet(`ch_${k}`, `${A}chars/${k}.png`, { frameWidth: 16, frameHeight: 32 });
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
    this.sprites = {}; this.shops = {};
    this.build();
    const cam = this.cameras.main;
    this.input.on("wheel", (p, o, dx, dy) => {
      const z = Phaser.Math.Clamp(cam.zoom * (dy > 0 ? .9 : 1.1), this.fitZoom * .8, 4);
      const before = cam.getWorldPoint(p.x, p.y);
      cam.setZoom(z);
      const after = cam.getWorldPoint(p.x, p.y);
      cam.scrollX += before.x - after.x; cam.scrollY += before.y - after.y;
    });
    this.input.on("pointermove", p => {
      if (!p.isDown) return;
      cam.scrollX -= (p.x - p.prevPosition.x) / cam.zoom; cam.scrollY -= (p.y - p.prevPosition.y) / cam.zoom;
    });
    this.input.on("pointerdown", p => { if (p.event.detail === 2) this.fit(); });
    seek(S.pos, true);
  }

  build() {
    this.tweens.killAll(); this.time.removeAllEvents();
    this.children.removeAll(true);
    this.sprites = {}; this.shops = {};
    const { GX, GY } = grid();
    ORIGIN = { x: (GY + 2) * TW / 2, y: 130 };
    this.cameras.main.setBackgroundColor("#2c4a2a");
    const rnd = new Phaser.Math.RandomDataGenerator(["seedville"]);
    const taken = new Set();
    // ground: a ring of grass around the road grid
    for (let gx = -1; gx <= GX + 1; gx++) for (let gy = -1; gy <= GY + 1; gy++) {
      const inside = gx >= 0 && gy >= 0 && gx <= GX && gy <= GY;
      let f = "t_grass";
      const R = grid().road;
      if (inside && isRoad(gx, gy)) f = gx % R === 0 && gy % R === 0 ? "t_cross" : gx % R === 0 ? "t_road_y" : "t_road_x";
      const p = iso(gx, gy);
      this.add.image(p.x, p.y, "iso", f).setOrigin(.5, 0).setDepth(-1e4);
      if (!inside && rnd.frac() < .35) this.prop(gx, gy, rnd.pick(["tree0", "tree1", "tree2"]));
    }
    for (const d of S.run.world.districts) this.district(d, rnd, taken);
    const pl = grid().plaza, pp = iso(...pl);
    this.add.image(pp.x, pp.y, "iso", "t_plaza").setOrigin(.5, 0).setDepth(-9e3);
    this.cars(rnd);
    for (const d of S.run.devs) this.dev(d);
    this.fit();
  }

  /* a building or prop standing on tile (gx, gy); its frame has the tile diamond in its bottom 32 rows */
  prop(gx, gy, frame, depthShift = 0) {
    const p = iso(gx, gy), f = this.textures.getFrame("iso", frame);
    const img = this.add.image(p.x, p.y + TH, "iso", frame);
    if (frame.startsWith("tree")) img.setOrigin(.5, 1).setY(p.y + TH / 2 + 4);
    else img.setOrigin(.5, 1);
    img.setDepth(p.y + TH / 2 + 8 + depthShift);
    return img;
  }

  district(d, rnd, taken) {
    const [cx, cy] = corner(d.index);
    const title = S.run.world.districts.length > 1 ? `${cap(d.name)} district` : "SeedVille";
    const near = new Set();
    for (const w of d.workshops) {
      const [gx, gy] = w.tile;
      taken.add(`${gx},${gy}`);
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, -1], [1, -1], [-1, 1]]) near.add(`${gx + dx},${gy + dy}`);
      const img = this.prop(gx, gy, `w_${w.kind}`);
      const own = owner(w.module);
      const label = this.add.text(img.x, img.y - img.height + 12,
        `${KIND_TITLE[w.kind] || w.kind}${own ? " · " + nick(own) : ""}`, {
          fontFamily: "Pixelify Sans", fontSize: "10px", color: "#fff6df",
          backgroundColor: own ? colorOf(own) : "#3a3f4c", padding: { x: 3, y: 1 } })
        .setOrigin(.5, 1).setResolution(4).setDepth(TOP);
      img.setInteractive({ useHandCursor: true, pixelPerfect: true });
      img.on("pointerover", () => showMachines(w));
      img.on("pointerout", () => toast(null));
      this.shops[w.module] = { img, label };
    }
    // each block is mostly open ground: a small park, a few trees, one house or low building
    const ground = (gx, gy, f) => { const p = iso(gx, gy); this.add.image(p.x, p.y, "iso", f).setOrigin(.5, 0).setDepth(-9e3); };
    for (const [qx, qy] of QUADS) {
      const free = [];
      for (let i = 0; i < 5; i++) for (let j = 0; j < 5; j++) {
        const k = `${cx + qx + i},${cy + qy + j}`;
        if (!taken.has(k) && !near.has(k)) free.push([cx + qx + i, cy + qy + j]);
      }
      rnd.shuffle(free);
      const take = () => { const t = free.pop(); if (t) taken.add(`${t[0]},${t[1]}`); return t; };
      const park = take();
      if (park) { ground(...park, "t_park"); this.prop(...park, rnd.frac() < .4 ? "fountain" : "tree1"); }
      const thing = take();
      if (thing) {
        const r = rnd.frac();
        if (r < .45) this.prop(...thing, `f_house${rnd.between(0, 2)}`);
        else if (r < .75) this.prop(...thing, rnd.pick(["f_low0", "f_low1"]));
        else { ground(...thing, "t_lot"); this.prop(...thing, rnd.pick(["car_red_x", "car_blue_y", "van_x"]), -4); }
      }
      for (let n = rnd.between(2, 4); n > 0; n--) { const t = take(); if (t) this.prop(...t, rnd.pick(["tree0", "tree1", "tree2"])); }
    }
    const sign = centre(cx + grid().road, cy + grid().road);
    this.add.text(sign.x, sign.y + 14, title, { fontFamily: "Pixelify Sans", fontSize: "12px", color: "#fff6df",
      backgroundColor: "#7a4a26", padding: { x: 5, y: 1 } }).setOrigin(.5, 0).setResolution(4).setDepth(TOP - 1);
  }

  /* traffic: a few cars driving along the roads, just for life */
  cars(rnd) {
    const { GX, GY } = grid();
    const n = 2 * S.run.world.districts.length;
    for (let k = 0; k < n; k++) {
      const kind = rnd.pick(["car_red", "car_blue", "van", "truck"]);
      const img = this.add.image(0, 0, "iso", `${kind}_x`).setOrigin(.5, .75).setVisible(false);
      const drive = () => {
        const alongX = rnd.frac() < .5, R = grid().road, line = R * rnd.between(0, (alongX ? GY : GX) / R);
        const a = alongX ? [0, line] : [line, 0], b = alongX ? [GX, line] : [line, GY];
        const [s, e] = rnd.frac() < .5 ? [a, b] : [b, a];
        img.setFrame(`${kind}_${alongX ? "x" : "y"}`).setFlipX(false);
        const lane = alongX ? { x: 4, y: -2 } : { x: -4, y: -2 };
        const o = { t: 0 }, cs = centre(...s), ce = centre(...e);
        this.tweens.add({ targets: o, t: 1, duration: 9000 + rnd.between(0, 6000), delay: rnd.between(0, 2500),
          onUpdate: () => { const x = cs.x + (ce.x - cs.x) * o.t + lane.x, y = cs.y + (ce.y - cs.y) * o.t + lane.y;
            img.setPosition(x, y).setDepth(y + 2).setVisible(true); },
          onComplete: drive });
      };
      drive();
    }
  }

  dev(d) {
    const key = `ch_${d.look.join("_")}`;
    const p = spot(d.home, d.name);
    const sh = this.add.ellipse(p.x, p.y, 12, 5, 0x000000, .3);
    const sp = this.add.sprite(p.x, p.y, key, 0).setOrigin(.5, 1);
    const tag = this.add.text(p.x, p.y - 33, d.look[0], { fontFamily: "Pixelify Sans", fontSize: "9px", color: "#fff6df",
      backgroundColor: COLORS[d.look[1]], padding: { x: 2, y: 0 } }).setOrigin(.5, 1).setResolution(4);
    const k = S.run.devs.indexOf(d);
    this.sprites[d.name] = { sp, sh, tag, key, tween: null, lift: (k % 2) * 9, tile: tileOfPlace(d.home) };
    this.put(d.name, p);
  }

  put(name, p) {
    const s = this.sprites[name];
    s.sp.setPosition(p.x, p.y).setDepth(p.y + 1);
    s.sh.setPosition(p.x, p.y - 1).setDepth(p.y + .5);
    s.tag.setPosition(p.x, p.y - 33 - s.lift).setDepth(TOP + 1);
  }

  fit() {
    const { GX, GY } = grid(), cam = this.cameras.main;
    const l = iso(-1, GY + 1).x - TW / 2, r = iso(GX + 1, -1).x + TW / 2;
    const t = iso(-1, -1).y - 70, b = iso(GX + 1, GY + 1).y + TH;
    this.fitZoom = Math.min(GW / (r - l), GH / (b - t));
    cam.setZoom(this.fitZoom).centerOn((l + r) / 2, (t + b) / 2);
  }

  /* walk to a place along `path` (the turning points of the engine's route), or the shortest way */
  walk(name, to, ms, path) {
    const s = this.sprites[name], target = tileOfPlace(to), o = devOffset(name);
    if (s.tween) { s.tween.stop(); s.tween = null; }
    path = path || route(s.tile, target);
    s.tile = target;
    if (!ms) { this.put(name, spot(to, name)); s.sp.anims.stop(); s.sp.setFrame(0); return; }
    const pts = path.map(t => centre(...t)).map((c, i, a) => i === a.length - 1 ? { x: c.x + o.x, y: c.y + o.y } : c);
    pts.unshift({ x: s.sp.x, y: s.sp.y });
    if (pts.length > 2) {  // the route it takes, in its colour
      const g = this.add.graphics().setDepth(-8e3);
      g.lineStyle(3, Phaser.Display.Color.HexStringToColor(colorOf(name)).color, .8).strokePoints(pts.slice(1));
      this.tweens.add({ targets: g, alpha: 0, duration: Math.max(ms * 2.5, 400), onComplete: () => g.destroy() });
    }
    const legs = []; let total = 0;
    for (let i = 1; i < pts.length; i++) { const d = Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y); legs.push(d); total += d; }
    const pos = { d: 0 };
    s.tween = this.tweens.add({ targets: pos, d: total, duration: ms,
      onUpdate: () => {
        let d = pos.d, i = 0;
        while (i < legs.length - 1 && d > legs[i]) { d -= legs[i]; i++; }
        const a = pts[i], b = pts[i + 1] || a, f = legs[i] ? Math.min(1, d / legs[i]) : 1;
        const dx = b.x - a.x, dy = b.y - a.y;
        const dir = dy < 0 ? (dx < 0 ? "left" : "up") : (dx < 0 ? "down" : "right");
        s.sp.play(`${s.key}_${dir}`, true);
        this.put(name, { x: a.x + dx * f, y: a.y + dy * f });
      },
      onComplete: () => { s.sp.anims.stop(); s.sp.setFrame(0); s.tween = null; } });
  }
  emote(name, frame, ms) {
    if (!ms) return;
    const s = this.sprites[name];
    const e = this.add.image(s.sp.x, s.sp.y - 40, "ui", frame).setDepth(TOP + 2);
    this.tweens.add({ targets: e, y: e.y - 6, alpha: { from: 1, to: 0 }, duration: Math.max(ms * 1.6, 300),
      ease: "Cubic.easeIn", onComplete: () => e.destroy() });
  }

  float(name, text, color, ms) {
    if (!ms) return;
    const s = this.sprites[name];
    const t = this.add.text(s.sp.x, s.sp.y - 46, text, { fontFamily: "VT323", fontSize: "11px", color,
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

  flash(module, ms) {
    const sh = this.shops[module]; if (!sh || !ms) return;
    sh.img.setTint(0xfff1b0);
    this.time.delayedCall(Math.max(ms, 150), () => sh.img.clearTint());
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
  S.tally = { done: 0, failed: 0, study: 0, ask: 0, unanswered: 0, walk: 0, forgot: 0, wrong: 0 };
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
      sc.walk(who, e.to, ms ? ms * .85 : 0, e.path);
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
      sc.emote(who, e.correct ? "emote_note" : "emote_bang", ms); sc.flash(moduleOf(e.fn), ms);
      sc.float(who, `+${verbOf(e.fn)}`, "#f2b632", ms);
      if ((e.forgot || []).length) sc.time.delayedCall(ms * .5, () => sc.float(who, `−${e.forgot.map(verbOf).join(" −")}`, "#ff8a7a", ms));
      say(`${nick(who)} studies ${e.fn}: ${e.law.replace(" (mod 101)", "")}` +
          ((e.forgot || []).length ? ` and forgets ${e.forgot.join(", ")}.` : "."));
      break;
    }
    case "ask":
      t.ask++; S.budget[e.to] = Math.max(0, (S.budget[e.to] || 0) - 1);
      sc.link(who, e.to, e.answered, ms);
      sc.emote(who, "emote_q", ms);
      if (e.answered) {
        sc.time.delayedCall(ms * .4, () => sc.emote(e.to, "emote_note", ms));
        const also = (e.also || []).length;
        say(`${nick(who)} asks ${nick(e.to)} about ${e.fn}${also ? ` and gets ${also} more rule${also > 1 ? "s" : ""} on the same visit` : ""}.`);
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

function showMachines(w) {
  const knows = fn => S.run.devs.filter(d => S.books[d.name].includes(fn)).map(d => d.look[0]);
  toast(`${KIND_TITLE[w.kind] || w.kind}: ` + w.machines.map(m => {
    const k = knows(m.name);
    return `${verbOf(m.name)} ${m.in}→${m.out}${k.length ? " (" + k.join(", ") + ")" : ""}`;
  }).join(" · "));
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
  if (S.scene) { S.scene.build(); seek(0, true); }
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
