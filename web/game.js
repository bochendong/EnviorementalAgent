/* SeedVille client (Phaser 3).
 *
 * The Python engine (worldseeds/town) is the source of truth. This client only renders
 * TownWorld.snapshot() states and animates the step between two of them:
 *   - Replay mode: frames recorded by worldseeds/town/replay.py (assets: replays/demo.json),
 *     or any replay JSON the viewer loads (e.g. a Qwen run exported with scripts/export_replay.py).
 *   - Play mode: when served by scripts/serve_ui.py, clicks become engine actions via /api.
 *
 * Scenes: Boot (loading), World (tilemap, Y-sorted sprites, lights, camera), Hud (clock,
 * quest, toolbar, dialogue). A Director drives both from frames.
 */
"use strict";

const TILE = 16, MAPW = 48, MAPH = 32, GW = 960, GH = 540, ZOOM = 3;
const SEASONS = ["spring", "summer", "fall", "winter"];
const NAMES = ["Rosa", "Tomas", "Ivy", "Bram", "Lena", "Otto", "Mira", "Finn"];
const COLORS = ["red", "blue", "green", "yellow", "purple", "orange"];
const DIRS = ["down", "left", "right", "up"];
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : s;

/* ===================================================================== helpers */
function frameFor(o) {
  switch (o.kind) {
    case "item": return `item_${o.name}_${o.color}`;
    case "crop": return `produce_${o.name}_${o.color}`;
    case "seeds": return `seeds_${o.crop}`;
    case "tool": return `can_${o.color}`;
    case "trophy": return "trophy";
    case "decor": return o.name === "lamppost" ? "lamppost" : `${o.name}_${o.color}`;
  }
  return null;
}
function charKey(o) { return o ? `ch_${o.name}_${o.color}` : "player"; }
function cleanMessage(m, kind) {
  const lines = (m || "").split("\n").filter(l => !l.startsWith("(Day ")).map(l => l.trimEnd());
  if (kind === "act") return lines[0] + (lines.length > 1 && !lines[1].startsWith("[") ? "\n" + lines.slice(1).join("\n") : "");
  return lines.join("\n").trim();
}
function parseAction(a) {
  const m = /^(\w+)\((.*)\)$/.exec(a || "");
  if (!m) return { verb: a || "", args: [] };
  return { verb: m[1], args: m[2] ? m[2].split(",").map(s => s.trim()).filter(Boolean) : [] };
}

/* ===================================================================== Boot */
class BootScene extends Phaser.Scene {
  constructor() { super("boot"); }
  preload() {
    const bar = this.add.rectangle(GW / 2 - 150, GH / 2, 0, 10, 0xf2b632).setOrigin(0, .5);
    this.add.rectangle(GW / 2, GH / 2, 304, 14).setStrokeStyle(2, 0x7a4a26);
    this.add.text(GW / 2, GH / 2 - 30, "Growing the town…", { fontFamily: "Pixelify Sans", fontSize: "20px", color: "#f1d9a7" }).setOrigin(.5);
    this.load.on("progress", p => bar.width = 300 * p);
    const A = "assets/";
    for (const s of SEASONS) {
      this.load.image(`terrain_${s}`, `${A}terrain_${s}.png`);
      this.load.atlas(`props_${s}`, `${A}props_${s}.png`, `${A}props_${s}.json`);
      this.load.atlas(`bld_${s}`, `${A}buildings_${s}.png`, `${A}buildings_${s}.json`);
    }
    this.load.atlas("obj", `${A}objects.png`, `${A}objects.json`);
    this.load.atlas("ui", `${A}ui.png`, `${A}ui.json`);
    this.load.tilemapTiledJSON("town", `${A}town.json`);
    this.load.spritesheet("player", `${A}chars/player.png`, { frameWidth: 16, frameHeight: 32 });
    this.load.image("pt_player", `${A}portraits/player.png`);
    for (const n of NAMES) for (const c of COLORS) {
      this.load.spritesheet(`ch_${n}_${c}`, `${A}chars/${n}_${c}.png`, { frameWidth: 16, frameHeight: 32 });
      this.load.image(`pt_${n}_${c}`, `${A}portraits/${n}_${c}.png`);
    }
  }
  create() {
    // walk animations for every character sheet
    const keys = ["player", ...NAMES.flatMap(n => COLORS.map(c => `ch_${n}_${c}`))];
    for (const k of keys) DIRS.forEach((d, r) => this.anims.create({
      key: `${k}-${d}`, frames: this.anims.generateFrameNumbers(k, { start: r * 4, end: r * 4 + 3 }), frameRate: 8, repeat: -1,
    }));
    // tiny particle textures
    const tex = (key, w, h, color) => { const g = this.make.graphics({ add: false }); g.fillStyle(color); g.fillRect(0, 0, w, h); g.generateTexture(key, w, h); g.destroy(); };
    tex("px_petal", 2, 2, 0xf6b8d2); tex("px_leaf", 3, 2, 0xd9772e); tex("px_snow", 2, 2, 0xffffff);
    tex("px_drop", 1, 2, 0x8fc7f0); tex("px_spark", 1, 1, 0xfff3b0); tex("px_pollen", 1, 1, 0xf6e27a);
    this.scene.start("world");
    this.scene.launch("hud");
  }
}

/* ===================================================================== World */
class WorldScene extends Phaser.Scene {
  constructor() { super("world"); }
  init(data) { this.season = (data && data.season) || this.season || "spring"; }

  create() {
    this.cameras.main.setBackgroundColor("#1d2a22");
    this.buildMap();
    this.dyn = new Map();          // snapshot object id -> sprite
    this.plotSprites = {};
    this.fog = this.add.graphics().setDepth(9000);
    this.fogMarks = [];
    this.player = this.add.sprite(0, 0, "player", 0).setOrigin(.5, 1);
    this.player.dir = "down";
    this.placeChar(this.player, this.loc("farm").anchor);
    this.cameras.main.setBounds(0, 0, MAPW * TILE, MAPH * TILE).setZoom(ZOOM).startFollow(this.player, true, .12, .12);
    this.cameras.main.roundPixels = true;
    this.overview = false;
    this.light = this.add.rectangle(0, 0, MAPW * TILE, MAPH * TILE, 0xffffff).setOrigin(0).setDepth(9500)
      .setBlendMode(Phaser.BlendModes.MULTIPLY);
    this.glows = this.lampPositions.map(([x, y]) => this.add.image(x, y, "obj", "light").setDepth(9600)
      .setBlendMode(Phaser.BlendModes.ADD).setTint(0xffc86a).setAlpha(0).setScale(1.1));
    this.windowGlows = this.windowPositions.map(([x, y]) => this.add.image(x, y, "obj", "light").setDepth(9600)
      .setBlendMode(Phaser.BlendModes.ADD).setTint(0xffb050).setAlpha(0).setScale(.45));
    this.time.addEvent({ delay: 650, loop: true, callback: () => this.animateWater() });
    this.time.addEvent({ delay: 220, loop: true, callback: () => { this.fountainFrame = ((this.fountainFrame || 0) + 1) % 3; this.fountain && this.fountain.setFrame(`fountain${this.fountainFrame}`); } });
    this.input.on("pointerdown", p => this.onPointer(p, "down"));
    this.input.on("pointermove", p => this.onPointer(p, "move"));
    this.input.on("gameout", () => UI.hideTip());
    this.game.events.emit("world-ready", this);
  }

