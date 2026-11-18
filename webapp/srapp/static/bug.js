/* Jira bug form: draws the response time and errors charts (light theme, white background) and sends them as PNG
   with the form, so they are attached to the issue and embedded in its description. */
(function () {
  const form = document.getElementById('bug-form');
  const dataEl = document.getElementById('bug-series');
  if (!form || !dataEl || !window.Chart) return;
  const d = JSON.parse(dataEl.textContent);
  const PALETTE = ['#1868db', '#e06c00', '#8270db', '#0c8599', '#ae2e24', '#626f86', '#1f845a'];
  const INK = '#172b4d', GRID = '#dcdfe4', RED = '#c9372c';
  const span = (sets) => {
    const xs = sets.flatMap((s) => s.pts.map((p) => p[0]));
    return xs.length ? Math.max(...xs) - Math.min(...xs) : 0;
  };
  const fmt = (ms, wide) => new Date(ms).toLocaleString([], wide
    ? { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }
    : { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const whiteBg = { id: 'whiteBg', beforeDraw: (c) => { const x = c.ctx; x.save(); x.fillStyle = '#fff'; x.fillRect(0, 0, c.width, c.height); x.restore(); } };
  const charts = {};
  // few samples (short run, coarse report granularity) -> show the points, a single one has no line to draw
  const radius = (pts) => (pts.length <= 3 ? 5 : pts.length <= 30 ? 3 : 0);
  const win = Array.isArray(d.window) ? d.window : null;

  function draw(key, title, yTitle, sets, colorOf) {
    const canvas = document.querySelector(`canvas[data-bug-chart="${key}"]`);
    if (!canvas || !sets.length) return;
    const wide = span(sets) > 20 * 3600e3;
    charts[key] = new Chart(canvas, {
      type: 'line', plugins: [whiteBg],
      data: { datasets: sets.map((s, i) => ({ label: s.label, data: s.pts.map(([x, y]) => ({ x, y })), borderColor: colorOf(s, i),
        backgroundColor: colorOf(s, i) + '30', borderWidth: 2, pointRadius: radius(s.pts), pointBackgroundColor: colorOf(s, i),
        tension: 0.2, borderDash: s.dash ? [6, 3] : [], spanGaps: true,
        fill: key === 'err' && i === 0 })) },
      options: { responsive: false, animation: false, parsing: false, devicePixelRatio: 1.5,
        plugins: { title: { display: true, text: title, color: INK, font: { size: 16, weight: 'bold' } },
          legend: { labels: { color: INK, boxWidth: 14, font: { size: 12 } } } },
        scales: { x: { type: 'linear', min: win ? win[0] : undefined, max: win ? win[1] : undefined, ticks: { color: INK, maxTicksLimit: 9, callback: (v) => fmt(v, wide) }, grid: { color: GRID } },
          y: { beginAtZero: true, ticks: { color: INK }, grid: { color: GRID }, title: { display: true, text: yTitle, color: INK } } } },
    });
  }

  draw('rt', 'Tiempo de respuesta', 'ms', d.rt || [], (s, i) => (s.dash ? RED : PALETTE[i % PALETTE.length]));
  draw('err', 'Errores por segundo', 'errores / s', d.err || [], (s, i) => (i === 0 ? RED : PALETTE[(i + 1) % PALETTE.length]));

  form.addEventListener('submit', () => {
    const put = (key, id) => { const el = document.getElementById(id); if (el && charts[key]) el.value = charts[key].toBase64Image('image/png'); };
    put('rt', 'img_bug_tiempo_respuesta');
    put('err', 'img_bug_errores');
  });
})();
