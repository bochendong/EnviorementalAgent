/* SeedVille Workshops: plays back CodeWorld replays recorded by the engine
   (worldseeds/codeworld/replay.py), so the picture is always what the engine did.

   A district is a block of eight workshops on two streets around a plaza; districts tile into a town.
   Apprentices walk to a workshop to study its machines, walk to a master to ask, and deliver orders. */
"use strict";

const A = "assets/";
const GW = 1280, GH = 800;            // canvas size
const DW = 640, DH = 470;             // one district, in world pixels
const COLS_X = [85, 235, 405, 555];   // workshop x in a row
const ROW_BASE = [150, 420];          // building base (door) y of the two rows
const STREET_Y = [170, 440], STREET_X = 320;
const PLAZA = { x: 320, y: 270 };
const DIRS = ["down", "left", "right", "up"];
const COLORS = { red: "#c8463a", blue: "#3f6fc4", green: "#3d8a3a", yellow: "#c9a227", purple: "#8a4fb0", orange: "#d8782e" };
const FRAME = { bakery: "bakery", smithy: "smithy", florist: "florist", mine: "mine", clinic: "clinic", inn: "inn",
                shop: "shop", farm: "farmhouse" };
const KIND_COLOR = { bakery: "#b8743a", smithy: "#5a6270", florist: "#b4558a", mine: "#6e6a64", clinic: "#3e8c8c",
                     inn: "#8a4a2a", shop: "#3f6fc4", farm: "#6a8a2a" };
const KIND_TITLE = { bakery: "Bakery", smithy: "Smithy", florist: "Florist", mine: "Mine", clinic: "Clinic", inn: "Inn",
                     shop: "Shop", farm: "Farm" };

const $ = id => document.getElementById(id);
const hex = c => parseInt(c.slice(1), 16);
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
function grid() {
  const n = S.run.world.districts.length;
  const cols = Math.ceil(Math.sqrt(n)), rows = Math.ceil(n / cols);
  return { cols, rows, W: cols * DW, H: rows * DH };
}
function origin(index) { const { cols } = grid(); return { x: (index % cols) * DW, y: Math.floor(index / cols) * DH }; }
function shopSpot(district, slot) {
  const o = origin(district);
  return { x: o.x + COLS_X[slot % 4], y: o.y + ROW_BASE[Math.floor(slot / 4)] };
}
function spot(module, devName) {
  const k = S.run.devs.findIndex(d => d.name === devName);
  const dx = ((k % 4) - 1.5) * 13, dy = (Math.floor(k / 4) % 3) * 5;
  if (!module) { const o = origin(0); return { x: o.x + PLAZA.x + dx * 2, y: o.y + PLAZA.y + 18 + dy }; }
  const { d, w } = workshop(module);
  const p = shopSpot(d.index, d.workshops.indexOf(w));
  return { x: p.x + dx, y: p.y + 14 + dy };
}

/* ===================================================================== Phaser */
class Boot extends Phaser.Scene {
  constructor() { super("boot"); }
  preload() {
    const bar = this.add.rectangle(GW / 2 - 150, GH / 2, 0, 10, 0xf2b632).setOrigin(0, .5);
    this.add.rectangle(GW / 2, GH / 2, 304, 14).setStrokeStyle(2, 0x7a4a26);
    this.load.on("progress", p => bar.width = 300 * p);
    this.load.atlas("bld", `${A}buildings_summer.png`, `${A}buildings_summer.json`);
    this.load.atlas("props", `${A}props_summer.png`, `${A}props_summer.json`);
    this.load.atlas("obj", `${A}objects.png`, `${A}objects.json`);
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
    this.layer = this.add.container(0, 0);
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
    this.children.removeAll(true);
    this.sprites = {}; this.shops = {};
    const { cols, rows, W, H } = grid();
    const g = this.add.graphics().setDepth(-10);
    g.fillStyle(0x5f9a3c).fillRect(-200, -200, W + 400, H + 400);
    const rnd = new Phaser.Math.RandomDataGenerator(["seedville"]);
    for (let k = 0; k < (W * H) / 900; k++) {
      g.fillStyle(rnd.pick([0x548c34, 0x6aa845, 0x4f8530]));
      g.fillRect(rnd.between(-200, W + 200), rnd.between(-200, H + 200), 3, 2);
    }
    // streets: two per row of districts, one per column, all connected
    const street = (x, y, w, h) => { g.fillStyle(0xa9844a).fillRect(x - 2, y - 2, w + 4, h + 4); g.fillStyle(0xd2ae72).fillRect(x, y, w, h); };
    for (let r = 0; r < rows; r++) for (const y of STREET_Y) street(0, r * DH + y - 8, W, 16);
    for (let c = 0; c < cols; c++) street(c * DW + STREET_X - 8, 0, 16, H);
    for (const d of S.run.world.districts) this.district(d, g, rnd);
    // empty slots of the grid are meadow with trees
    for (let k = S.run.world.districts.length; k < cols * rows; k++) {
      const o = origin(k);
      for (let t = 0; t < 14; t++) this.tree(o.x + rnd.between(30, DW - 30), o.y + rnd.between(60, DH - 20), rnd);
    }
    this.links = this.add.graphics().setDepth(5000);
    for (const d of S.run.devs) this.dev(d);
    this.fit();
  }