  /* ---------- static world from the Tiled map */
  buildMap() {
    const map = this.make.tilemap({ key: "town" });
    const ts = map.addTilesetImage("terrain", `terrain_${this.season}`);
    this.ground = map.createLayer("ground", ts, 0, 0).setDepth(-20);
    map.createLayer("decor", ts, 0, 0).setDepth(-19);
    this.waterTiles = [];
    this.ground.forEachTile(t => { if (t.index >= 49 && t.index < 65) this.waterTiles.push(t); });
    const P = `props_${this.season}`, B = `bld_${this.season}`;
    this.locs = {}; this.blocked = new Set(); this.lampPositions = []; this.windowPositions = []; this.mapPlots = [];
    const block = (tx, ty) => this.blocked.add(tx + "," + ty);
    const prop = o => Object.fromEntries((o.properties || []).map(p => [p.name, p.value]));
    for (const o of map.getObjectLayer("objects").objects) {
      const pr = prop(o), tx = Math.round(o.x / TILE), ty = Math.round(o.y / TILE);
      switch (o.type) {
        case "location": {
          const pts = s => (s || "").split(";").filter(Boolean).map(p => p.split(",").map(Number));
          this.locs[o.name] = { name: o.name, rect: [tx, ty, o.width / TILE, o.height / TILE],
            anchor: pts(pr.anchor)[0], label: pts(pr.label)[0], items: pts(pr.items), people: pts(pr.people) };
          break;
        }
        case "building": {
          const img = this.add.image(o.x, o.y + TILE, B, pr.sprite).setOrigin(0, 1).setDepth(o.y + TILE);
          img.buildingName = o.name;
          for (let x = 0; x < o.width / TILE; x++) for (let y = 0; y < o.height / TILE; y++) block(tx + x, ty - y);
          const w = img.width;  // windows on the front wall, for evening light
          this.windowPositions.push([o.x + 14, o.y + TILE - 22], [o.x + w - 14, o.y + TILE - 22]);
          if (o.name === "farmhouse") this.farmhouse = img;
          break;
        }
        case "fountain":
          this.fountain = this.add.image(o.x, o.y + TILE, "obj", "fountain0").setOrigin(0, 1).setDepth(o.y + TILE);
          for (let x = 0; x < 3; x++) for (let y = 0; y < 2; y++) block(tx + x, ty - y);
          break;
        case "lamppost":
          this.add.image(o.x, o.y, "obj", "lamppost").setOrigin(0, 1).setDepth(o.y);
          block(tx, ty - 1); this.lampPositions.push([o.x + 8, o.y - 24]);
          break;
        case "prop":
          this.add.image(o.x, o.y + TILE, "obj", pr.sprite).setOrigin(0, 1).setDepth(o.y + TILE);
          for (let x = 0; x < (+pr.w || 1); x++) block(tx + x, ty);
          break;
        case "plaza_decor": {
          const f = pr.sprite === "bench" ? "bench_green" : "flowerbed_red";
          this.add.image(o.x, o.y, "obj", f).setOrigin(0, 1).setDepth(o.y);
          block(tx, ty - 1); block(tx + 1, ty - 1);
          break;
        }
        case "fence_h": case "fence_v":
          this.add.image(o.x, o.y + TILE, "obj", o.type === "fence_h" ? "fence_h" : "fence_v").setOrigin(0, 1).setDepth(o.y + TILE - 4);
          block(tx, ty);
          break;
        case "plot":
          this.mapPlots.push([o.x, o.y]);
          break;
        case "tree": {
          const big = pr.sprite.startsWith("oak") || pr.sprite.startsWith("pine");
          this.add.image(o.x + 8, o.y, P, pr.sprite).setOrigin(.5, 1).setDepth(o.y);
          block(tx, ty - 1);
          if (big && pr.sprite.startsWith("oak")) { /* canopy overlaps neighbours visually only */ }
          break;
        }
      }
    }
    this.ground.forEachTile(t => { if (t.index >= 49 && t.index < 81) block(t.x, t.y); });
  }

  animateWater() {
    for (const t of this.waterTiles) t.index = t.index < 65 ? t.index + 16 : t.index - 16;
  }

  loc(name) { return this.locs[name] || this.locs.plaza; }
  tileCenter([tx, ty]) { return [tx * TILE + 8, ty * TILE + TILE - 1]; }
  placeChar(s, tile) { const [x, y] = this.tileCenter(tile); s.setPosition(x, y).setDepth(y); s.tile = [...tile]; }

