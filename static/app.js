"use strict";
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const store = {get(k, d) { try { return JSON.parse(localStorage.getItem("hl:" + k)) ?? d; } catch { return d; } },
               set(k, v) { try { localStorage.setItem("hl:" + k, JSON.stringify(v)); } catch {} }};
const GROUPS = [["search", "Job portals and feeds"], ["board", "Company boards (names go on the right)"], ["page", "Careers pages"]];
const KEYHELP = {REED_API_KEY: "reed.co.uk/developers", USAJOBS_API_KEY: "developer.usajobs.gov", USAJOBS_EMAIL: "the email you registered with",
  ADZUNA_APP_ID: "developer.adzuna.com", ADZUNA_APP_KEY: "developer.adzuna.com", JOOBLE_API_KEY: "jooble.org/api/about", MUSE_API_KEY: "optional, raises the limit"};
const COUNTRIES = {gb: "United Kingdom", us: "United States", de: "Germany", pk: "Pakistan", ae: "United Arab Emirates", sa: "Saudi Arabia", qa: "Qatar",
  in: "India", ca: "Canada", au: "Australia", fr: "France", nl: "Netherlands", es: "Spain", ie: "Ireland", sg: "Singapore", za: "South Africa"};

const V11_NEW = ["workablejobs", "rozee"];
let SOURCES = [], run = null, rows = [], view = [], shown = 0, sel = -1, es = null;
const PAGE = 300;

async function api(path, opts = {}) {
  const r = await fetch(path, {headers: {"Content-Type": "application/json"}, ...opts});
  const body = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(body?.detail || r.statusText);
  return body;
}

/* ---------- setup ---------- */
async function boot() {
  const q = store.get("query", {});
  for (const id of ["kw", "days", "limit"]) if (q[id] != null) $("#" + id).value = q[id];
  $("#remote").checked = !!q.remote;
  loadCountries(q).catch(() => {});
  $("#companies").value = store.get("companies", "");
  const d = await api("/api/sources");
  $("#ver").textContent = "v" + d.version;
  SOURCES = d.sources;
  renderSources();
}

function renderSources() {
  const defaults = SOURCES.filter(s => s.group === "search" && s.ready && s.default).map(s => s.id);
  const stored = store.get("picked", null);
  // Portals added in an update are ticked once for people who saved a selection before they existed.
  const seen = new Set(store.get("seen", stored ? SOURCES.map(s => s.id).filter(id => !V11_NEW.includes(id)) : SOURCES.map(s => s.id)));
  const picked = new Set(stored ?? defaults);
  defaults.filter(id => !seen.has(id)).forEach(id => picked.add(id));
  store.set("seen", SOURCES.map(s => s.id)); store.set("picked", [...picked]);
  let html = "";
  for (const [g, label] of GROUPS) {
    const list = SOURCES.filter(s => s.group === g);
    html += `<div class="grp"><h3>${label}</h3>`;
    for (const s of list) {
      const locked = !s.ready, sel = g === "search";
      html += `<label class="src ${locked ? "locked" : ""}" title="${esc(s.note || s.region)}">` +
        (sel ? `<input type="checkbox" value="${s.id}" ${picked.has(s.id) && !locked ? "checked" : ""} ${locked ? "disabled" : ""}>` : `<span class="mono dim">&middot;</span>`) +
        `<span>${esc(s.name)}</span>` +
        (locked ? `<button type="button" class="addkey" data-src="${s.id}" title="Needs a free API key. Click to add it.">add free key</button>`
                : `<span class="r">${esc(s.region)}</span>`) + `</label>`;
    }
    html += "</div>";
  }
  $("#srcList").innerHTML = html;
  const ready = SOURCES.filter(s => s.ready).length;
  $("#srcCount").textContent = `${SOURCES.length} sources, ${ready} ready`;
}

$("#srcList").addEventListener("change", () => store.set("picked", pickedSources()));
$("#srcList").addEventListener("click", e => {
  const b = e.target.closest(".addkey"); if (!b) return;
  e.preventDefault(); openKeys(SOURCES.find(s => s.id === b.dataset.src));
});
document.querySelectorAll("[data-pick]").forEach(b => b.onclick = () => {
  $("#srcList").querySelectorAll("input:not(:disabled)").forEach(i => i.checked = b.dataset.pick === "all");
  store.set("picked", pickedSources());
});
const pickedSources = () => [...$("#srcList").querySelectorAll("input:checked")].map(i => i.value);

