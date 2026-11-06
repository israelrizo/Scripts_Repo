/* Confluence report form: renders light-theme charts for export and sends them as PNG with the form. */
(function () {
  const form = document.getElementById('report-form');
  if (!form) return;
  const PALETTE = ['#1868db', '#c9372c', '#1f845a', '#e06c00', '#8270db', '#0c8599', '#ae2e24', '#626f86'];
  const INK = '#172b4d', GRID = '#dcdfe4';
  const fmtTime = (ms) => new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const whiteBg = { id: 'whiteBg', beforeDraw: (c) => { const x = c.ctx; x.save(); x.fillStyle = '#fff'; x.fillRect(0, 0, c.width, c.height); x.restore(); } };
  const charts = {};
  let ready = false;

  const lineOpts = (yTitle) => ({
    responsive: false, animation: false, parsing: false, devicePixelRatio: 1.5,
    plugins: { legend: { labels: { color: INK, boxWidth: 14, font: { size: 13 } } } },
    scales: {
      x: { type: 'linear', ticks: { color: INK, maxTicksLimit: 10, callback: (v) => fmtTime(v) }, grid: { color: GRID } },
      y: { beginAtZero: true, ticks: { color: INK }, grid: { color: GRID }, title: { display: true, text: yTitle, color: INK } },
    },
  });
  const xy = (pts) => pts.map(([x, y]) => ({ x, y }));
  const ds = (label, pts, color, extra = {}) => ({ label, data: xy(pts), borderColor: color, backgroundColor: color + '30', borderWidth: 2, pointRadius: 0, tension: 0.2, ...extra });

  function draw(key, config) {
    const canvas = document.querySelector(`canvas[data-export="${key}"]`);
    if (!canvas) return;
    config.plugins = [whiteBg];
    charts[key] = new Chart(canvas, config);
  }

  async function render() {
    const box = document.getElementById('export-charts');
    if (!box) { ready = true; return; }
    const p = new URLSearchParams({ db: box.dataset.db, app: box.dataset.app, from: box.dataset.from, to: box.dataset.to });
    try {
      const d = await SR.getJSON('/api/influx/dashboard?' + p);
      draw('usuarios_activos', { type: 'line', options: lineOpts('usuarios'), data: { datasets: [ds('Usuarios activos', d.vusers, PALETTE[0], { fill: true, stepped: true, tension: 0 })] } });
      draw('throughput', { type: 'line', options: lineOpts('hits / s'), data: { datasets: [ds('Hits por segundo', d.hps, PALETTE[2])] } });
      draw('errores', { type: 'line', options: lineOpts('errores / s'), data: { datasets: [ds('Errores por segundo', d.eps, PALETTE[1], { fill: true })] } });
      draw('tiempos_respuesta', { type: 'line', options: lineOpts('ms'), data: { datasets: [ds('Promedio', d.avg, PALETTE[0]), ds('Percentil 95', d.p95, PALETTE[3], { borderDash: [6, 3] })] } });
      draw('p95_transacciones', { type: 'line', options: lineOpts('ms'), data: { datasets: Object.entries(d.p95_by_tx).map(([n, pts], i) => ds(n, pts, PALETTE[i % PALETTE.length])) } });
      // Errors section: distribution of the failed requests only (the OK share would hide them)
      const ERR = ['#c9372c', '#e06c00', '#8270db', '#0c8599', '#ae2e24', '#b38600', '#626f86', '#1868db'];
      const errCodes = d.codes.filter((c) => !c.code.startsWith('OK'));
      const codes = errCodes.length ? errCodes : (d.codes.length ? d.codes : [{ code: 'Sin datos', count: 1 }]);
      const pct = (n) => (d.totals.req ? (n * 100 / d.totals.req).toFixed(2) : '0') + ' % del total';
      draw('codigos_respuesta', { type: 'doughnut', data: {
          labels: codes.map((c) => `${c.code}: ${Number(c.count).toLocaleString()} (${pct(c.count)})`),
          datasets: [{ data: codes.map((c) => c.count), backgroundColor: codes.map((c, i) => c.code.startsWith('OK') ? PALETTE[2] : ERR[i % ERR.length]), borderColor: '#fff', borderWidth: 2 }] },
        options: { responsive: false, animation: false, devicePixelRatio: 1.5, cutout: '55%', layout: { padding: 10 },
          plugins: { legend: { position: 'right', labels: { color: INK, font: { size: 13 } } } } } });
    } catch (e) {
      const note = document.createElement('div');
      note.className = 'flash warn';
      note.textContent = 'Charts not rendered: ' + e.message;
      box.before(note);
    }
    ready = true;
  }

  form.addEventListener('submit', (ev) => {
    const action = ev.submitter && ev.submitter.value;
    if (action === 'regen') return;
    if (!ready) { ev.preventDefault(); alert('Charts are still loading, try again in a second.'); return; }
    Object.entries(charts).forEach(([key, chart]) => {
      document.getElementById('img_' + key).value = chart.toBase64Image('image/png');
    });
    if (action === 'publish') {
      if (!confirm('Publish this report to Confluence?')) { ev.preventDefault(); return; }
      document.getElementById('publish-note').textContent = 'Publishing… uploading attachments can take a minute.';
    }
  });

  // live "auto" status while editing the acceptance criteria
  const totals = JSON.parse(form.dataset.totals);
  const opt = document.getElementById('auto-opt');
  const val = (n) => { const v = form.querySelector(`[name="${n}"]`).value.trim(); return v === '' ? null : Number(v); };
  const recompute = () => {
    const checks = [];
    if (val('crit_avg') !== null && totals.avg != null) checks.push(totals.avg <= val('crit_avg'));
    if (val('crit_p95') !== null && totals.p95 != null) checks.push(totals.p95 <= val('crit_p95'));
    if (val('crit_err') !== null) checks.push(totals.error_pct <= val('crit_err'));
    if (val('crit_tps') !== null) checks.push(totals.tps >= val('crit_tps'));
    opt.textContent = 'Automático según criterios → ' + (checks.length ? (checks.every(Boolean) ? 'SATISFACTORIA' : 'INSATISFACTORIA') : 'sin criterios');
  };
  ['crit_avg', 'crit_p95', 'crit_err', 'crit_tps'].forEach((n) => form.querySelector(`[name="${n}"]`).addEventListener('input', recompute));

  render();
})();