  /* ---------- pathfinding (BFS on the walk grid) */
  walkable(x, y) { return x >= 0 && y >= 0 && x < MAPW && y < MAPH && !this.blocked.has(x + "," + y); }
  path(from, to) {
    const key = p => p[0] + "," + p[1];
    if (key(from) === key(to)) return [];
    const prev = new Map([[key(from), null]]), q = [from];
    while (q.length) {
      const c = q.shift();
      if (key(c) === key(to)) break;
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const n = [c[0] + dx, c[1] + dy];
        if (prev.has(key(n)) || (!this.walkable(...n) && key(n) !== key(to))) continue;
        prev.set(key(n), c); q.push(n);
      }
    }
    if (!prev.has(key(to))) return [to];
    const out = []; let c = to;
    while (key(c) !== key(from)) { out.push(c); c = prev.get(key(c)); }
    return out.reverse();
  }
  async walk(sprite, to, speed) {
    const steps = this.path(sprite.tile || to, to);
    const key = sprite.texture.key;
    for (const st of steps) {
      const [x, y] = this.tileCenter(st);
      const dx = x - sprite.x, dy = y - sprite.y;
      const dir = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "right" : "left") : (dy > 0 ? "down" : "up");
      if (sprite.dir !== dir || !sprite.anims.isPlaying) sprite.play(`${key}-${dir}`, true);
      sprite.dir = dir;
      const dur = reduceMotion ? 0 : Math.max(18, 85 / speed);
      await new Promise(r => this.tweens.add({ targets: sprite, x, y, duration: dur, onUpdate: () => sprite.setDepth(sprite.y), onComplete: r }));
      sprite.tile = st;
    }
    this.idle(sprite);
  }
  idle(sprite) { sprite.anims.stop(); sprite.setFrame(DIRS.indexOf(sprite.dir || "down") * 4); }
  face(sprite, tile) {
    const dx = tile[0] - sprite.tile[0], dy = tile[1] - sprite.tile[1];
    sprite.dir = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "right" : "left") : (dy > 0 ? "down" : dy < 0 ? "up" : sprite.dir);
    this.idle(sprite);
  }
  standNear(tile, w = 1, h = 1) {
    const from = this.player.tile, cands = [];
    for (let x = tile[0] - 1; x <= tile[0] + w; x++) for (let y = tile[1] - 1; y <= tile[1] + h; y++) {
      const inside = x >= tile[0] && x < tile[0] + w && y >= tile[1] && y < tile[1] + h;
      if (!inside && this.walkable(x, y)) cands.push([x, y]);
    }
    cands.sort((a, b) => (Math.abs(a[0] - from[0]) + Math.abs(a[1] - from[1])) - (Math.abs(b[0] - from[0]) + Math.abs(b[1] - from[1])));
    return cands[0] || tile;
  }

  /* ---------- layout of snapshot objects onto the map */
  layout(state) {
    const pos = {}, counts = {};
    const plots = state.objects.filter(o => o.kind === "plot");
    plots.forEach((p, i) => { const mp = this.mapPlots[i % this.mapPlots.length]; pos[p.id] = { plot: true, x: mp[0], y: mp[1], tile: [mp[0] / TILE, mp[1] / TILE] }; });
    for (const o of state.objects) {
      if (o.kind === "plot" || o.kind === "bed" || !this.locs[o.location]) continue;
      const L = this.locs[o.location];
      const isPerson = o.kind === "villager";
      const list = isPerson ? L.people : L.items;
      const k = (counts[o.location + isPerson] = (counts[o.location + isPerson] || 0) + 1) - 1;
      const t = list[k % list.length], lap = Math.floor(k / list.length);
      pos[o.id] = { tile: t, x: t[0] * TILE + 8 + lap * 5, y: t[1] * TILE + TILE - 1 - lap * 3 };
    }
    return pos;
  }

  spriteFor(o) {
    if (o.kind === "villager") {
      const s = this.add.sprite(0, 0, charKey(o), 0).setOrigin(.5, 1);
      s.dir = "down"; s.villager = true;
      s.hearts = this.add.container(0, 0).setDepth(9400);
      return s;
    }
    const f = frameFor(o);
    if (!f) return null;
    const s = this.add.image(0, 0, "obj", f).setOrigin(.5, 1);
    if (o.for_sale) {
      s.tag = this.add.text(0, 0, `${o.price}g`, { fontFamily: "Pixelify Sans", fontSize: "6px", color: "#fff3c4", stroke: "#3a2312", strokeThickness: 2 }).setOrigin(.5, 0).setResolution(4);
    }
    return s;
  }

  syncPlots(state) {
    const plots = state.objects.filter(o => o.kind === "plot");
    plots.forEach((p, i) => {
      const [x, y] = this.mapPlots[i % this.mapPlots.length];
      let ps = this.plotSprites[p.id];
      if (!ps) {
        ps = this.plotSprites[p.id] = { base: this.add.image(x, y, "obj", "plot_dry").setOrigin(0).setDepth(-10), crops: [], tag: null };
        for (let k = 0; k < 4; k++) ps.crops.push(this.add.image(x + (k % 2) * 16 + 8, y + Math.floor(k / 2) * 16 + 18, "obj", "crop_turnip_planted").setOrigin(.5, 1).setVisible(false));
      }
      ps.base.setFrame(p.watered ? "plot_wet" : "plot_dry");
      ps.crops.forEach(c => {
        if (p.crop && p.status !== "empty") { c.setFrame(`crop_${p.crop}_${p.status === "growing" ? "growing" : p.status}`).setVisible(true).setDepth(c.y); }
        else c.setVisible(false);
      });
      if (p.seen && !ps.tag) {
        const col = { loam: "#6b4429", clay: "#b5653a", sand: "#e0c48a", peat: "#2a2018" }[p.soil] || "#888";
        ps.tag = this.add.container(x + 30, y + 2).setDepth(y + 2);
        ps.tag.add(this.add.rectangle(0, 0, 9, 7, 0x6e4428).setOrigin(.5).setStrokeStyle(1, 0x2e1a10));
        ps.tag.add(this.add.rectangle(0, 0, 5, 3, Phaser.Display.Color.HexStringToColor(col).color));
        ps.tag.add(this.add.rectangle(0, 6, 1, 6, 0x4d2d1a));
      }
    });
  }

  /** Make the scene match a snapshot. ``moves`` lets villagers walk instead of teleporting. */
  async sync(state, { instant = false, speed = 1 } = {}) {
    this.state = state;
    const pos = this.layout(state);
    const seen = new Set();
    const walks = [];
    for (const o of state.objects) {
      const p = pos[o.id];
      if (!p || p.plot) continue;
      seen.add(o.id);
      let s = this.dyn.get(o.id);
      if (s && s.villager && s.texture.key !== charKey(o)) { s.hearts.destroy(); s.destroy(); s = null; }
      if (!s) { s = this.spriteFor(o); if (!s) continue; this.dyn.set(o.id, s); s.setPosition(p.x, p.y); s.tile = p.tile; }
      s.obj = o;
      if (s.villager) {
        const moved = s.tile && (s.tile[0] !== p.tile[0] || s.tile[1] !== p.tile[1]);
        if (moved && !instant && !reduceMotion) walks.push(this.walk(s, p.tile, speed * 1.4));
        else { s.setPosition(p.x, p.y); s.tile = p.tile; }
        this.drawHearts(s, o, state);
      } else {
        s.setPosition(p.x, p.y);
      }
      s.setDepth(s.y + (s.villager ? 0 : -6));
      const hidden = !this.isVisited(state, o.location);
      s.setVisible(!hidden);
      if (s.tag) s.tag.setPosition(p.x, p.y + 1).setDepth(s.depth + 1).setVisible(!hidden);
    }
    for (const [id, s] of this.dyn) if (!seen.has(id)) { if (s.hearts) s.hearts.destroy(); if (s.tag) s.tag.destroy(); s.destroy(); this.dyn.delete(id); }
    this.syncPlots(state);
    this.drawFog(state);
    this.setLight(state.phase, instant);
    if (walks.length) await Promise.all(walks);
  }

  isVisited(state, loc) { const r = state.rooms.find(r => r.id === loc); return !r || r.visited; }

  drawHearts(s, o, state) {
    s.hearts.removeAll(true);
    const goal = o.id === state.goal_villager && !state.done;
    if (goal) {
      const b = this.add.image(0, -36, "ui", "emote_bang").setOrigin(.5);
      s.hearts.add(b);
      this.tweens.add({ targets: b, y: -38, yoyo: true, repeat: -1, duration: 500 });
    }
    s.hearts.setPosition(s.x, s.y);
  }

  drawFog(state) {
    this.fog.clear();
    this.fogMarks.forEach(m => m.destroy()); this.fogMarks = [];
    for (const r of state.rooms) {
      if (r.visited || !this.locs[r.id]) continue;
      const [x, y, w, h] = this.locs[r.id].rect;
      this.fog.fillStyle(0x14181e, .32).fillRect(x * TILE, y * TILE, w * TILE, h * TILE);
      const [lx, ly] = this.locs[r.id].label;
      const q = this.add.image(lx * TILE, ly * TILE + 20, "ui", "emote_q").setDepth(9001);
      this.tweens.add({ targets: q, y: q.y - 3, yoyo: true, repeat: -1, duration: 700 });
      this.fogMarks.push(q);
    }
  }

  setLight(phase, instant) {
    const color = { morning: 0xfff1dc, midday: 0xffffff, evening: 0xa58fc0 }[phase] || 0xffffff;
    this.light.setFillStyle(color);
    const on = phase === "evening" ? 1 : 0;
    this.tweens.add({ targets: [...this.glows, ...this.windowGlows], alpha: on ? .85 : 0, duration: instant ? 0 : 600 });
  }

  update() {
    for (const s of this.dyn.values()) if (s.hearts) s.hearts.setPosition(s.x, s.y);
  }

  /* ---------- little effects */
  emote(target, frame, ms = 900) {
    const e = this.add.image(target.x, target.y - 34, "ui", frame).setDepth(9450).setScale(.01);
    this.tweens.add({ targets: e, scale: 1, duration: reduceMotion ? 0 : 140, ease: "Back.out" });
    this.time.delayedCall(ms, () => this.tweens.add({ targets: e, alpha: 0, duration: 200, onComplete: () => e.destroy() }));
  }
  flyTo(frame, from, to, ms = 380) {
    const s = this.add.image(from.x, from.y - 8, "obj", frame).setOrigin(.5, 1).setDepth(9300);
    return new Promise(r => this.tweens.add({ targets: s, x: to.x, y: to.y - 18, duration: reduceMotion ? 0 : ms, ease: "Quad.in",
      onComplete: () => { s.destroy(); r(); } }));
  }
  burst(x, y, key, n = 12, opts = {}) {
    const em = this.add.particles(x, y, key, Object.assign({ speed: { min: 20, max: 60 }, lifespan: 500, quantity: n, emitting: false, gravityY: 120 }, opts)).setDepth(9350);
    em.explode(n);
    this.time.delayedCall(1200, () => em.destroy());
  }

  /* ---------- input (play mode + hover) */
  pick(wx, wy) {
    const st = this.state; if (!st) return null;
    let best = null;
    for (const [id, s] of this.dyn) {
      if (!s.visible) continue;
      const b = s.getBounds();
      if (b.contains(wx, wy) && (!best || s.depth > best.depth)) best = { id, depth: s.depth };
    }
    if (best) return { obj: best.id };
    for (const [id, ps] of Object.entries(this.plotSprites)) if (ps.base.getBounds().contains(wx, wy)) return { obj: id };
    if (this.farmhouse && this.farmhouse.getBounds().contains(wx, wy)) return { house: "farm" };
    const tx = Math.floor(wx / TILE), ty = Math.floor(wy / TILE);
    for (const L of Object.values(this.locs)) {
      const [x, y, w, h] = L.rect;
      if (tx >= x && tx < x + w && ty >= y && ty < y + h) return { loc: L.name };
    }
    return null;
  }
  onPointer(p, type) {
    const hit = this.pick(p.worldX, p.worldY);
    if (type === "move") UI.tip(hit, p.event); else UI.click(hit, p.event);
  }

  toggleOverview() {
    const cam = this.cameras.main;
    this.overview = !this.overview;
    if (this.overview) {
      cam.stopFollow(); cam.removeBounds();
      const z = Math.min(GW / (MAPW * TILE), GH / (MAPH * TILE));
      cam.zoomTo(z, 500); cam.pan(MAPW * TILE / 2, MAPH * TILE / 2, 500);
    } else {
      cam.setBounds(0, 0, MAPW * TILE, MAPH * TILE);
      cam.zoomTo(ZOOM, 500); cam.startFollow(this.player, true, .12, .12);
    }
    this.game.events.emit("overview", this.overview);
  }
}

