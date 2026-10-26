/* AgentCity side by side: two DAG runs (web/replays/dag.json), each in its own embedded web/codeworld.html,
   played round by round in step. The page owns the clock; each side reports where it is (codeworld.js
   report()). The chart is drawn with plain attributes so "Save chart" gives a standalone SVG for a paper. */
"use strict";

const $ = id => document.getElementById(id);
const C = { left: "#d24a3a", right: "#2f7fd0", bound: "#6b778a", ref: "#2f9e5a", ink: "#1b2433", soft: "#4f5d73",
            grid: "#cdd6e3", task: "#2f9e5a", talk: "#e8b032", wait: "#9aa4b2", other: "#cdd6e3" };
const P = { runs: null, sel: { L: null, R: null }, ready: { L: false, R: false }, state: { L: null, R: null },
            round: 0, playing: false, timer: null, speed: 2, net: true };
const frame = side => $(side === "L" ? "fL" : "fR");
const send = (side, msg) => frame(side).contentWindow.postMessage(msg, "*");
const run = side => P.runs && P.runs[P.sel[side]];
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const short = r => r.title.replace(/ \(seed \d+\)$/, "");

/* the default pair: two designs on the same problem (same size and seed), else a team and its reference */
function defaults() {
  const q = new URLSearchParams(location.search), dag = P.runs.filter(r => r.dag);
  if (q.has("l") && q.has("r")) return [+q.get("l"), +q.get("r")];
  for (const a of dag) for (const b of dag)
    if (a.i < b.i && a.agents === b.agents && a.seed === b.seed && a.tasks === b.tasks &&
        !a.title.startsWith("reference") && !b.title.startsWith("reference")) return [a.i, b.i];
  const a = dag[0], b = a && dag.find(r => r.title === a.pair);
  return [a ? a.i : 0, b ? b.i : (dag[1] || a || { i: 0 }).i];
}

function maxRound() { return Math.max(...["L", "R"].map(s => run(s) ? run(s).rounds : 0)); }

function choose(side, k) {
  P.sel[side] = k; P.state[side] = null;
  $(side === "L" ? "selL" : "selR").value = k;
  if (P.ready[side]) { send(side, { type: "run", run: k }); send(side, { type: "speed", speed: P.speed });
    send(side, { type: "net", on: P.net }); send(side, { type: "round", round: P.round }); }
  $("scrub").max = maxRound();
  draw();
}

function go(r, animate) {
  P.round = Math.max(0, Math.min(r, maxRound()));
  for (const s of ["L", "R"]) if (P.ready[s]) send(s, { type: "round", round: P.round, animate });
  $("scrub").value = P.round;
  $("round").textContent = `round ${P.round} / ${maxRound()}`;
  draw();
}

function play(on) {
  P.playing = on; $("bPlay").textContent = on ? "Pause" : "Play"; $("bPlay").classList.toggle("on", on);
  clearInterval(P.timer);
  if (on) P.timer = setInterval(() => { if (P.round >= maxRound()) play(false); else go(P.round + 1, true); }, 1000 / P.speed);
}

window.addEventListener("message", e => {
  const m = e.data || {}, side = e.source === frame("L").contentWindow ? "L" : e.source === frame("R").contentWindow ? "R" : null;
  if (!side) return;
  if (m.type === "runs") {
    P.ready[side] = true;
    if (!P.runs) {
      P.runs = m.runs;
      const opts = P.runs.filter(r => r.dag).map(r => `<option value="${r.i}">${esc(r.title)}</option>`).join("");
      $("selL").innerHTML = opts; $("selR").innerHTML = opts;
      const [l, r] = defaults();
      P.sel = { L: l, R: r };
    }
    choose(side, P.sel[side]);
  } else if (m.type === "state") {
    P.state[side] = m;
    stats(side);
    split();
  }
});

/* ------------------------------------------------------------------ panels */
function stats(side) {
  const s = P.state[side], r = run(side); if (!s || !r) return;
  const acts = s.compute + s.submits + s.messages + s.inbox + s.reads + s.writes + s.waits + s.tools;
  const cell = (v, l) => `<div><b>${v}</b> <span>${l}</span></div>`;
  $(side === "L" ? "statsL" : "statsR").innerHTML = [
    cell(`${s.done}/${s.tasks}`, "tasks done"), cell(r.rounds, `rounds${r.reference ? ` (ref ${r.reference})` : ""}`),
    cell(s.messages, "messages"), cell(acts ? `${Math.round(100 * s.waits / acts)}%` : "–", "waiting"),
  ].join("");
}

