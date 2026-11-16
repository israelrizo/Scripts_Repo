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
      const sb = document.getElementById('servers-badge');
      if (sb) {
        try {
          const a = await SR.getJSON('/api/servers');
          if (a.error) { sb.className = 'badge down'; sb.textContent = a.auth ? 'AWS session expired' : 'AWS error'; sb.title = a.error; }
          else {
            const up = a.instances.filter((i) => i.state === 'running' && i.ssm).length;
            sb.className = 'badge ' + (up === a.instances.length ? 'up' : (up ? 'stopped' : 'down'));
            sb.textContent = `Servers ${up}/${a.instances.length} on` + (up && a.auto_off ? ` · auto-off ${a.auto_off}` : '');
          }
        } catch (e) { sb.className = 'badge down'; sb.textContent = 'Servers ?'; }
      }
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
            if (rb && el.dataset.reportBase) {
              rb.href = el.dataset.reportBase.replace('__RUN__', encodeURIComponent(d.result_dir));
              rb.style.display = '';
            }
          }
          document.querySelectorAll('#run-actions form').forEach((f) => f.remove());
          SR.liveStop && SR.liveStop();
        }
      } catch (e) { /* retry */ }
      if (!done) setTimeout(tick, 1500);
    };
    tick();
  };

  // ---- servers check dialog ----
  const td = (text, cls) => { const c = document.createElement('td'); c.textContent = text ?? '—'; if (cls) c.className = cls; return c; };
  async function checkServers(tag) {
    const dlg = document.getElementById('dlg-servers'); if (!dlg) return;
    const body = document.getElementById('srv-body');
    document.getElementById('srv-tag').textContent = tag;
    dlg.dataset.tag = tag;
    body.replaceChildren(Object.assign(document.createElement('tr'), { innerHTML: '<td colspan="6" class="empty">Resolving and connecting…</td>' }));
    if (!dlg.open) dlg.showModal();
    const url = JSON.parse(document.getElementById('servers-url').textContent);
    try {
      const d = await SR.getJSON(`${url}?tag=${encodeURIComponent(tag)}&props=${encodeURIComponent(document.getElementById('srv-props').value)}`);
      document.getElementById('srv-script').textContent = d.script;
      document.getElementById('srv-note').textContent = d.note || '';
      body.replaceChildren();
      if (!d.results.length) body.appendChild(Object.assign(document.createElement('tr'), { innerHTML: '<td colspan="6" class="empty">No HTTP samplers found.</td>' }));
      d.results.forEach((r) => {
        const tr = document.createElement('tr');
        tr.append(td(`${r.protocol}://${r.host}:${r.port}`, (r.ok ? 'ok-dot' : 'bad-dot') + ' mono'), td(r.samplers, 'num'),
          td(r.dns ? r.dns.join(', ') : (r.error || '—'), 'mono'), td(r.tcp_ms != null ? r.tcp_ms + ' ms' : '—', 'num'),
          td(r.tls), td(r.http || (r.ok ? '' : r.error)));
        body.appendChild(tr);
      });
    } catch (e) {
      body.replaceChildren(); const tr = document.createElement('tr'); tr.append(td(e.message)); body.appendChild(tr);
    }
  }
  document.addEventListener('click', (ev) => {
    const b = ev.target.closest('[data-servers-tag]');
    if (b) checkServers(b.dataset.serversTag);
    if (ev.target.id === 'srv-run') checkServers(document.getElementById('dlg-servers').dataset.tag);
  });

  // ---- Jira ticket lookup in the run dialog ----
  const jira = document.getElementById('run-jira');
  if (jira) {
    let timer;
    jira.addEventListener('input', () => {
      clearTimeout(timer);
      const info = document.getElementById('run-jira-info');
      const key = jira.value.trim().toUpperCase();
      if (!/^[A-Z][A-Z0-9_]{0,19}-\d{1,9}$/.test(key)) { info.textContent = 'A comment with the results is added when the run ends.'; return; }
      timer = setTimeout(async () => {
        info.textContent = 'Looking up ' + key + '…';
        try { const d = await SR.getJSON('/api/jira/' + key); info.textContent = `✓ ${d.key} · ${d.summary} (${d.status})`; }
        catch (e) { info.textContent = '⚠ ' + e.message; }
      }, 500);
    });
  }

  // ---- shift-left files preview ----
  const slb = document.getElementById('sl-preview');
  if (slb) slb.addEventListener('click', async () => {
    const box = document.getElementById('sl-files');
    box.replaceChildren();
    try {
      const files = await SR.getJSON(slb.dataset.url);
      Object.entries(files).forEach(([name, content]) => {
        const h = document.createElement('h3'); h.className = 'mt';
        h.textContent = name === '_pipelines' ? 'bitbucket-pipelines.yml (only if the repo has none)' : name;
        const pre = document.createElement('pre'); pre.className = 'code'; pre.textContent = content;
        box.append(h, pre);
      });
    } catch (e) { box.textContent = e.message; }
  });

  // ---- servers page: who holds the Master ----
  SR.masterLock = async () => {
    const box = document.getElementById('master-lock'); if (!box) return;
    const t = document.getElementById('lock-text');
    try {
      const d = await SR.getJSON(box.dataset.url);
      if (d.error) t.textContent = 'AWS: ' + d.error;
      else if (d.active) t.textContent = `🔒 ${d.active.user} is running ${d.active.tag} (run ${d.active.run}). New runs wait until it ends.`;
      else if (d.active_error) t.textContent = d.active_error;
      else if (d.instances.some((i) => i.role === 'master' && i.state === 'running' && i.ssm)) t.textContent = '✓ The Master is free: no test is running.';
      else t.textContent = 'The Master is not running.';
    } catch (e) { t.textContent = e.message; }
  };

  // ---- run dialog: auto-off notice ----
  const ao = document.getElementById('run-autooff');
  if (ao) SR.getJSON(ao.dataset.url).then((d) => {
    if (d.error) { ao.textContent = '⚠ AWS: ' + d.error; return; }
    const up = d.instances.filter((i) => i.state === 'running' && i.ssm).length;
    let msg = `Servers: ${up}/${d.instances.length} running.`;
    if (d.auto_off && d.auto_off_min != null) {
      const h = Math.floor(d.auto_off_min / 60), m = Math.round(d.auto_off_min % 60);
      msg += ` Automatic shutdown at ${d.auto_off} (in ${h} h ${m} min)` + (d.auto_off_min < 90 ? ' — ⚠ a long test will be cut.' : '.');
    }
    ao.textContent = msg;
  }).catch(() => {});

  // ---- reports stored on the Master ----
  const rrb = document.getElementById('remote-results-btn');
  if (rrb) rrb.addEventListener('click', async () => {
    const dlg = document.getElementById('dlg-remote'), body = document.getElementById('remote-body');
    body.replaceChildren(Object.assign(document.createElement('tr'), { innerHTML: '<td colspan="3" class="empty">Asking the Master…</td>' }));
    dlg.showModal();
    try {
      const d = await SR.getJSON(rrb.dataset.url);
      body.replaceChildren();
      if (!d.results.length) body.appendChild(Object.assign(document.createElement('tr'), { innerHTML: '<td colspan="3" class="empty">No results on the Master for this project.</td>' }));
      d.results.forEach((r) => {
        const tr = document.createElement('tr');
        const act = document.createElement('td'); act.className = 'right';
        if (r.local) act.textContent = '✓ on this computer';
        else {
          const b = document.createElement('button'); b.type = 'button'; b.className = 'btn sm primary'; b.textContent = 'Fetch';
          b.addEventListener('click', () => { document.getElementById('remote-result').value = r.name; document.getElementById('remote-form').submit(); });
          act.appendChild(b);
        }
        tr.append(td(r.name, 'mono'), td(r.mb + ' MB', 'num'), act);
        body.appendChild(tr);
      });
    } catch (e) { body.replaceChildren(); const tr = document.createElement('tr'); tr.append(td(e.message)); body.appendChild(tr); }
  });
})(window.SR);