/* ===================================================================== HUD */
class HudScene extends Phaser.Scene {
  constructor() { super("hud"); }
  create() {
    const T = (x, y, s, size, color = "#3a2312", font = "VT323") => this.add.text(x, y, s, { fontFamily: font, fontSize: size + "px", color }).setResolution(2);
    // quest panel (top-left)
    this.qPanel = this.add.nineslice(10, 10, "ui", "panel", 300, 118, 7, 7, 7, 7).setOrigin(0);
    this.qTitle = T(26, 20, "QUEST", 14, "#6e4b2c", "Pixelify Sans");
    this.qText = T(26, 38, "", 22).setWordWrapWidth(270);
    this.qNeeds = this.add.container(26, 66);
    // clock (top-right)
    this.cPanel = this.add.nineslice(GW - 10, 10, "ui", "panel", 214, 112, 7, 7, 7, 7).setOrigin(1, 0);
    this.cDay = T(GW - 200, 20, "", 22, "#3a2312", "Pixelify Sans");
    this.cIcon = this.add.image(GW - 188, 60, "ui", "sun").setScale(2);
    this.cPhase = T(GW - 172, 48, "", 24);
    this.ticks = [];
    for (let i = 0; i < 12; i++) this.ticks.push(this.add.rectangle(GW - 200 + i * 15.5, 86, 12, 7, 0xe5c588).setOrigin(0, .5));
    this.coinBox = this.add.nineslice(GW - 10, 126, "ui", "panel", 140, 40, 7, 7, 7, 7).setOrigin(1, 0);
    this.add.image(GW - 132, 146, "obj", "coin").setScale(1.5);
    this.coins = T(GW - 116, 132, "0", 26, "#3a2312", "VT323");
    // energy = action budget (bottom-right)
    this.eFrame = this.add.nineslice(GW - 14, GH - 14, "ui", "panel", 34, 150, 7, 7, 7, 7).setOrigin(1, 1);
    this.eBar = this.add.rectangle(GW - 31, GH - 24, 14, 128, 0x6aa84f).setOrigin(.5, 1);
    this.eLabel = T(GW - 38, GH - 182, "E", 22, "#f1d9a7", "Pixelify Sans");
    // toolbar (bottom-center)
    this.slots = [];
    const sx = GW / 2 - 12 * 21;
    this.tbPanel = this.add.nineslice(GW / 2, GH - 8, "ui", "panel", 12 * 42 + 22, 62, 7, 7, 7, 7).setOrigin(.5, 1);
    for (let i = 0; i < 12; i++) {
      const x = sx + i * 42 + 21, y = GH - 39;
      this.add.image(x, y, "ui", "slot").setScale(2);
      const icon = this.add.image(x, y, "obj", "coin").setScale(2).setVisible(false);
      const n = T(x + 8, y + 4, "", 16, "#3a2312");
      this.slots.push({ icon, n });
    }
    // dialogue (above toolbar)
    this.dlg = this.add.container(0, 0).setVisible(false);
    const dw = 600, dh = 108, dx = GW / 2 - dw / 2, dy = GH - 76 - dh;
    this.dlg.add(this.add.nineslice(dx, dy, "ui", "panel", dw, dh, 7, 7, 7, 7).setOrigin(0));
    this.dlg.add(this.add.nineslice(dx + dw - 104, dy + 8, "ui", "slot", 92, 92, 4, 4, 4, 4).setOrigin(0));
    this.portrait = this.add.image(dx + dw - 58, dy + 52, "pt_player").setScale(1.75);
    this.dlg.add(this.portrait);
    this.dlgName = T(dx + dw - 58, dy + dh - 2, "", 16, "#fff3c4", "Pixelify Sans").setOrigin(.5, 1).setStroke("#3a2312", 4);
    this.dlg.add(this.dlgName);
    this.dlgAct = T(dx + 18, dy + 12, "", 15, "#8a6a44", "Pixelify Sans");
    this.dlgText = T(dx + 18, dy + 30, "", 21).setWordWrapWidth(dw - 140).setLineSpacing(-3);
    this.dlg.add([this.dlgAct, this.dlgText]);
    // banner (location name)
    this.banner = this.add.container(GW / 2, 34).setAlpha(0);
    this.banner.add(this.add.nineslice(0, 0, "ui", "panel", 260, 44, 7, 7, 7, 7));
    this.bannerText = T(0, 0, "", 22, "#3a2312", "Pixelify Sans").setOrigin(.5);
    this.banner.add(this.bannerText);
    // day card
    this.dayCard = T(GW / 2, GH / 2 - 30, "", 48, "#f2b632", "Pixelify Sans").setOrigin(.5).setStroke("#3a2312", 8).setAlpha(0);
    // location labels for the map overview
    this.labels = {};
    // weather
    this.weather = null;
    this.game.events.on("state", (s, opts) => this.render(s, opts), this);
    this.game.events.on("say", d => this.say(d), this);
    this.game.events.on("banner", t => this.showBanner(t), this);
    this.game.events.on("daycard", t => this.showDay(t), this);
    this.game.events.on("overview", on => this.showLabels(on), this);
    this.game.events.emit("hud-ready", this);
  }

