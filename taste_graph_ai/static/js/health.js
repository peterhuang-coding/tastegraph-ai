// Tab 6: System Health — full diagnostic dashboard
const HealthTab = {
  _data: null,

  async load() {
    const container = document.getElementById('tab-health');
    App.renderLoading(container);
    try {
      const data = await API.get('/api/v1/health/detailed');
      this._data = data;
      this.render(container, data);
    } catch (e) {
      container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">⚠️</div><p>健康检查加载失败: ${App.esc(e.message)}</p><p style="font-size:12px;color:var(--text-dim)">检查后端 /api/v1/health/detailed 是否可用</p></div>`;
    }
  },

  render(container, data) {
    const cards = [
      this._serverCard(data.server),
      this._daemonsCard(data.daemons),
      this._cdpCard(data.cdp),
      this._databaseCard(data.database),
      this._gitCard(data.git),
      this._dataDirsCard(data.dataDirs),
    ];

    const errorsBlock = (data.errors && data.errors.length)
      ? `<div class="card" style="border-left:3px solid var(--yellow);margin-top:16px"><div class="card-title">⚠ 采集警告 (${data.errors.length})</div><ul style="margin-top:8px;font-size:13px;color:var(--text-muted);padding-left:18px">${data.errors.map(e => `<li>${App.esc(e)}</li>`).join('')}</ul></div>`
      : '';

    container.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <div>
          <span style="font-size:13px;color:var(--text-dim)">最后检查: ${this._formatTs(data.checkedAt)}</span>
        </div>
        <button class="btn btn-ghost btn-sm" onclick="HealthTab.load()">🔄 重新检查</button>
      </div>
      <div class="health-grid">
        ${cards.join('')}
      </div>
      ${errorsBlock}
    `;
    this._bindExpands(container);
  },

  _serverCard(server) {
    const mem = server.memoryMb != null ? `${server.memoryMb} MB` : '—';
    const cpu = server.cpuPercent != null ? `${server.cpuPercent.toFixed(1)}%` : '—';
    const status = server.memoryMb && server.memoryMb > 1024 ? 'warn' : 'ok';
    return this._card({
      icon: '🖥',
      title: '服务器进程',
      summary: `PID ${server.pid} · ${mem} RSS · CPU ${cpu}`,
      level: status,
      detail: server,
    });
  },

  _daemonsCard(daemons) {
    const total = daemons.length;
    const loaded = daemons.filter(d => d.loaded).length;
    const failed = daemons.filter(d => d.lastExitCode && d.lastExitCode !== 0).length;
    const level = failed > 0 ? 'warn' : (loaded < total ? 'warn' : 'ok');
    const summary = `${loaded}/${total} 已加载${failed > 0 ? ` · ${failed} 异常退出` : ''}`;
    return this._card({
      icon: '⚙️',
      title: 'Launchd 守护进程',
      summary,
      level,
      detail: daemons,
    });
  },

  _cdpCard(cdp) {
    const level = cdp.reachable ? 'ok' : 'err';
    const summary = cdp.reachable
      ? `已连接 · ${(cdp.browser || '').slice(0, 40)}`
      : 'CDP 端口 9222 不可达';
    return this._card({
      icon: '🌐',
      title: 'Chrome DevTools',
      summary,
      level,
      detail: cdp,
    });
  },

  _databaseCard(db) {
    const size = db.sizeMb != null ? `${db.sizeMb} MB` : '—';
    const level = db.sizeMb == null ? 'err' : 'ok';
    const summary = `${db.tables.length} 张表 · ${size}`;
    return this._card({
      icon: '🗄',
      title: 'SQLite 数据库',
      summary,
      level,
      detail: db,
    });
  },

  _gitCard(git) {
    const dirty = (git.uncommitted || 0) + (git.untracked || 0);
    const level = dirty > 0 ? 'warn' : 'ok';
    const summary = `${git.branch || '?'} · ${(git.commit || '').slice(0, 7)}${dirty ? ` · ${dirty} 变更` : ''}`;
    return this._card({
      icon: '🌿',
      title: 'Git 状态',
      summary,
      level,
      detail: git,
    });
  },

  _dataDirsCard(dirs) {
    const images = dirs.imagesMb != null ? `${dirs.imagesMb} MB` : '—';
    const exports = dirs.exportsMb != null ? `${dirs.exportsMb} MB` : '—';
    const logs = dirs.logsMb != null ? `${dirs.logsMb} MB` : '—';
    const level = 'ok';
    const summary = `图片 ${images} · 导出 ${exports} · 日志 ${logs}`;
    return this._card({
      icon: '📦',
      title: '数据目录',
      summary,
      level,
      detail: dirs,
    });
  },

  _card({ icon, title, summary, level, detail }) {
    const levelMeta = {
      ok:  { dot: '🟢', cls: 'health-ok',  label: '正常' },
      warn: { dot: '🟡', cls: 'health-warn', label: '警告' },
      err: { dot: '🔴', cls: 'health-err',  label: '异常' },
    }[level] || { dot: '⚪', cls: '', label: '未知' };

    return `
      <div class="health-card ${levelMeta.cls}" data-expand="0">
        <div class="health-card-head">
          <span class="health-card-icon">${icon}</span>
          <div style="flex:1;min-width:0">
            <div class="health-card-title">${title}</div>
            <div class="health-card-summary">${levelMeta.dot} ${App.esc(summary)}</div>
          </div>
        </div>
        <pre class="health-card-detail" hidden>${App.esc(JSON.stringify(detail, null, 2))}</pre>
      </div>
    `;
  },

  _bindExpands(container) {
    container.querySelectorAll('.health-card').forEach(card => {
      card.addEventListener('click', () => {
        const detail = card.querySelector('.health-card-detail');
        const expanded = card.dataset.expand === '1';
        detail.hidden = expanded;
        card.dataset.expand = expanded ? '0' : '1';
      });
    });
  },

  _formatTs(ts) {
    if (!ts) return '—';
    try { return new Date(ts * 1000).toLocaleString('zh-CN'); }
    catch (e) { return String(ts); }
  },
};