/* ---------- country + city ---------- */
const CITY = {data: null, items: [], on: -1};
const cityCache = {};

async function loadCountries(q) {
  const sel = $("#cty");
  let list = Object.entries(COUNTRIES).map(([code, name]) => ({code, name})).sort((a, b) => a.name.localeCompare(b.name));
  try { list = (await api("/api/countries")).countries; } catch {}
  sel.innerHTML = `<option value="">Any country</option>` + list.map(c => `<option value="${c.code}">${esc(c.name)}</option>`).join("");
  // older saved searches stored the country name instead of the code
  const saved = (q.cty || "").toLowerCase();
  const hit = list.find(c => c.code === saved || c.name.toLowerCase() === saved);
  if (hit) { sel.value = hit.code; await loadCities(hit.code); $("#loc").value = q.loc || ""; }
}

async function loadCities(code) {
  const inp = $("#loc");
  closeCities(); inp.value = ""; CITY.data = null;
  if (!code) { inp.disabled = true; inp.placeholder = "pick a country first"; return; }
  inp.disabled = true; inp.placeholder = "loading cities...";
  try { CITY.data = cityCache[code] ||= await api(`/api/cities?country=${encodeURIComponent(code)}`); }
  catch { CITY.data = {popular: [], cities: []}; }
  if ($("#cty").value !== code) return;               // the user changed country meanwhile
  inp.disabled = false;
  inp.placeholder = CITY.data.cities.length ? "Any city" : "Any city (type one)";
}

$("#cty").addEventListener("change", e => { loadCities(e.target.value); });

function renderCities() {
  const d = CITY.data; if (!d) return;
  const t = $("#loc").value.trim().toLowerCase();
  let html = "", items = [];
  const add = c => { items.push(c); return `<li role="option" data-i="${items.length - 1}">${esc(c)}</li>`; };
  if (!t) {
    html += `<li role="option" data-i="0" class="any">Any city in ${esc(d.name)}</li>`; items.push("");
    if (d.popular.length) html += `<li class="grp">Main cities</li>` + d.popular.map(add).join("");
    const rest = d.cities.filter(c => !d.popular.includes(c));
    if (rest.length) html += `<li class="grp">All ${d.cities.length.toLocaleString()} cities A-Z</li>` + rest.slice(0, 150).map(add).join("") +
      (rest.length > 150 ? `<li class="note">type to search all ${rest.length.toLocaleString()} cities</li>` : "");
  } else {
    const all = [...new Set([...d.popular, ...d.cities])];
    const starts = all.filter(c => c.toLowerCase().startsWith(t)), has = all.filter(c => !c.toLowerCase().startsWith(t) && c.toLowerCase().includes(t));
    const hits = [...starts, ...has].slice(0, 200);
    html = hits.length ? hits.map(add).join("") : `<li class="note">No match in the list. "${esc($("#loc").value.trim())}" will be searched as typed.</li>`;
  }
  CITY.items = items; CITY.on = -1;
  const ul = $("#cityList"); ul.innerHTML = html; ul.hidden = false; ul.scrollTop = 0;
  $("#loc").setAttribute("aria-expanded", "true");
}

function closeCities() { $("#cityList").hidden = true; $("#loc").setAttribute("aria-expanded", "false"); }
function pickCity(i) { $("#loc").value = CITY.items[i] ?? ""; closeCities(); }

$("#loc").addEventListener("focus", renderCities);
$("#loc").addEventListener("click", renderCities);
$("#loc").addEventListener("input", renderCities);
$("#loc").addEventListener("blur", () => setTimeout(closeCities, 150));
$("#loc").addEventListener("keydown", e => {
  const ul = $("#cityList"); const opts = [...ul.querySelectorAll("li[data-i]")];
  if (e.key === "Escape") return closeCities();
  if (!["ArrowDown", "ArrowUp", "Enter"].includes(e.key)) return;
  if (ul.hidden) { if (e.key !== "Enter") { e.preventDefault(); renderCities(); } return; }
  if (e.key === "Enter") { if (CITY.on >= 0) { e.preventDefault(); pickCity(+opts[CITY.on].dataset.i); } else closeCities(); return; }
  e.preventDefault();
  CITY.on = Math.max(0, Math.min(opts.length - 1, CITY.on + (e.key === "ArrowDown" ? 1 : -1)));
  opts.forEach((li, k) => li.classList.toggle("on", k === CITY.on));
  opts[CITY.on]?.scrollIntoView({block: "nearest"});
});
$("#cityList").addEventListener("mousedown", e => {
  const li = e.target.closest("li[data-i]"); if (!li) return;
  e.preventDefault(); pickCity(+li.dataset.i);
});