  setWeather(season) {
    if (this.weatherSeason === season) return;
    this.weatherSeason = season;
    if (this.weather) this.weather.destroy();
    const cfg = {
      spring: ["px_petal", { speedY: { min: 14, max: 26 }, speedX: { min: 6, max: 22 }, frequency: 260, scale: 2 }],
      summer: ["px_pollen", { speedY: { min: -6, max: 6 }, speedX: { min: -8, max: 8 }, frequency: 300, scale: 3, alpha: { start: 1, end: 0 } }],
      fall: ["px_leaf", { speedY: { min: 18, max: 34 }, speedX: { min: -16, max: 12 }, frequency: 180, scale: 2, rotate: { min: 0, max: 360 } }],
      winter: ["px_snow", { speedY: { min: 16, max: 34 }, speedX: { min: -8, max: 8 }, frequency: 60, scale: { min: 1, max: 2 } }],
    }[season];
    if (!cfg || reduceMotion) return;
    this.weather = this.add.particles(0, 0, cfg[0], Object.assign({ x: { min: 0, max: GW }, y: season === "summer" ? { min: 0, max: GH } : -6, lifespan: 16000 }, cfg[1])).setDepth(-1);
  }

  render(s) {
    if (!s) return;
    this.setWeather(s.season);
    // quest
    const v = s.objects.find(o => o.id === s.goal_villager);
    this.qText.setText(v ? `Get the trophy from ${v.name}` : "No quest");
    this.qNeeds.removeAll(true);
    let y = 0;
    const row = (txt, ok, hearts) => {
      this.qNeeds.add(this.add.text(0, y, (ok ? "✔ " : "• ") + txt, { fontFamily: "VT323", fontSize: "19px", color: ok ? "#3d7a26" : "#6e4b2c" }).setResolution(2));
      if (hearts !== undefined) for (let k = 0; k < 2; k++) this.qNeeds.add(this.add.image(150 + k * 14, y + 10, "ui", k < hearts ? "heart" : "heart_empty").setScale(1.4));
      y += 18;
    };
    if (v) {
      if (s.blocks.includes("gifting")) row("Friendship", v.friendship >= 2, Math.min(2, v.friendship));
      if (s.blocks.includes("farming")) row("Bring a fresh crop", v.got_crop);
      if (v.request) row("Bring what they asked for", v.got_request);
      if (s.blocks.includes("schedule")) row("Find them (they move)", s.done);
      if (s.done) row("Trophy in hand!", true);
    }
    this.qPanel.height = Math.max(90, 70 + y);
    // clock
    this.cDay.setText(`Day ${s.day}, ${cap(s.season)}`);
    this.cPhase.setText(cap(s.phase));
    this.cIcon.setFrame(s.phase === "evening" ? "moon" : "sun");
    this.ticks.forEach((t, i) => t.setFillStyle(i < s.tick ? 0xb08a5a : i === s.tick ? 0xf2b632 : (i < 4 ? 0xf6d89a : i < 8 ? 0xf2c46a : 0xc9a0c8)));
    this.coins.setText(String(s.coins));
    const frac = s.max_actions >= 1000 ? 1 : Math.max(0, 1 - s.actions / s.max_actions);
    this.eBar.height = 128 * frac;
    this.eBar.setFillStyle(frac > .5 ? 0x6aa84f : frac > .2 ? 0xe8c23a : 0xc0392b);
    // toolbar
    this.slots.forEach((sl, i) => {
      const id = s.inventory[i], o = id && s.objects.find(x => x.id === id);
      const f = o && frameFor(o);
      sl.icon.setVisible(!!f); if (f) sl.icon.setFrame(f);
      sl.n.setText(o && o.kind === "seeds" ? String(o.uses) : "");
    });
  }

  say({ action, message, who, kind }) {
    const text = cleanMessage(message, kind);
    if (!text && !action) { this.dlg.setVisible(false); return; }
    this.dlg.setVisible(true);
    this.dlgAct.setText(action || "");
    const key = who ? `pt_${who.name}_${who.color}` : "pt_player";
    this.portrait.setTexture(this.textures.exists(key) ? key : "pt_player");
    this.dlgName.setText(who ? who.name : "You");
    const lines = text.split("\n");
    const shown = lines.length > 4 ? lines.slice(0, 4).join("\n") + " …" : text;
    if (this.typer) this.typer.remove();
    if (reduceMotion || Director.speed > 3) { this.dlgText.setText(shown); return; }
    let i = 0;
    this.dlgText.setText("");
    this.typer = this.time.addEvent({ delay: 12, repeat: shown.length - 1, callback: () => this.dlgText.setText(shown.slice(0, ++i)) });
  }

