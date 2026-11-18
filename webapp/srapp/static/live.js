/* Live InfluxDB charts (Chart.js) + report comparison charts. */
window.SR = window.SR || {};
(function (SR) {
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const PALETTE = ['#4f8cff', '#f0545b', '#3fb768', '#e3a33b', '#a76cf5', '#22b8cf', '#f06595', '#94a3b8', '#fab005', '#12b886'];
  const fmtTime = (ms) => new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const fmtDay = (ms) => new Date(ms).toLocaleString([], { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  const pad = (n) => String(n).padStart(2, '0');
  const toLocalInput = (ms) => { const d = new Date(ms); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; };
  const fmtNum = (n, d = 0) => (n === null || n === undefined) ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d });

  // Grafana-style drag-to-zoom: draws the selection band while dragging (chart.$sel = {x0, x1} in CSS px).
  const selectionPlugin = {
    id: 'srSelection',
    afterDraw(chart) {
      const s = chart.$sel, a = chart.chartArea;
      if (!s || !a) return;
      const ctx = chart.ctx, x = Math.min(s.x0, s.x1), w = Math.abs(s.x1 - s.x0);
      ctx.save();
      ctx.fillStyle = (css('--accent') || PALETTE[0]) + '33';
      ctx.strokeStyle = css('--accent') || PALETTE[0];
      ctx.fillRect(x, a.top, w, a.bottom - a.top);
      ctx.strokeRect(x + 0.5, a.top + 0.5, w, a.bottom - a.top - 1);
      ctx.restore();
    },
  };

  function baseOptions(yTitle, win) {
    const grid = css('--border'), text = css('--muted');
    return {
      responsive: true, maintainAspectRatio: false, animation: false, parsing: false, normalized: true,
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      plugins: { legend: { labels: { color: text, boxWidth: 12 } },
        tooltip: { callbacks: { title: (items) => items.length ? new Date(items[0].parsed.x).toLocaleString() : '' } } },
      scales: {
        x: { type: 'linear', min: win && win[0], max: win && win[1], grid: { color: grid },
          ticks: { color: text, maxTicksLimit: 8, callback(v) { return (this.max - this.min) > 20 * 3600e3 ? fmtDay(v) : fmtTime(v); } } },
        y: { beginAtZero: true, ticks: { color: text }, grid: { color: grid }, title: { display: !!yTitle, text: yTitle, color: text } },
      },
    };
  }
  const xy = (pts) => pts.map(([x, y]) => ({ x, y }));
  const line = (label, pts, color, extra = {}) => ({ label, data: xy(pts), borderColor: color, backgroundColor: color + '33',
    borderWidth: 2, pointRadius: 0, tension: 0.25, ...extra });

  class Live {
    constructor(root) {
      this.root = root;
      this.db = root.dataset.db; this.app = root.dataset.app;
      this.from = root.dataset.from ? Number(root.dataset.from) : null;
      this.to = root.dataset.to ? Number(root.dataset.to) : null;
      this.live = root.dataset.live === '1';
      this.range = Number(new URLSearchParams(location.search).get('range') || 900);
      this.urlSync = root.dataset.urlSync === '1';
      this.initial = { from: this.from, to: this.to, live: this.live };
      this.zoomed = false;
      this.depth = 0;  // history entries pushed by zooming
      this.win = null;  // [start, end] ms of the data on screen
      this.seq = 0;
      this.charts = {};
      this.timer = null;
      const out = root.querySelector('[data-role="zoom-out"]'), reset = root.querySelector('[data-role="zoom-reset"]');
      if (out) out.addEventListener('click', () => this.zoomOut());
      if (reset) reset.addEventListener('click', () => this.resetZoom());
    }
    // ---- time range navigation (drag to zoom, double-click / button to zoom out) ----
    setWindow(from, to, push = true) {
      clearTimeout(this.timer);
      const now = Date.now();
      to = Math.min(to, now);
      if (to - from < 10000) from = to - 10000;  // the smallest useful window (2 buckets of 5 s)
      this.from = Math.round(from); this.to = Math.round(to); this.live = false; this.zoomed = true;
      const reset = this.root.querySelector('[data-role="zoom-reset"]');
      if (reset) reset.hidden = false;
      if (this.urlSync && push) {
        const u = new URL(location.href);
        u.searchParams.delete('range'); u.searchParams.delete('result');
        u.searchParams.set('from', this.from); u.searchParams.set('to', this.to);
        history.pushState({ from: this.from, to: this.to }, '', u);
        this.depth += 1;
        SR.monitorSyncForm && SR.monitorSyncForm(this.from, this.to);
      }
      const gl = document.getElementById('mon-grafana');
      if (gl) {
        try {
          const g = new URL(gl.href);
          g.searchParams.set('from', this.from); g.searchParams.set('to', this.to); g.searchParams.delete('refresh');
          gl.href = g.toString();
        } catch (e) { /* not an absolute URL: leave it */ }
      }
      this.refresh();
    }
    zoomOut() {
      const [a, b] = this.win || [Date.now() - this.range * 1000, Date.now()];
      const span = b - a, mid = (a + b) / 2;
      let to = mid + span, from = mid - span;
      const now = Date.now();
      if (to > now) { from -= to - now; to = now; }
      this.setWindow(from, to);
    }
    resetZoom() {
      if (this.urlSync && this.depth) { history.go(-this.depth); return; }  // popstate reloads the original URL
      clearTimeout(this.timer);
      Object.assign(this, this.initial, { zoomed: false });
      this.root.querySelector('[data-role="zoom-reset"]').hidden = true;
      this.refresh();
    }
    attachZoom(chart) {
      const c = chart.canvas;
      let sel = null;
      const px = (ev) => ev.clientX - c.getBoundingClientRect().left;
      const clamp = (x) => Math.min(Math.max(x, chart.chartArea.left), chart.chartArea.right);
      c.style.cursor = 'crosshair';
      c.style.touchAction = 'pan-y';
      c.addEventListener('pointerdown', (ev) => {
        if (ev.button !== 0 || !chart.chartArea) return;
        const x = px(ev), a = chart.chartArea;
        if (x < a.left || x > a.right) return;
        sel = chart.$sel = { x0: x, x1: x };
        c.setPointerCapture(ev.pointerId);
        ev.preventDefault();
      });
      c.addEventListener('pointermove', (ev) => { if (!sel) return; sel.x1 = clamp(px(ev)); chart.draw(); });
      const finish = (apply) => {
        if (!sel) return;
        const s = sel; sel = chart.$sel = null; chart.draw();
        if (!apply || Math.abs(s.x1 - s.x0) < 6) return;
        const xs = chart.scales.x;
        this.setWindow(xs.getValueForPixel(Math.min(s.x0, s.x1)), xs.getValueForPixel(Math.max(s.x0, s.x1)));
      };
      c.addEventListener('pointerup', () => finish(true));
      c.addEventListener('pointercancel', () => finish(false));
      c.addEventListener('dblclick', () => this.zoomOut());
    }
    canvas(name) { return this.root.querySelector(`[data-chart="${name}"]`); }
    chart(name, config) {
      const ch = this.charts[name];
      if (ch) {
        ch.data = config.data;
        const x = config.options.scales && config.options.scales.x;
        if (x) { ch.options.scales.x.min = x.min; ch.options.scales.x.max = x.max; }
        ch.update('none');
      } else {
        const timeSeries = config.type === 'line';
        if (timeSeries) config.plugins = [selectionPlugin];
        this.charts[name] = new Chart(this.canvas(name), config);
        if (timeSeries) this.attachZoom(this.charts[name]);
      }
    }
    url() {
      const p = new URLSearchParams({ db: this.db, app: this.app });
      if (this.from) p.set('from', this.from); else p.set('range', this.range);
      if (this.to && !this.live) p.set('to', this.to);
      else if (this.from && !this.live) p.set('to', Date.now());
      return '/api/influx/dashboard?' + p.toString();
    }
    async refresh() {
      const state = this.root.querySelector('[data-role="state"]');
      const seq = ++this.seq;
      try {
        const d = await SR.getJSON(this.url());
        if (seq !== this.seq) return;  // a newer zoom/refresh superseded this response
        this.win = [d.start, d.end];
        this.render(d);
        const errs = Object.entries(d.errors || {});
        state.className = 'badge ' + (errs.length ? 'stopped' : (this.live ? 'running' : 'finished'));
        state.textContent = (this.live ? 'live · every 5 s' : (this.zoomed ? 'zoomed' : 'fixed window')) + (errs.length ? ` · ${errs.length} panel(s) failed` : '');
        state.title = errs.map(([k, v]) => `${k}: ${v}`).join('\n');
        let note = this.root.querySelector('[data-role="panel-errors"]');
        if (!note) { note = document.createElement('div'); note.dataset.role = 'panel-errors'; note.className = 'flash warn'; state.parentElement.after(note); }
        note.style.display = errs.length ? '' : 'none';
        note.textContent = errs.length ? 'InfluxDB rejected: ' + errs.map(([k, v]) => `${k} → ${v}`).join(' | ') + ' (Settings → InfluxDB diagnostics)' : '';
        this.root.querySelector('[data-role="window"]').textContent =
          `${new Date(d.start).toLocaleString()} → ${new Date(d.end)[new Date(d.start).toDateString() === new Date(d.end).toDateString() ? 'toLocaleTimeString' : 'toLocaleString']()} · bucket ${d.bucket_s}s`;
      } catch (e) {
        if (seq !== this.seq) return;
        state.className = 'badge failed'; state.textContent = e.message;
      }
      if (this.live && seq === this.seq) this.timer = setTimeout(() => this.refresh(), 5000);
    }
    stop() { this.live = false; clearTimeout(this.timer); setTimeout(() => this.refresh(), 6000); }
    kpi(key, value, cls) {
      const el = this.root.querySelector(`[data-kpi="${key}"]`);
      el.textContent = value;
      if (cls !== undefined) el.parentElement.className = 'kpi ' + cls;
    }
    render(d) {
      const t = d.totals;
      const peak = (pts) => pts.reduce((m, p) => Math.max(m, p[1] || 0), 0);
      this.kpi('req', fmtNum(t.req));
      this.kpi('err', fmtNum(t.err), t.err ? 'bad' : 'good');
      this.kpi('error_pct', fmtNum(t.error_pct, 2) + ' %', t.error_pct > 1 ? 'bad' : 'good');
      this.kpi('avg', t.avg == null ? '—' : fmtNum(t.avg) + ' ms');
      this.kpi('p95', t.p95 == null ? '—' : fmtNum(t.p95) + ' ms');
      this.kpi('vu', fmtNum(peak(d.vusers)));
      this.kpi('hps', fmtNum(peak(d.hps), 1));

      const win = [d.start, d.end];
      const accent = css('--accent') || PALETTE[0], err = css('--err') || PALETTE[1];
      this.chart('vusers', { type: 'line', options: baseOptions('users', win),
        data: { datasets: [line('Active threads', d.vusers, accent, { fill: true, stepped: true, tension: 0 })] } });
      this.chart('hits', { type: 'line', options: baseOptions('per second', win),
        data: { datasets: [line('Hits/s', d.hps, PALETTE[2]), line('Errors/s', d.eps, err)] } });
      this.chart('rt', { type: 'line', options: baseOptions('ms', win),
        data: { datasets: [line('Average', d.avg, accent), line('95th percentile', d.p95, PALETTE[3], { borderDash: [6, 3] })] } });

      const codes = d.codes.length ? d.codes : [{ code: 'no data', count: 1 }];
      const ERR = [PALETTE[1], PALETTE[3], PALETTE[4], PALETTE[5], PALETTE[6], PALETTE[8], PALETTE[7], PALETTE[0]];
      let e = 0;
      const colors = codes.map((c) => c.code.startsWith('OK') ? (css('--ok') || PALETTE[2]) : ERR[e++ % ERR.length]);
      const pieCfg = { type: 'doughnut', data: { labels: codes.map((c) => `${c.code} (${fmtNum(c.count)})`),
        datasets: [{ data: codes.map((c) => c.count), backgroundColor: d.codes.length ? colors : [css('--border')], borderColor: css('--panel'), borderWidth: 2 }] },
        options: { responsive: true, maintainAspectRatio: false, animation: false, cutout: '55%',
          plugins: { legend: { position: 'right', labels: { color: css('--muted'), boxWidth: 12 } } } } };
      this.chart('codes', pieCfg);

      const txSets = Object.entries(d.p95_by_tx).map(([name, pts], i) => line(name, pts, PALETTE[i % PALETTE.length]));
      this.chart('p95tx', { type: 'line', options: baseOptions('ms', win), data: { datasets: txSets } });

      const tbody = this.root.querySelector('[data-role="tx"]');
      tbody.innerHTML = '';
      if (!d.transactions.length) { tbody.innerHTML = '<tr><td colspan="7" class="empty">No samples in this window yet.</td></tr>'; return; }
      d.transactions.forEach((x) => {
        const tr = document.createElement('tr');
        const cells = [x.transaction, fmtNum(x.count), fmtNum(x.errors), fmtNum(x.error_pct, 2) + ' %', fmtNum(x.avg), fmtNum(x.p95), fmtNum(x.max)];
        cells.forEach((v, i) => { const td = document.createElement('td'); td.textContent = v; if (i) td.className = 'num'; if (i === 3 && x.error_pct > 1) td.className += ' delta-up'; tr.appendChild(td); });
        tbody.appendChild(tr);
      });
    }
  }

  document.querySelectorAll('.live').forEach((root) => {
    if (!window.Chart) return;
    const l = new Live(root);
    SR.liveStop = () => l.stop();
    l.refresh();
  });

  // ---- monitor page: load applications of the selected database ----
  SR.monitorForm = () => {
    const db = document.getElementById('mon-db'), app = document.getElementById('mon-app');
    if (!db) return;
    const load = async () => {
      app.innerHTML = '<option value="">—</option>';
      if (!db.value) return;
      try {
        const d = await SR.getJSON('/api/influx/apps?db=' + encodeURIComponent(db.value));
        d.apps.forEach((a) => { const o = document.createElement('option'); o.textContent = a; if (a === app.dataset.selected) o.selected = true; app.appendChild(o); });
        if (d.apps.length === 1) app.value = d.apps[0];
      } catch (e) {
        const o = document.createElement('option'); o.value = ''; o.textContent = e.message;
        app.replaceChildren(o);
      }
    };
    db.addEventListener('change', load);
    load();

    // Window: a live range, or a custom From/To (datetime-local, browser time zone) sent as epoch ms.
    const form = document.getElementById('monitor-form'), rng = document.getElementById('mon-range');
    const fIn = document.getElementById('mon-from'), tIn = document.getElementById('mon-to');
    const fMs = document.getElementById('mon-from-ms'), tMs = document.getElementById('mon-to-ms');
    const showCustom = () => form.querySelectorAll('.mon-custom').forEach((el) => { el.hidden = rng.value !== 'custom'; });
    SR.monitorSyncForm = (from, to) => {
      rng.value = 'custom'; fIn.value = toLocalInput(from); tIn.value = to ? toLocalInput(to) : '';
      fMs.value = from; tMs.value = to || ''; showCustom();
    };
    if (fMs.value) { fIn.value = toLocalInput(Number(fMs.value)); if (tMs.value) tIn.value = toLocalInput(Number(tMs.value)); }
    rng.addEventListener('change', () => {
      if (rng.value === 'custom' && !fIn.value) {
        const now = Date.now(); fIn.value = toLocalInput(now - 3600e3); tIn.value = toLocalInput(now);
      }
      showCustom();
    });
    form.addEventListener('submit', (ev) => {
      if (rng.value !== 'custom') { fMs.disabled = tMs.disabled = true; return; }
      const from = fIn.value ? new Date(fIn.value).getTime() : NaN;
      const to = tIn.value ? new Date(tIn.value).getTime() : Date.now();
      if (Number.isNaN(from) || Number.isNaN(to) || from >= to) {
        ev.preventDefault();
        fIn.setCustomValidity('From must be a valid date before To'); fIn.reportValidity();
        return;
      }
      fIn.setCustomValidity('');
      fMs.value = from; tMs.value = to; fMs.disabled = tMs.disabled = false;
      rng.disabled = true;  // the range select must not be sent with a custom window
    });
    fIn.addEventListener('input', () => fIn.setCustomValidity(''));
    window.addEventListener('pageshow', () => { rng.disabled = false; fMs.disabled = tMs.disabled = false; });
    window.addEventListener('popstate', () => location.reload());
    showCustom();
  };

  // ---- report comparison charts ----
  SR.compareCharts = () => {
    const el = document.getElementById('cmp-data');
    if (!el || !window.Chart) return;
    const d = JSON.parse(el.textContent);
    const muted = css('--muted'), grid = css('--border');
    const short = (r) => r.replace(/^Ejecucion_/, '').slice(0, 13);
    const axes = { x: { ticks: { color: muted }, grid: { color: grid } }, y: { beginAtZero: true, ticks: { color: muted }, grid: { color: grid } } };
    const base = { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { labels: { color: muted, boxWidth: 12 } } } };
    const tx = d.rows.filter((r) => r.name !== 'Total');
    const names = tx.map((r) => r.name);
    // metric per transaction, one bar series per run
    new Chart(document.getElementById('cmp-tx'), { type: 'bar', options: { ...base, indexAxis: 'y', scales: axes },
      data: { labels: names, datasets: d.runs.map((r, i) => ({ label: (i ? '' : 'BASE ') + short(r), backgroundColor: i ? PALETTE[i % PALETTE.length] : '#A59F80',
        data: tx.map((row) => (row.cells[i].s || {})[d.metric] ?? null) })) } });
    // delta % of the last selected run vs baseline, red when worse than threshold
    const last = d.runs.length - 1;
    const deltas = tx.map((row) => (row.cells[last] || {}).delta);
    new Chart(document.getElementById('cmp-delta'), { type: 'bar', options: { ...base, indexAxis: 'y', scales: axes, plugins: { legend: { display: false } } },
      data: { labels: names, datasets: [{ label: 'Δ %', data: deltas,
        backgroundColor: deltas.map((v) => v == null ? '#94a3b8' : v > d.thr ? css('--err') : v < -d.thr ? css('--ok') : '#94a3b8') }] } });
    // trend of all executions of the same script
    const tr = d.trend;
    new Chart(document.getElementById('cmp-trend'), { type: 'line', options: { ...base, scales: { ...axes, y1: { position: 'right', beginAtZero: true, ticks: { color: muted }, grid: { display: false } } } },
      data: { labels: tr.map((x) => short(x.run)), datasets: [
        { label: 'Avg (ms)', data: tr.map((x) => x.avg_ms), borderColor: PALETTE[0], backgroundColor: PALETTE[0], tension: 0.2 },
        { label: 'p95 (ms)', data: tr.map((x) => x.p95_ms), borderColor: PALETTE[3], backgroundColor: PALETTE[3], tension: 0.2 },
        { label: 'Error %', data: tr.map((x) => x.error_pct), borderColor: PALETTE[1], backgroundColor: PALETTE[1], yAxisID: 'y1', borderDash: [5, 3], tension: 0.2 }] } });
  };
})(window.SR);
