/* Scripts_Repo JMeter Control Center – shared UI helpers (no framework, no build step). */
window.SR = window.SR || {};
(function (SR) {
  const csrf = () => document.querySelector('meta[name="csrf-token"]').content;
  SR.csrf = csrf;

  SR.getJSON = async (url) => {
    const r = await fetch(url, { headers: { 'X-CSRF-Token': csrf() }, credentials: 'same-origin' });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error || r.statusText);
    return body;
  };

  // ---- confirmations & password prompts declared with data-attributes ----
  document.addEventListener('submit', (ev) => {
    const f = ev.target;
    if (f.dataset.confirm && !confirm(f.dataset.confirm)) { ev.preventDefault(); return; }
    if (f.hasAttribute('data-prompt-password')) {
      const p = prompt('New password (min. 10 characters):');
      if (!p) { ev.preventDefault(); return; }
      f.querySelector('input[name=password]').value = p;
    }
  });

  // ---- run dialog ----
  document.addEventListener('click', (ev) => {
    const b = ev.target.closest('[data-run-tag]');
    if (!b) return;
    const dlg = document.getElementById('dlg-run');
    dlg.querySelector('#run-tag').value = b.dataset.runTag;
    dlg.querySelector('#run-tag-label').textContent = b.dataset.runTag;
    dlg.querySelector('#run-script').textContent = b.dataset.runScript;
    dlg.showModal();
  });

  // ---- dashboard status (slaves / influx) ----
  SR.loadStatus = async () => {
    try {
      const s = await SR.getJSON('/api/status');
      const ib = document.getElementById('influx-badge');
      if (ib) { ib.className = 'badge ' + (s.influx.ok ? 'up' : 'down'); ib.textContent = 'InfluxDB ' + (s.influx.ok ? 'up' : 'down'); ib.title = s.influx.detail; }
      s.slaves.forEach((sl) => {
        const el = document.querySelector(`[data-slave="${CSS.escape(sl.host)}"]`);
        if (el) { el.className = 'badge ' + (sl.up ? 'up' : 'down'); el.textContent = `Slave ${sl.host} ${sl.up ? 'up · ' + sl.ms + ' ms' : 'down'}`; el.title = sl.error || 'jmeter-server RMI port reachable'; }
      });
    } catch (e) { /* ignore */ }
  };

  // ---- run console ----
  const classify = (line) => {
    if (/^###/.test(line)) return 'hl-meta';
    if (/error|exception|fail|refused|not found/i.test(line)) return 'hl-err';
    if (/finaliz|guardados|summary =|end of run|tidying up/i.test(line)) return 'hl-ok';
    return '';
  };
  const fmtElapsed = (s) => [Math.floor(s / 3600), Math.floor(s % 3600 / 60), Math.floor(s % 60)].map((n) => String(n).padStart(2, '0')).join(':');

  SR.followRun = (el) => {
    if (!el) return;
    let offset = 0, done = false;
    const follow = document.getElementById('follow');
    const statusEl = document.getElementById('run-status');
    const tick = async () => {
      try {
        const d = await SR.getJSON(`/api/runs/${el.dataset.run}/log?offset=${offset}`);
        if (d.text) {
          const frag = document.createDocumentFragment();
          d.text.split(/(?<=\n)/).forEach((line) => {
            const span = document.createElement('span');
            const c = classify(line); if (c) span.className = c;
            span.textContent = line; frag.appendChild(span);
          });
          el.appendChild(frag);
          if (follow.checked) el.scrollTop = el.scrollHeight;
        }
        offset = d.offset;
        statusEl.textContent = d.status; statusEl.className = 'badge ' + d.status;
        if (d.started) document.getElementById('run-elapsed').textContent = fmtElapsed(((d.ended || Date.now() / 1000) - d.started));
        if (!['running', 'starting', 'stopping'].includes(d.status)) {
          done = true;
          if (d.result_dir && d.status === 'finished') {
            const rb = document.getElementById('report-btn');
            rb.href = el.dataset.reportBase.replace('__RUN__', encodeURIComponent(d.result_dir));
            rb.style.display = '';
          }
          document.querySelectorAll('#run-actions form').forEach((f) => f.remove());
          SR.liveStop && SR.liveStop();
        }
      } catch (e) { /* retry */ }
      if (!done) setTimeout(tick, 1500);
    };
    tick();
  };
})(window.SR);