/* ---------- search ---------- */
$("#query").addEventListener("submit", async e => {
  e.preventDefault();
  const q = {kw: $("#kw").value, loc: $("#loc").value, cty: $("#cty").value, days: $("#days").value, limit: $("#limit").value, remote: $("#remote").checked};
  store.set("query", q); store.set("companies", $("#companies").value);
  const body = {keywords: q.kw, location: q.loc, country: q.cty, days: +q.days, limit: +q.limit || 150, remote: q.remote,
                sources: pickedSources(), companies: $("#companies").value.split("\n")};
  if (es) es.close();
  rows = []; view = []; sel = -1; shown = 0;
  $("#list").innerHTML = ""; $("#detail").innerHTML = `<p class="dim empty">Select a job to read the full posting.</p>`;
  $("#ledger").innerHTML = ""; $("#exports").hidden = true; $("#runbar").hidden = false; $("#results").hidden = false;
  $("#go").disabled = true; $("#runState").textContent = "starting";
  try { run = (await api("/api/search", {method: "POST", body: JSON.stringify(body)})).run; }
  catch (err) { $("#runState").innerHTML = `<span class="err">${esc(err.message)}</span>`; $("#go").disabled = false; return; }
  const t0 = performance.now();
  es = new EventSource(`/api/runs/${run}/events`);
  let pending = false;
  es.onmessage = m => {
    const ev = JSON.parse(m.data);
    if (ev.type === "source") ledger(ev);
    else if (ev.type === "jobs") { rows.push(...ev.rows); if (!pending) { pending = true; requestAnimationFrame(() => { pending = false; refresh(); }); } }
    else if (ev.type === "done") {
      es.close(); $("#go").disabled = false; refresh(); $("#exports").hidden = !rows.length;
      const s = ev.stats || {};
      $("#runState").textContent = `${ev.total} unique jobs in ${ev.seconds}s  |  ${s.requests ?? 0} requests, ${s.cache_hits ?? 0} from cache, ${s.retries ?? 0} retries`;
    }
    if (ev.type !== "done") $("#runState").textContent = `${rows.length} jobs so far, ${((performance.now() - t0) / 1000).toFixed(1)}s`;
  };
  es.onerror = () => { if ($("#go").disabled) { $("#runState").innerHTML = `<span class="err">Connection to the app was lost.</span>`; $("#go").disabled = false; es.close(); } };
});

function ledger(s) {
  const id = "led-" + s.id.replace(/[^\w-]/g, "_");
  let el = document.getElementById(id);
  if (!el) { el = document.createElement("div"); el.id = id; $("#ledger").append(el); }
  el.className = "led " + s.state;
  const v = s.state === "running" ? "working" : s.state === "done" ? `${s.kept}${s.found !== s.kept ? " of " + s.found : ""}${s.ms != null ? "  " + (s.ms / 1000).toFixed(1) + "s" : ""}` : s.state;
  el.title = s.state === "done" ? `returned ${s.found}, matched your filters ${s.matched ?? s.kept}, kept ${s.kept}${s.error ? "\n" + s.error : ""}` : (s.error || "");
  el.innerHTML = `<i></i><span class="n">${esc(s.name)}</span><span class="v">${esc(v)}</span>`;
}

/* ---------- results ---------- */
let ftimer;
$("#filter").addEventListener("input", () => { clearTimeout(ftimer); ftimer = setTimeout(refresh, 120); });
$("#sort").addEventListener("change", refresh);

function refresh() {
  const f = $("#filter").value.toLowerCase().trim().split(/\s+/).filter(Boolean);
  const key = $("#sort").value;
  view = rows.filter(r => !f.length || f.every(w => `${r.title} ${r.company} ${r.location} ${r.department} ${r.source}`.toLowerCase().includes(w)));
  view.sort(key === "posted" ? (a, b) => (b.posted || "").localeCompare(a.posted || "") : (a, b) => (a[key] || "").localeCompare(b[key] || ""));
  shown = 0; $("#list").innerHTML = ""; more();
}