  district(d, g, rnd) {
    const o = origin(d.index);
    // plaza with fountain and the order board
    g.fillStyle(0xa9844a).fillCircle(o.x + PLAZA.x, o.y + PLAZA.y - 10, 44);
    g.fillStyle(0xdcbf86).fillCircle(o.x + PLAZA.x, o.y + PLAZA.y - 10, 41);
    const f = this.add.sprite(o.x + PLAZA.x, o.y + PLAZA.y, "obj", "fountain0").setOrigin(.5, 1);
    f.setDepth(f.y);
    this.time.addEvent({ delay: 250, loop: true, callback: () => f.setFrame(`fountain${(this.time.now / 250 | 0) % 3}`) });
    const board = this.add.image(o.x + PLAZA.x + 52, o.y + PLAZA.y - 14, "obj", "board").setOrigin(.5, 1);
    board.setDepth(board.y);
    const title = S.run.world.districts.length > 1 ? `${cap(d.name)} district` : "SeedVille";
    this.add.text(o.x + PLAZA.x, o.y + PLAZA.y + 36, title, {
      fontFamily: "Pixelify Sans", fontSize: "13px", color: "#fff6df", backgroundColor: "#7a4a26",
      padding: { x: 5, y: 1 } }).setOrigin(.5).setResolution(4).setDepth(4000);
    // workshops
    const blocked = [];
    d.workshops.forEach((w, slot) => {
      const p = shopSpot(d.index, slot);
      const img = this.add.image(p.x, p.y, "bld", FRAME[w.kind] || "house0").setOrigin(.5, 1);
      img.setDepth(p.y);
      blocked.push(new Phaser.Geom.Rectangle(p.x - img.width / 2 - 6, p.y - img.height - 6, img.width + 12, img.height + 30));
      g.fillStyle(0xd2ae72).fillRect(p.x - 7, p.y, 14, STREET_Y[Math.floor(slot / 4)] - p.y);
      const own = owner(w.module);
      const label = this.add.text(p.x, p.y - img.height - 4,
        `${KIND_TITLE[w.kind] || w.kind}${own ? " · " + nick(own) : ""}`, {
          fontFamily: "Pixelify Sans", fontSize: "10px", color: "#fff6df",
          backgroundColor: own ? colorOf(own) : "#4a2a14", padding: { x: 3, y: 1 } })
        .setOrigin(.5, 1).setResolution(4).setDepth(4001);
      img.setInteractive({ useHandCursor: true });
      img.on("pointerover", () => showMachines(w));
      img.on("pointerout", () => toast(null));
      this.shops[w.module] = { img, label };
    });
    for (const y of STREET_Y) blocked.push(new Phaser.Geom.Rectangle(o.x, o.y + y - 14, DW, 26));
    blocked.push(new Phaser.Geom.Rectangle(o.x + STREET_X - 14, o.y, 28, DH));
    blocked.push(new Phaser.Geom.Rectangle(o.x + PLAZA.x - 70, o.y + PLAZA.y - 60, 140, 110));
    for (let t = 0, tries = 0; t < 10 && tries < 300; tries++) {
      const x = o.x + rnd.between(14, DW - 14), y = o.y + rnd.between(40, DH - 4);
      if (blocked.some(r => r.contains(x, y) || r.contains(x, y - 30))) continue;
      this.tree(x, y, rnd); blocked.push(new Phaser.Geom.Rectangle(x - 20, y - 20, 40, 30)); t++;
    }
    for (const [dx, dy] of [[-60, -30], [60, -30]]) {
      const l = this.add.image(o.x + PLAZA.x + dx, o.y + PLAZA.y + dy, "obj", "lamppost").setOrigin(.5, 1);
      l.setDepth(l.y);
    }
  }

