/* Live InfluxDB charts (Chart.js) + report comparison charts. */
window.SR = window.SR || {};
(function (SR) {
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const PALETTE = ['#4f8cff', '#f0545b', '#3fb768', '#e3a33b', '#a76cf5', '#22b8cf', '#f06595', '#94a3b8', '#fab005', '#12b886'];
  const fmtTime = (ms) => new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const fmtNum = (n, d = 0) => (n === null || n === undefined) ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d });

  function baseOptions(yTitle) {
    const grid = css('--border'), text = css('--muted');
    return {
      responsive: true, maintainAspectRatio: false, animation: false, parsing: false, normalized: true,
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      plugins: { legend: { labels: { color: text, boxWidth: 12 } },
        tooltip: { callbacks: { title: (items) => items.length ? fmtTime(items[0].parsed.x) : '' } } },
      scales: {
        x: { type: 'linear', ticks: { color: text, maxTicksLimit: 8, callback: (v) => fmtTime(v) }, grid: { color: grid } },
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
      this.charts = {};
      this.timer = null;
    }
    canvas(name) { return this.root.querySelector(`[data-chart="${name}"]`); }
    chart(name, config) {
      if (this.charts[name]) {
        this.charts[name].data = config.data;
        this.charts[name].update('none');
      } else {
        this.charts[name] = new Chart(this.canvas(name), config);
      }
    }
    url() {
      const p = new URLSearchParams({ db: this.db, app: this.app });
      if (this.from) p.set('from', this.from); else p.set('range', this.range);
      if (this.to && !this.live) p.set('to', this.to);
      return '/api/influx/dashboard?' + p.toString();
    }
    async refresh() {
      const state = this.root.querySelector('[data-role="state"]');
      try {
        const d = await SR.getJSON(this.url());
        this.render(d);
        const errs = Object.entries(d.errors || {});
        state.className = 'badge ' + (errs.length ? 'stopped' : (this.live ? 'running' : 'finished'));
        state.textContent = (this.live ? 'live · every 5 s' : 'execution window') + (errs.length ? ` · ${errs.length} panel(s) failed` : '');
        state.title = errs.map(([k, v]) => `${k}: ${v}`).join('\n');
        let note = this.root.querySelector('[data-role="panel-errors"]');
        if (!note) { note = document.createElement('div'); note.dataset.role = 'panel-errors'; note.className = 'flash warn'; state.parentElement.after(note); }
        note.style.display = errs.length ? '' : 'none';
        note.textContent = errs.length ? 'InfluxDB rejected: ' + errs.map(([k, v]) => `${k} → ${v}`).join(' | ') + ' (Settings → InfluxDB diagnostics)' : '';
        this.root.querySelector('[data-role="window"]').textContent =
          `${new Date(d.start).toLocaleString()} → ${new Date(d.end).toLocaleTimeString()} · bucket ${d.bucket_s}s`;
      } catch (e) {
        state.className = 'badge failed'; state.textContent = e.message;
      }
      if (this.live) this.timer = setTimeout(() => this.refresh(), 5000);
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

      const accent = css('--accent') || PALETTE[0], err = css('--err') || PALETTE[1];
      this.chart('vusers', { type: 'line', options: baseOptions('users'),
        data: { datasets: [line('Active threads', d.vusers, accent, { fill: true, stepped: true, tension: 0 })] } });
      this.chart('hits', { type: 'line', options: baseOptions('per second'),
        data: { datasets: [line('Hits/s', d.hps, PALETTE[2]), line('Errors/s', d.eps, err)] } });
      this.chart('rt', { type: 'line', options: baseOptions('ms'),
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
      this.chart('p95tx', { type: 'line', options: baseOptions('ms'), data: { datasets: txSets } });

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