function more() {
  const frag = document.createDocumentFragment();
  for (const r of view.slice(shown, shown + PAGE)) {
    const li = document.createElement("li");
    li.dataset.i = r.i; if (r.i === sel) li.className = "on";
    li.innerHTML = `<span class="t">${esc(r.title)}</span><span class="d">${esc(r.posted || "")}</span>` +
      `<span class="c">${esc([r.company, r.location].filter(Boolean).join("  ·  "))}</span><span class="s">${esc(r.source)}${r.also.length ? " +" + r.also.length : ""}</span>`;
    frag.append(li);
  }
  $("#list").append(frag);
  shown = Math.min(view.length, shown + PAGE);
  $("#more").hidden = shown >= view.length;
  $("#shown").textContent = `${view.length} of ${rows.length}`;
}
$("#more").onclick = more;

$("#list").addEventListener("click", async e => {
  const li = e.target.closest("li"); if (!li) return;
  $("#list").querySelector("li.on")?.classList.remove("on"); li.classList.add("on");
  sel = +li.dataset.i;
  const d = $("#detail"); d.innerHTML = `<p class="dim empty">Loading</p>`;
  try {
    const j = await api(`/api/runs/${run}/jobs/${sel}`);
    if (sel !== +li.dataset.i) return;
    const facts = [["Location", j.location], ["Department", j.department], ["Office / team", j.office], ["Type", j.employment_type],
      ["Remote", j.remote], ["Salary", j.salary], ["Posted", j.posted], ["Updated", j.updated], ["Source", [j.source, ...(j.also_on || [])].join(", ")]]
      .filter(([, v]) => v);
    d.innerHTML = `<h1>${esc(j.title)}</h1><div class="co">${esc(j.company)}</div>` +
      (j.url ? `<a class="open" href="${esc(j.url)}" target="_blank" rel="noopener">Open original posting</a>` : "") +
      `<dl class="facts">${facts.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl>` +
      `<div class="body">${esc(j.description || "No description in this source. Open the original posting.")}</div>`;
    d.scrollTop = 0;
  } catch (err) { d.innerHTML = `<p class="err">${esc(err.message)}</p>`; }
});

document.addEventListener("keydown", e => {
  if (!["ArrowDown", "ArrowUp"].includes(e.key) || ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
  const cur = $("#list").querySelector("li.on"); const next = cur ? (e.key === "ArrowDown" ? cur.nextElementSibling : cur.previousElementSibling) : $("#list").firstElementChild;
  if (next) { e.preventDefault(); next.click(); next.scrollIntoView({block: "nearest"}); }
});

$("#exports").addEventListener("click", e => { const a = e.target.closest("a[data-fmt]"); if (a && run) location.href = `/api/runs/${run}/export.${a.dataset.fmt}`; });

/* ---------- keys ---------- */
async function openKeys(src) {
  const have = await api("/api/settings");
  const link = k => SOURCES.find(s => s.needs.includes(k) && s.signup)?.signup;
  $("#keyFields").innerHTML = Object.keys(have).map(k => `<div class="kf ${src?.needs.includes(k) ? "hl" : ""}"><label for="k_${k}">${k}</label>` +
    `<input id="k_${k}" data-k="${k}" placeholder="${have[k] ? "saved (leave blank to keep)" : ""}" autocomplete="off"><small>${esc(KEYHELP[k] || "")}</small>` +
    (link(k) ? `<a class="grab" href="${esc(link(k))}" target="_blank" rel="noopener">Get this free key</a>` : "") + `</div>`).join("");
  $("#keys").showModal();
  if (src) $(`#k_${src.needs[0]}`)?.focus();
}
$("#openKeys").onclick = () => openKeys();
$("#keysForm").addEventListener("submit", async e => {
  if (e.submitter?.value !== "save") return;
  const body = {}; $("#keyFields").querySelectorAll("input").forEach(i => { if (i.value.trim()) body[i.dataset.k] = i.value.trim(); });
  await api("/api/settings", {method: "POST", body: JSON.stringify(body)});
  SOURCES = (await api("/api/sources")).sources; renderSources();
});

boot().catch(err => { document.body.insertAdjacentHTML("afterbegin", `<p class="err">${esc(err.message)}</p>`); });