function split() {
  const rows = ["L", "R"].map(s => ({ s, st: P.state[s], r: run(s) })).filter(x => x.st && x.r);
  const W = 360, rowH = 34, H = rowH * rows.length + 22, L = 4;
  let out = "";
  rows.forEach(({ s, st, r }, k) => {
    const parts = [["tasks", st.compute + st.submits, C.task], ["talk", st.messages + st.inbox + st.reads + st.writes, C.talk],
                   ["waiting", st.waits, C.wait], ["other", st.tools, C.other]];
    const total = parts.reduce((a, p) => a + p[1], 0) || 1;
    const y = 4 + k * rowH;
    out += `<text x="${L}" y="${y + 10}" font-family="VT323, monospace" font-size="14" fill="${C.ink}">${esc(short(r))}</text>`;
    let x = L;
    for (const [name, v, col] of parts) {
      const w = (W - 2 * L) * v / total;
      if (w > 0) out += `<rect x="${x}" y="${y + 14}" width="${w}" height="14" fill="${col}"><title>${name}: ${v} (${Math.round(100 * v / total)}%)</title></rect>`;
      if (w > 34) out += `<text x="${x + 3}" y="${y + 25}" font-family="VT323, monospace" font-size="13" fill="${C.ink}">${Math.round(100 * v / total)}%</text>`;
      x += w;
    }
    out += `<rect x="${L - 1}" y="${y + 13}" width="${W - 2 * L + 2}" height="16" fill="none" stroke="${s === "L" ? C.left : C.right}" stroke-width="2"/>`;
  });
  const key = [["tasks", C.task], ["talk", C.talk], ["waiting", C.wait], ["other", C.other]]
    .map(([n, c], i) => `<rect x="${L + i * 80}" y="${H - 14}" width="10" height="10" fill="${c}"/><text x="${L + i * 80 + 14}" y="${H - 5}" font-family="VT323, monospace" font-size="14" fill="${C.soft}">${n}</text>`).join("");
  $("split").innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="share of actions">${out}${key}</svg>`;
}

/* tasks done over rounds: both runs, the lower bound and the scripted reference */
function chartSvg(full) {
  const a = run("L"), b = run("R"); if (!a || !b) return "";
  const W = 760, H = 300, l = 46, r = 14, t = 14, bt = 40;
  const T = Math.max(a.rounds, b.rounds, a.reference || 0, b.reference || 0, a.bound || 0) + 2;
  const N = Math.max(a.tasks, b.tasks);
  const X = v => l + (W - l - r) * v / T, Y = n => H - bt - (H - bt - t) * n / N;
  const font = `font-family="VT323, monospace" font-size="15" fill="${C.soft}"`;
  let g = "";
  const step = T > 60 ? 10 : 5;
  for (let v = 0; v <= T; v += step)
    g += `<line x1="${X(v)}" x2="${X(v)}" y1="${t}" y2="${H - bt}" stroke="${C.grid}" stroke-width="1"/><text x="${X(v)}" y="${H - bt + 16}" text-anchor="middle" ${font}>${v}</text>`;
  for (const n of [0, Math.round(N / 2), N])
    g += `<line x1="${l}" x2="${W - r}" y1="${Y(n)}" y2="${Y(n)}" stroke="${C.grid}" stroke-width="1"/><text x="${l - 6}" y="${Y(n) + 4}" text-anchor="end" ${font}>${n}</text>`;
  g += `<text x="${(l + W - r) / 2}" y="${H - 6}" text-anchor="middle" ${font}>round</text>` +
       `<text x="12" y="${(t + H - bt) / 2}" text-anchor="middle" transform="rotate(-90 12 ${(t + H - bt) / 2})" ${font}>tasks done</text>`;
  const vline = (v, col, label, dy) => `<line x1="${X(v)}" x2="${X(v)}" y1="${t}" y2="${H - bt}" stroke="${col}" stroke-width="1.5" stroke-dasharray="4 4"/>` +
    `<text x="${X(v) + 4}" y="${t + 12 + dy}" ${font.replace(C.soft, col)}>${label}</text>`;
  if (a.bound) g += vline(a.bound, C.bound, `bound ${a.bound}`, 0);
  const refs = [...new Set([a.reference, b.reference].filter(Boolean))];
  refs.forEach((v, i) => { g += vline(v, C.ref, `reference ${v}`, 16 + 16 * i); });
  const path = (rs, upto) => {
    let d = `M${X(0)},${Y(0)}`, n = 0;
    for (const v of rs) { if (upto !== undefined && v > upto) break; d += `L${X(v)},${Y(n)}L${X(v)},${Y(++n)}`; }
    if (upto !== undefined) d += `L${X(Math.max(upto, n ? rs[n - 1] : 0))},${Y(n)}`;
    return d;
  };
  for (const [rr, col] of [[a, C.left], [b, C.right]]) {
    if (!full) g += `<path d="${path(rr.curve)}" fill="none" stroke="${col}" stroke-width="2" opacity=".2"/>`;
    g += `<path d="${path(rr.curve, full ? undefined : P.round)}" fill="none" stroke="${col}" stroke-width="2.5"/>`;
    g += `<circle cx="${X(rr.rounds)}" cy="${Y(rr.curve.length)}" r="3.5" fill="${col}"/>`;
  }
  if (!full) g += `<line x1="${X(P.round)}" x2="${X(P.round)}" y1="${t}" y2="${H - bt}" stroke="${C.ink}" stroke-width="1.5"/>`;
  const key = [[a, C.left], [b, C.right]].map(([rr, col], i) =>
    `<rect x="${W - r - 250}" y="${H - bt - 46 + i * 18}" width="14" height="4" fill="${col}"/>` +
    `<text x="${W - r - 230}" y="${H - bt - 40 + i * 18}" font-family="VT323, monospace" font-size="15" fill="${C.ink}">${esc(short(rr))}: ${rr.rounds} rounds</text>`).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="tasks done over rounds">` +
    `<rect width="${W}" height="${H}" fill="#ffffff"/>${g}${full ? key : ""}</svg>`;
}