  showBanner(t) {
    this.bannerText.setText(t);
    this.tweens.killTweensOf(this.banner);
    this.banner.setAlpha(1);
    this.tweens.add({ targets: this.banner, alpha: 0, delay: 1300, duration: 500 });
  }
  showDay(t) {
    this.dayCard.setText(t).setAlpha(1);
    this.tweens.add({ targets: this.dayCard, alpha: 0, delay: 700, duration: 500 });
  }
  showLabels(on) {
    Object.values(this.labels).forEach(l => l.destroy()); this.labels = {};
    [this.dlg, this.qPanel, this.qTitle, this.qText, this.qNeeds].forEach(o => o.setAlpha(on ? 0 : 1));
    if (!on) return;
    const w = this.scene.get("world");
    const cam = w.cameras.main;
    this.time.delayedCall(520, () => {
      for (const L of Object.values(w.locs)) {
        const r = w.state && w.state.rooms.find(x => x.id === L.name);
        if (!r) continue;
        const sx = (L.label[0] * TILE - cam.worldView.x) * cam.zoom, sy = (L.label[1] * TILE - cam.worldView.y) * cam.zoom;
        this.labels[L.name] = this.add.text(sx, sy + 6, (r.visited ? "" : "? ") + cap(r.name.replace(/^the /, "").replace(/'s house$/, "'s")), { fontFamily: "Pixelify Sans", fontSize: "15px", color: "#fff3c4", stroke: "#2a1a10", strokeThickness: 4 }).setOrigin(.5, 0).setResolution(2);
      }
    });
  }
}

/* ===================================================================== Director */
const Director = {
  game: null, world: null, hud: null,
  frames: [], idx: 0, playing: false, speed: 1, busy: false, replay: null, live: false,
  skipZooms: false,

  async ready() {
    if (this.world && this.hud) return;
    await new Promise(r => { const t = setInterval(() => { if (this.world && this.hud) { clearInterval(t); r(); } }, 30); });
  },
  async ensureSeason(season) {
    if (this.world.season === season) return;
    const done = new Promise(r => this.game.events.once("world-ready", w => { this.world = w; r(); }));
    this.world.scene.restart({ season });
    await done;
  },
  who(state, action) {
    const { args } = parseAction(action);
    return state.objects.find(o => o.kind === "villager" && args.includes(o.id));
  },

  /** Show a state without animation (jumps, scrubbing, first frame). */
  async show(frame) {
    const s = frame.state;
    await this.ensureSeason(s.season);
    const w = this.world;
    w.placeChar(w.player, w.loc(s.agent_room).anchor);
    w.player.dir = "down"; w.idle(w.player);
    await w.sync(s, { instant: true });
    this.game.events.emit("state", s);
    const msg = frame.kind === "start" && this.replay ? `${frame.action ? "" : "A new day in SeedVille. "}Goal: get the trophy from ${(s.objects.find(o => o.id === s.goal_villager) || {}).name}.` : frame.message;
    this.game.events.emit("say", { action: frame.kind === "start" ? "" : frame.action, message: msg, kind: frame.kind, who: this.who(s, frame.action) });
  },

  /** Animate from prev state to frame (the heart of the presentation). */
  async animate(prev, frame) {
    const s = frame.state, w = this.world, sp = this.speed;
    if (!prev || prev.season !== s.season) return this.show(frame);
    const { verb, args } = parseAction(frame.action);
    const P = w.player;
    const objPrev = id => prev.objects.find(o => o.id === id);
    const spriteOf = id => w.dyn.get(id) || (w.plotSprites[id] && w.plotSprites[id].base);
    const target = args[0], instr = args[1];
    const dayChanged = s.day !== prev.day;
    this.game.events.emit("say", { action: frame.action, message: frame.message, kind: frame.kind, who: this.who(s, frame.action) || this.who(prev, frame.action) });

    // 1. walk
    if (frame.kind === "act" && verb === "go" && target) {
      const dest = dayChanged ? prev.agent_room : s.agent_room;
      await w.walk(P, w.loc(dest).anchor, sp);
      this.game.events.emit("banner", cap((s.rooms.find(r => r.id === dest) || {}).name || dest));
    } else if ((frame.kind === "act" || frame.kind === "inspect") && target && objPrev(target)) {
      const o = objPrev(target), spr = spriteOf(target);
      if (spr && (o.location === prev.agent_room || o.kind === "plot")) {
        const isPlot = o.kind === "plot";
        const tile = isPlot ? [Math.round(spr.x / TILE), Math.round(spr.y / TILE)] : spr.tile;
        if (tile) { await w.walk(P, w.standNear(tile, isPlot ? 2 : 1, isPlot ? 2 : 1), sp); w.face(P, tile); }
      }
    } else if (verb === "sleep") {
      await w.walk(P, w.loc("farm").anchor, sp);
    }

    // 2. effect
    const tS = target && spriteOf(target);
    const delay = ms => sleep(reduceMotion ? 0 : ms / sp);
    if (frame.kind === "inspect" && tS) { w.emote(tS, "emote_q", 700 / sp); await delay(350); }
    else if (frame.kind === "think") { w.emote(P, "emote_dots", 700 / sp); await delay(300); }
    else if (frame.kind === "act") {
      const failed = frame.ok === false;
      if ((verb === "take" || verb === "buy") && tS && !failed) { await w.flyTo(tS.frame.name, tS, P); }
      else if (verb === "plant" && tS && !failed) { w.burst(tS.x + 16, tS.y + 16, "px_spark", 8, { tint: 0x8a5a36 }); await delay(250); }
      else if (verb === "water" && tS && !failed) { w.burst(tS.x + 16, tS.y + 8, "px_drop", 22, { speed: { min: 10, max: 40 }, gravityY: 200, lifespan: 600 }); await delay(400); }
      else if (verb === "harvest" && tS) { w.burst(tS.x + 16, tS.y + 12, "px_spark", 16); await delay(300); }
      else if (verb === "give" && tS && instr) {
        const io = objPrev(instr);
        if (io) await w.flyTo(frameFor(io), P, tS);
        const liked = /loves|delighted|Exactly/.test(frame.message || "");
        w.emote(tS, liked ? "emote_heart" : "emote_dots", 1000 / sp);
        if (liked) w.burst(tS.x, tS.y - 30, "px_petal", 10, { tint: 0xe0457b, gravityY: -20 });
        await delay(500);
      }
      else if (verb === "talk" && tS) { w.emote(tS, s.done ? "emote_heart" : "emote_note", 900 / sp); await delay(400); }
      else if (verb === "wait") { w.emote(P, "emote_dots", 600 / sp); await delay(250); }
      if (failed && verb !== "give") { w.emote(P, "emote_bang", 700 / sp); w.cameras.main.shake(120, .002); await delay(250); }
    }

    // 3. night
    if (dayChanged) {
      if (verb !== "sleep") { w.emote(P, "emote_zzz", 600); await delay(400); }
      const cam = w.cameras.main;
      await new Promise(r => { cam.once("camerafadeoutcomplete", r); cam.fadeOut(reduceMotion ? 0 : 450 / Math.min(sp, 2), 10, 10, 30); });
      this.game.events.emit("daycard", `Day ${s.day}`);
      await w.sync(s, { instant: true });
      w.placeChar(P, w.loc(s.agent_room).anchor); P.dir = "down"; w.idle(P);
      this.game.events.emit("state", s);
      await sleep(reduceMotion ? 0 : 500 / Math.min(sp, 2));
      await new Promise(r => { cam.once("camerafadeincomplete", r); cam.fadeIn(reduceMotion ? 0 : 450 / Math.min(sp, 2), 10, 10, 30); });
      return;
    }
    // 4. settle the rest (villagers walk to their new places)
    this.game.events.emit("state", s);
    if (prev.phase !== s.phase) this.game.events.emit("banner", cap(s.phase));
    await w.sync(s, { speed: sp });
  },

  /* ---------- replay controls */
  load(replay) {
    this.stop();
    this.replay = replay; this.frames = replay.frames || []; this.idx = 0;
    UI.onReplay(replay);
    return this.show(this.frames[0]).then(() => UI.onStep(0));
  },
  visible(i) { return !(this.skipZooms && this.frames[i] && this.frames[i].kind !== "act" && i > 0); },
  async go(i, animate) {
    if (this.busy || !this.frames.length) return;
    i = Math.max(0, Math.min(this.frames.length - 1, i));
    this.busy = true;
    try {
      if (animate && i === this.idx + 1) await this.animate(this.frames[this.idx].state, this.frames[i]);
      else await this.show(this.frames[i]);
      this.idx = i; UI.onStep(i);
    } finally { this.busy = false; }
  },
  async next() {
    let j = this.idx + 1;
    while (j < this.frames.length && !this.visible(j)) {
      j++;
    }
    if (j >= this.frames.length) { this.stop(); return false; }
    if (j > this.idx + 1) { await this.show(this.frames[j - 1]); this.idx = j - 1; }
    await this.go(j, true);
    return true;
  },
  async play() {
    if (this.idx >= this.frames.length - 1) await this.go(0);
    this.playing = true; UI.onPlay(true);
    while (this.playing) {
      if (!(await this.next())) break;
      await sleep(reduceMotion ? 50 : 420 / this.speed);
    }
    this.playing = false; UI.onPlay(false);
  },
  stop() { this.playing = false; UI.onPlay(false); },

  /* ---------- live play (scripts/serve_ui.py) */
  liveState: null,
  async api(path, body) {
    const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error("server " + r.status);
    return r.json();
  },
  async startLive() {
    this.stop();
    const d = await this.api("api/state");
    this.liveState = d.state; UI.onLive(d);
    await this.show({ state: d.state, message: d.goal_text, action: "A new day in SeedVille" });
  },
  async liveAct(verb, target, instrument, kind = "act") {
    if (this.busy) return;
    this.busy = true;
    try {
      const path = kind === "inspect" ? "api/inspect" : "api/act";
      const d = await this.api(path, kind === "inspect" ? { target } : { verb, target, instrument });
      const action = kind === "inspect" ? `zoom_in(${target})` : `${verb}(${[target, instrument].filter(Boolean).join(", ")})`;
      await this.animate(this.liveState, { kind, action, message: d.message, state: d.state, ok: d.ok });
      this.liveState = d.state; UI.onLive(d, action);
    } catch (e) { UI.toast("The game server is not answering. Restart scripts/serve_ui.py and reload."); }
    finally { this.busy = false; }
  },
  async liveAuto(policy) {
    if (this.busy) return;
    this.busy = true;
    try {
      const d = await this.api("api/autoplay", { policy });
      for (const f of d.frames) { await this.animate(this.liveState, f); this.liveState = f.state; UI.onLive({ state: f.state }, f.action); await sleep(150 / this.speed); }
      this.liveState = d.state;
    } finally { this.busy = false; }
  },
  async liveNew(universe, blocks) {
    const d = await this.api("api/new", { universe, blocks });
    this.liveState = d.state; UI.onLive(d);
    await this.show({ state: d.state, message: d.goal_text, action: "A new town grows from its seed" });
  },
};

/* ===================================================================== DOM glue */
const UI = {
  $: id => document.getElementById(id),
  mode: "replay", replays: [], liveData: null,

  init() {
    const $ = this.$;
    $("bPlay").onclick = () => Director.playing ? Director.stop() : Director.play();
    $("bNext").onclick = () => { Director.stop(); Director.next(); };
    $("bPrev").onclick = () => { Director.stop(); Director.go(Director.idx - 1); };
    $("bFirst").onclick = () => { Director.stop(); Director.go(0); };
    $("bLast").onclick = () => { Director.stop(); Director.go(Director.frames.length - 1); };
    $("scrub").oninput = e => { Director.stop(); Director.go(+e.target.value); };
    $("speed").onchange = e => { Director.speed = +e.target.value; };
    Director.speed = +$("speed").value;
    $("skipZooms").onchange = e => { Director.skipZooms = e.target.checked; };
    $("bMap").onclick = () => Director.world && Director.world.toggleOverview();
    $("runs").onchange = e => Director.load(this.replays[+e.target.value]);
    $("fileIn").onchange = async e => {
      const f = e.target.files[0]; if (!f) return;
      try {
        const d = JSON.parse(await f.text());
        const list = (Array.isArray(d) ? d : [d]).filter(r => r.frames);
        if (!list.length) throw new Error("no frames");
        this.addReplays(list); $("runs").value = String(this.replays.length - 1);
        if (this.mode !== "replay") this.setMode("replay");
        Director.load(this.replays[this.replays.length - 1]);
      } catch (err) { this.toast("That file is not a SeedVille replay. Make one with scripts/export_replay.py."); }
    };
    $("modeReplay").onclick = () => this.setMode("replay");
    $("modePlay").onclick = () => this.setMode("play");
    $("pWait").onclick = () => Director.liveAct("wait");
    $("pSleep").onclick = () => Director.liveAct("sleep");
    $("pOracle").onclick = () => Director.liveAuto("oracle");
    $("pExplorer").onclick = () => Director.liveAuto("explorer");
    $("pNew").onclick = () => Director.liveNew(+$("uni").value, ["farming", "gifting", "shop", "schedule"].filter(b => $("blk-" + b).checked));
    document.addEventListener("keydown", e => {
      if (["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
      if (e.key === "m" || e.key === "M") Director.world && Director.world.toggleOverview();
      if (this.mode !== "replay") return;
      if (e.key === "ArrowRight") { Director.stop(); Director.next(); }
      else if (e.key === "ArrowLeft") { Director.stop(); Director.go(Director.idx - 1); }
      else if (e.key === " ") { e.preventDefault(); Director.playing ? Director.stop() : Director.play(); }
    });
    document.addEventListener("click", e => { if (!e.target.closest("#menu") && e.target.tagName !== "CANVAS") this.hideMenu(); });
  },
  addReplays(list) {
    for (const r of list) this.replays.push(r);
    const sel = this.$("runs"); sel.innerHTML = "";
    this.replays.forEach((r, i) => {
      const acts = r.frames.filter(f => f.kind === "act").length;
      const o = document.createElement("option"); o.value = i;
      o.textContent = `${r.title} — ${r.success ? "solved" : "failed"} in ${acts} actions`;
      sel.appendChild(o);
    });
  },
  onReplay(r) {
    this.$("runDesc").textContent = r.description || "";
    const laws = this.$("laws"); laws.innerHTML = "";
    (r.laws || []).forEach(l => { const li = document.createElement("li"); li.textContent = l; laws.appendChild(li); });
    this.$("memory").textContent = r.memory || "Nothing. This agent starts from scratch.";
    this.$("scrub").max = Math.max(0, r.frames.length - 1);
  },
  onStep(i) {
    this.$("scrub").value = i;
    this.$("stepLabel").textContent = `${i} / ${Director.frames.length - 1}`;
  },
  onPlay(on) { const b = this.$("bPlay"); b.textContent = on ? "Pause" : "Play"; b.setAttribute("aria-label", on ? "Pause" : "Play"); },
  onLive(d) {
    this.liveData = Object.assign(this.liveData || {}, d);
    this.$("runDesc").textContent = "You are playing. Every click is a real action in the Python engine; the oracle or explorer can take over at any time.";
    if (d.laws) { const L = this.$("laws"); L.innerHTML = ""; d.laws.forEach(l => { const li = document.createElement("li"); li.textContent = l; L.appendChild(li); }); this.$("memory").textContent = "You. Learn the laws by trying things."; }
  },
  async setMode(m) {
    this.mode = m; this.hideMenu();
    this.$("modeReplay").classList.toggle("on", m === "replay"); this.$("modePlay").classList.toggle("on", m === "play");
    this.$("modeReplay").setAttribute("aria-pressed", m === "replay"); this.$("modePlay").setAttribute("aria-pressed", m === "play");
    this.$("replayBar").hidden = m !== "replay"; this.$("playBar").hidden = m !== "play";
    if (m === "play") await Director.startLive();
    else if (this.replays.length) await Director.load(this.replays[+this.$("runs").value || 0]);
  },
  toast(t) { const el = this.$("toast"); el.textContent = t; el.hidden = false; clearTimeout(this._tt); this._tt = setTimeout(() => el.hidden = true, 4000); },

  describe(hit) {
    const s = Director.world && Director.world.state; if (!s || !hit) return null;
    if (hit.loc) { const r = s.rooms.find(x => x.id === hit.loc); return r ? cap(r.name) + (r.visited ? "" : " (not visited yet)") : null; }
    if (hit.house) return "Your farmhouse (sleep here)";
    const o = s.objects.find(x => x.id === hit.obj); if (!o) return null;
    let t = o.label.replace(/^\S+\s/, "");
    if (o.kind === "villager") t = `${o.name}` + (o.seen ? `, the ${o.job}` : "") + ` · friendship ${o.friendship}`;
    if (o.kind === "plot") t = `Plot ${o.id}` + (o.seen ? ` · ${o.soil} soil` : " · soil unknown") + (o.crop ? ` · ${o.crop} (${o.status})` : "");
    return t;
  },
  tip(hit, ev) {
    const el = this.$("tip"), t = this.describe(hit);
    if (!t || !ev) { el.hidden = true; return; }
    const r = this.$("game").getBoundingClientRect();
    el.textContent = t; el.hidden = false;
    el.style.left = (ev.clientX - r.left) + "px"; el.style.top = (ev.clientY - r.top) + "px";
  },
  hideTip() { this.$("tip").hidden = true; },
  hideMenu() { this.$("menu").hidden = true; },

  click(hit, ev) {
    if (this.mode !== "play" || !hit || !ev) return;
    const s = Director.liveState; if (!s) return;
    const opts = [];
    const add = (label, fn) => opts.push([label, fn]);
    const A = (v, t, i) => () => Director.liveAct(v, t, i);
    if (hit.loc) { if (hit.loc !== s.agent_room) add(`Walk to ${cap((s.rooms.find(r => r.id === hit.loc) || {}).name || hit.loc)}`, A("go", hit.loc)); }
    else if (hit.house) { if (s.agent_room === "farm") add("Sleep until morning", A("sleep")); else add("Walk home", A("go", "farm")); }
    else {
      const o = s.objects.find(x => x.id === hit.obj);
      if (o) {
        const here = o.location === s.agent_room || o.location === "inv";
        if (!here && s.rooms.some(r => r.id === o.location)) add("Walk there", A("go", o.location));
        add("Look closer", () => Director.liveAct(null, o.id, null, "inspect"));
        if (here) {
          const held = s.inventory.map(id => s.objects.find(x => x.id === id));
          if (["item", "seeds", "tool", "crop"].includes(o.kind) && o.location !== "inv") add(o.for_sale ? `Buy for ${o.price}g` : "Pick up", A(o.for_sale ? "buy" : "take", o.id));
          if (o.kind === "villager") {
            add("Talk", A("talk", o.id));
            held.filter(h => h.kind === "item" || h.kind === "crop").forEach(h => add(`Give ${h.color} ${h.name}`, A("give", o.id, h.id)));
          }
          if (o.kind === "plot") {
            held.filter(h => h.kind === "seeds").forEach(h => add(`Plant ${h.crop}`, A("plant", o.id, h.id)));
            add("Water", A("water", o.id)); add("Harvest / clear", A("harvest", o.id));
          }
        }
      }
    }
    if (!opts.length) return;
    const m = this.$("menu"); m.innerHTML = "";
    for (const [label, fn] of opts) { const b = document.createElement("button"); b.type = "button"; b.textContent = label; b.onclick = () => { this.hideMenu(); fn(); }; m.appendChild(b); }
    const r = this.$("game").getBoundingClientRect();
    m.style.left = Math.min(ev.clientX - r.left, r.width - 200) + "px"; m.style.top = Math.min(ev.clientY - r.top, r.height - 40 * opts.length) + "px";
    m.hidden = false;
  },
};

/* ===================================================================== boot */
async function main() {
  try { await Promise.race([Promise.all([document.fonts.load('20px "Pixelify Sans"'), document.fonts.load('20px "VT323"')]), sleep(2500)]); } catch (e) { /* fallback fonts */ }
  UI.init();
  const game = new Phaser.Game({
    type: Phaser.AUTO, parent: "game", width: GW, height: GH, pixelArt: true, roundPixels: true,
    backgroundColor: "#1d2a22", scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_HORIZONTALLY },
    scene: [BootScene, WorldScene, HudScene],
  });
  Director.game = game;
  game.events.on("world-ready", w => { Director.world = w; });
  game.events.on("hud-ready", h => { Director.hud = h; });
  await Director.ready();

  let replays = [];
  try { const r = await fetch("replays/demo.json"); if (r.ok) replays = await r.json(); } catch (e) { /* none */ }
  if (Array.isArray(window.SEEDVILLE_REPLAYS)) replays = replays.concat(window.SEEDVILLE_REPLAYS);
  UI.addReplays(replays.filter(r => r.frames));
  let live = false;
  if (location.protocol.startsWith("http")) {
    try { const r = await fetch("api/state"); live = r.ok && (await r.json()).live; } catch (e) { live = false; }
  }
  UI.$("modePlay").disabled = !live;
  UI.$("modePlay").title = live ? "" : "Run scripts/serve_ui.py to play";
  if (live) UI.$("note").textContent = "Connected to the local game server: Play uses the real engine.";
  if (UI.replays.length) await Director.load(UI.replays[0]);
  else if (live) await UI.setMode("play");
}
main();
