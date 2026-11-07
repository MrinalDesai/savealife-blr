/* Shared helpers for the three SaveAlife BLR pages. Vanilla JS, no build step. */
const API = '/api';

async function api(path, opts = {}) {
  const r = await fetch(API + path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  if (!r.ok) { const t = await r.text(); throw new Error(`${r.status} ${t}`); }
  return r.json();
}
const post = (path, body) => api(path, { method: 'POST', body: JSON.stringify(body || {}) });

function fmtClock(sec) {
  sec = Math.max(0, Math.floor(sec));
  return `${String(Math.floor(sec / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`;
}
function fmtT(sec) { return fmtClock(sec); }
function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

/* Scenario strip + golden-hour timer, same on every page. `onNew` runs after a scenario is (re)started. */
async function mountTopbar(active, onNew) {
  const scen = await api('/scenarios');
  const strip = document.getElementById('scenarios');
  strip.innerHTML = scen.map(s => `<button data-id="${s.id}" title="${esc(s.title)} · ${esc(s.location)}">${s.id}<span class="sub"></span></button>`).join('');
  strip.onclick = async e => {
    const b = e.target.closest('button'); if (!b) return;
    await post('/incident/new', { scenario: b.dataset.id });
    onNew && onNew();
  };
  document.querySelectorAll('.nav a').forEach(a => a.classList.toggle('on', a.dataset.page === active));
}
function markScenario(st) {
  document.querySelectorAll('#scenarios button').forEach(b => {
    const on = st && b.dataset.id === st.scenario.id;
    b.classList.toggle('on', on);
    b.innerHTML = on ? `${b.dataset.id} · ${st.severity || '…'}` : b.dataset.id;
  });
}
function tickGolden(st) {
  const el = document.getElementById('golden'); const bar = document.getElementById('goldenbar');
  if (!el) return;
  if (!st) { el.textContent = '60:00'; if (bar) bar.style.width = '100%'; return; }
  const left = st.golden_hour_left_sec - (Date.now() / 1000 - st._fetched);
  el.textContent = fmtClock(left);
  if (bar) bar.style.width = `${Math.max(0, left / 36)}%`;
  el.className = 'big ' + (left < 900 ? 'red' : 'amber');
}

/* Poll /incident/state once a second; call `render(state|null)`. */
function startPolling(render) {
  let last = null;
  async function once() {
    try { last = await api('/incident/state'); last._fetched = Date.now() / 1000; }
    catch (e) { last = null; }
    render(last);
  }
  once();
  setInterval(once, 1000);
  setInterval(() => tickGolden(last), 250);
  return () => last;
}

/* Agent trace renderer: colours fails/passes/recommendation. */
function renderTrace(el, trace) {
  if (!trace || !trace.length) { el.innerHTML = '<div class="sim">Waiting for the bystander report…</div>'; return; }
  el.innerHTML = trace.map((t, i) => {
    const cls = t.startsWith('RECOMMEND') ? 'rec' : '';
    const body = esc(t)
      .replace(/(Fails window\.|No road route[^.]*\.|outside window)/g, '<span class="fail">$1</span>')
      .replace(/(Passes\.|passes inside window|saves [\d.]+ min)/g, '<span class="pass">$1</span>');
    return `<div class="${cls}"><span class="t">${String(i + 1).padStart(2, '0')}</span>${body}</div>`;
  }).join('');
  el.scrollTop = el.scrollHeight;
}

/* Point along a polyline at fraction f (0..1), with bearing in degrees. */
function alongLine(points, f) {
  const segs = []; let total = 0;
  for (let i = 1; i < points.length; i++) {
    const d = Math.hypot(points[i][0] - points[i - 1][0], (points[i][1] - points[i - 1][1]) * Math.cos(points[i][0] * Math.PI / 180));
    segs.push(d); total += d;
  }
  let target = f * total;
  for (let i = 0; i < segs.length; i++) {
    if (target <= segs[i] || i === segs.length - 1) {
      const u = segs[i] ? Math.min(1, target / segs[i]) : 1;
      const a = points[i], b = points[i + 1];
      const lat = a[0] + (b[0] - a[0]) * u, lng = a[1] + (b[1] - a[1]) * u;
      const brg = Math.atan2((b[1] - a[1]) * Math.cos(a[0] * Math.PI / 180), b[0] - a[0]) * 180 / Math.PI;
      return { lat, lng, bearing: brg };
    }
    target -= segs[i];
  }
  const l = points[points.length - 1]; return { lat: l[0], lng: l[1], bearing: 0 };
}