  tree(x, y, rnd) {
    const k = rnd.pick(["oak0", "oak1", "oak2", "pine0", "pine1", "bush0", "bush1", "rock0"]);
    this.add.image(x, y, "props", k).setOrigin(.5, 1).setDepth(y);
  }

  dev(d) {
    const key = `ch_${d.look.join("_")}`;
    const p = spot(d.home, d.name);
    const sh = this.add.image(p.x, p.y, "obj", "shadow").setAlpha(.5);
    const sp = this.add.sprite(p.x, p.y, key, 0).setOrigin(.5, 1);
    const tag = this.add.text(p.x, p.y - 33, d.look[0], { fontFamily: "Pixelify Sans", fontSize: "9px", color: "#fff6df",
      backgroundColor: COLORS[d.look[1]], padding: { x: 2, y: 0 } }).setOrigin(.5, 1).setResolution(4);
    const k = S.run.devs.indexOf(d);
    this.sprites[d.name] = { sp, sh, tag, key, tween: null, lift: (k % 2) * 9 };
    this.put(d.name, p);
  }

  put(name, p) {
    const s = this.sprites[name];
    s.sp.setPosition(p.x, p.y).setDepth(p.y + .5);
    s.sh.setPosition(p.x, p.y - 1).setDepth(p.y);
    s.tag.setPosition(p.x, p.y - 33 - s.lift).setDepth(6000);
  }

  fit() {
    const { W, H } = grid(), cam = this.cameras.main;
    this.fitZoom = Math.min(GW / W, GH / H);
    cam.setZoom(this.fitZoom).centerOn(W / 2, H / 2);
  }

  walk(name, to, ms) {
    const s = this.sprites[name], p = spot(to, name);
    if (s.tween) { s.tween.stop(); s.tween = null; }
    if (!ms) { this.put(name, p); s.sp.anims.stop(); return; }
    const dx = p.x - s.sp.x, dy = p.y - s.sp.y;
    const dir = Math.abs(dx) > Math.abs(dy) ? (dx < 0 ? "left" : "right") : (dy < 0 ? "up" : "down");
    s.sp.play(`${s.key}_${dir}`, true);
    const o = { x: s.sp.x, y: s.sp.y };
    s.tween = this.tweens.add({ targets: o, x: p.x, y: p.y, duration: ms,
      onUpdate: () => this.put(name, o),
      onComplete: () => { s.sp.anims.stop(); s.sp.setFrame(0); s.tween = null; } });
  }

  emote(name, frame, ms) {
    if (!ms) return;
    const s = this.sprites[name];
    const e = this.add.image(s.sp.x, s.sp.y - 40, "ui", frame).setDepth(7000);
    this.tweens.add({ targets: e, y: e.y - 6, alpha: { from: 1, to: 0 }, duration: Math.max(ms * 1.6, 300),
      ease: "Cubic.easeIn", onComplete: () => e.destroy() });
  }

  float(name, text, color, ms) {
    if (!ms) return;
    const s = this.sprites[name];
    const t = this.add.text(s.sp.x, s.sp.y - 46, text, { fontFamily: "VT323", fontSize: "11px", color,
      stroke: "#1b271f", strokeThickness: 3 }).setOrigin(.5, 1).setResolution(4).setDepth(7001);
    this.tweens.add({ targets: t, y: t.y - 14, alpha: { from: 1, to: 0 }, duration: Math.max(ms * 2, 500),
      onComplete: () => t.destroy() });
  }

  link(a, b, ok, ms) {
    if (!ms) return;
    const A1 = this.sprites[a].sp, B1 = this.sprites[b].sp;
    const g = this.add.graphics().setDepth(5000);
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
      sc.walk(who, e.to, ms ? ms * .85 : 0);
      say(`${nick(who)} walks to ${placeTitle(e.to)}.`, true);
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