function draw() {
  $("chart").innerHTML = chartSvg(false);
  const a = run("L"), b = run("R");
  $("chartLegend").innerHTML = a && b ? `<i style="background:${C.left}"></i>${esc(short(a))} (${a.rounds})` +
    `<i style="background:${C.right}"></i>${esc(short(b))} (${b.rounds})` +
    (a.bound ? ` · bound ${a.bound}` : "") + (a.reference ? ` · reference ${a.reference}` : "") : "";
}

/* ------------------------------------------------------------------ controls */
$("selL").onchange = e => { play(false); choose("L", +e.target.value); };
$("selR").onchange = e => { play(false); choose("R", +e.target.value); };
$("bFirst").onclick = () => { play(false); go(0); };
$("bPrev").onclick = () => { play(false); go(P.round - 1); };
$("bNext").onclick = () => { play(false); go(P.round + 1, true); };
$("bLast").onclick = () => { play(false); go(maxRound()); };
$("bPlay").onclick = () => play(!P.playing);
$("scrub").oninput = e => { play(false); go(+e.target.value); };
$("speed").onchange = e => {
  P.speed = +e.target.value;
  for (const s of ["L", "R"]) if (P.ready[s]) send(s, { type: "speed", speed: P.speed });
  if (P.playing) play(true);
};
$("bNet").onclick = () => {
  P.net = !P.net; $("bNet").classList.toggle("on", P.net);
  for (const s of ["L", "R"]) if (P.ready[s]) send(s, { type: "net", on: P.net });
};
$("bSvg").onclick = () => {
  const svg = chartSvg(true); if (!svg) return;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  a.download = `${short(run("L")).replace(/\W+/g, "-")}_vs_${short(run("R")).replace(/\W+/g, "-")}.svg`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};
document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  if (e.key === " ") { e.preventDefault(); play(!P.playing); }
  if (e.key === "ArrowRight") $("bNext").click();
  if (e.key === "ArrowLeft") $("bPrev").click();
});
frame("L").src = "codeworld.html?embed=1";
frame("R").src = "codeworld.html?embed=1";
