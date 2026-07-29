// Tab 7: Pipeline Triggers
// 5 backend endpoints exposed as buttons with confirm modal + history.
const PipelineTab = {
  STORAGE_KEY: 'pipeline_run_history_v1',
  _running: null,              // name of currently running pipeline (or null)
  _history: [],                // last 10 runs

  // Pipeline definitions (mirror backend /api/v1/pipeline/*)
  _pipelines: [
    {
      key: 'discover',
      name: '发现新源',
      icon: '🔍',
      desc: '调用 DiscoveryService 扫描 link_sources.json，评估链接质量并入库。',
      endpoint: '/api/v1/pipeline/discover',
      body: {},
      duration: '1-2 分钟',
      danger: 'safe',
      confirm: '扫描 link_sources.json 中的链接源，AI 评估质量后入库（pending 状态）。继续？',
    },
    {
      key: 'scrape-images',
      name: '抓取图片',
      icon: '📥',
      desc: '抓取已 approved 源的所有图片到本地，失败的记入失败表。',
      endpoint: '/api/v1/pipeline/scrape-images',
      body: {},
      duration: '5-30 分钟',
      danger: 'medium',
      confirm: '图片抓取会发起大量外网请求，耗时 5-30 分钟。确认继续？',
    },
    {
      key: 'generate',
      name: '生成每日 Pack',
      icon: '✨',
      desc: '用今日抓取的图片 + 审美模型生成 3 组每日推荐方案。',
      endpoint: '/api/v1/pipeline/generate',
      body: {},
      duration: '1-2 分钟',
      danger: 'safe',
      confirm: '调用 AI 生成 3 组每日推荐方案。确认继续？',
    },
    {
      key: 'full',
      name: '完整跑一遍',
      icon: '🚀',
      desc: '发现 → 抓图 → 任务 → 生成，串联跑一遍。',
      endpoint: '/api/v1/pipeline/full',
      body: {},
      duration: '10-30 分钟',
      danger: 'medium',
      confirm: '会把发现、抓图、生成三步全跑一遍，耗时约 10-30 分钟。确认继续？',
    },
    {
      key: 'cdp-publish',
      name: 'CDP 发布',
      icon: '📤',
      desc: '调用 Chrome 远程调试协议（需 Chrome 9222 端口运行）发布到小红书。',
      endpoint: '/api/v1/pipeline/cdp-publish',
      body: {},  // filled in at click time (pack_id prompt)
      duration: '1-2 分钟',
      danger: 'danger',
      confirm: 'CDP 发布会操控真实 Chrome 浏览器执行发布操作。受账号封禁影响，请确认账号状态。\n\n继续？',
      // special: requires pack_id field
      needsPackId: true,
    },
  ],

  async load() {
    const container = document.getElementById('tab-pipeline');
    this._loadHistory();
    container.innerHTML = this._renderLayout();
    this._bindActions(container);
    this._tickStatusBar();
  },

  // ── Render ──────────────────────────────────────────────────

  _renderLayout() {
    const statusBar = this._renderStatusBar();
    const grid = this._renderPipelineGrid();
    const history = this._renderHistory();
    return statusBar + grid + history;
  },

  _renderStatusBar() {
    const running = this._running;
    const lastRun = this._history[0];
    const lastRunText = lastRun
      ? `上次运行 <strong>${this._escape(lastRun.name)}</strong> ${lastRun.success ? '成功' : '失败'} · ${this._formatRelative(lastRun.ts)}`
      : '暂无历史记录';
    const stateText = running
      ? `正在跑 <strong>${this._escape(running)}</strong>…`
      : '系统空闲';
    const stateColor = running ? 'var(--yellow)' : 'var(--green)';
    return `
      <div class="card" id="pipeline-status-bar" style="margin-bottom:16px;border-left:3px solid ${stateColor}">
        <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
          <div style="display:flex;align-items:center;gap:8px">
            <span class="health-dot" style="color:${stateColor};font-size:14px">●</span>
            <span style="font-size:14px">${stateText}</span>
          </div>
          <div style="font-size:12px;color:var(--text-dim);margin-left:auto" data-last-run>${lastRunText}</div>
        </div>
      </div>
    `;
  },

  _renderPipelineGrid() {
    const cards = this._pipelines.map(p => this._renderPipelineCard(p)).join('');
    return `
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin-bottom:24px">
        ${cards}
      </div>
    `;
  },

  _renderPipelineCard(p) {
    const dangerBadge = {
      safe: '<span class="tag tag-green">安全</span>',
      medium: '<span class="tag tag-yellow">中等</span>',
      danger: '<span class="tag tag-red">慎用</span>',
    }[p.danger] || '';
    const disabled = this._running ? 'disabled' : '';
    const btnText = this._running ? '⏳ 正在跑…' : '▶ 启动';
    const dangerBtnClass = p.danger === 'danger' ? 'btn-danger' : 'btn-primary';
    return `
      <div class="card pipeline-card" data-key="${p.key}" style="display:flex;flex-direction:column;gap:8px">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
          <div class="card-title">${p.icon} ${this._escape(p.name)}</div>
          ${dangerBadge}
        </div>
        <p style="font-size:13px;color:var(--text-muted);margin:0;flex:1">${this._escape(p.desc)}</p>
        <div style="display:flex;align-items:center;gap:8px;margin-top:4px">
          <span class="tag tag-muted">⏱ ${p.duration}</span>
          <button class="btn ${dangerBtnClass} btn-sm btn-pipeline" data-key="${p.key}" style="margin-left:auto" ${disabled}>${btnText}</button>
        </div>
      </div>
    `;
  },

  _renderHistory() {
    if (!this._history.length) {
      return `
        <div class="card" style="margin-top:8px">
          <div class="card-title" style="margin-bottom:8px">📜 最近运行历史</div>
          <div style="font-size:13px;color:var(--text-dim)">还没有运行记录。点上面的按钮启动一个 pipeline。</div>
        </div>
      `;
    }
    const rows = this._history.map((h, i) => {
      const icon = h.success ? '✅' : '❌';
      const color = h.success ? 'var(--green)' : 'var(--red)';
      const dur = h.durationMs ? `${(h.durationMs / 1000).toFixed(1)}s` : '';
      const errorLine = h.error ? `<div style="font-size:12px;color:var(--red);margin-top:4px">${this._escape(h.error)}</div>` : '';
      return `
        <div class="card" style="padding:10px 14px;margin-bottom:8px">
          <div style="display:flex;align-items:center;gap:10px">
            <span style="color:${color};font-size:16px">${icon}</span>
            <div style="flex:1;min-width:0">
              <div style="font-size:13px;font-weight:500">${this._escape(h.name)}</div>
              <div style="font-size:11px;color:var(--text-dim);margin-top:2px">${h.ts} ${dur ? '· '+dur : ''}</div>
              ${errorLine}
            </div>
            <div style="font-size:12px;color:var(--text-muted);max-width:50%;text-align:right">${this._escape(h.message || '')}</div>
          </div>
        </div>
      `;
    }).join('');
    return `
      <div style="margin-top:8px">
        <div class="card-title" style="margin-bottom:8px">📜 最近运行历史（${this._history.length}）</div>
        ${rows}
      </div>
    `;
  },

  // ── Bind ─────────────────────────────────────────────────────

  _bindActions(container) {
    container.querySelectorAll('.btn-pipeline').forEach(btn => {
      btn.addEventListener('click', () => {
        const key = btn.dataset.key;
        const p = this._pipelines.find(x => x.key === key);
        if (!p) return;
        this._confirmAndRun(p);
      });
    });
  },

  async _confirmAndRun(p) {
    if (this._running) {
      App.toast(`正在运行 ${this._running}，请等待`, 'error');
      return;
    }

    // CDP publish needs a pack_id (or manual title/content/images)
    let body = p.body || {};
    if (p.needsPackId) {
      const packId = prompt('输入要发布的 pack_id（留空将发送空请求并返回错误）：', '');
      if (packId === null) return;  // cancelled
      body = { pack_id: packId.trim() };
    }

    const confirmed = confirm(p.confirm);
    if (!confirmed) return;

    this._running = p.name;
    this._refreshUI();

    const startTs = Date.now();
    let result = null;
    let error = null;
    try {
      result = await API.post(p.endpoint, body);
    } catch (e) {
      error = e;
    }
    const durationMs = Date.now() - startTs;

    this._running = null;
    const success = !error && result && result.success;
    const message = error ? error.message : (result?.message || (success ? '完成' : '失败'));
    this._recordHistory({
      key: p.key,
      name: p.name,
      success,
      message,
      error: error ? String(error.message || error) : null,
      durationMs,
      ts: new Date().toISOString(),
      postUrl: result?.data?.post_url || '',
    });

    if (success) {
      App.toast(`✓ ${p.name}: ${message}`, 'success');
    } else {
      App.toast(`${p.name} 失败: ${message}`, 'error');
    }

    this._refreshUI();
  },

  // ── History (localStorage-only) ──────────────────────────────

  _loadHistory() {
    try {
      const raw = localStorage.getItem(this.STORAGE_KEY);
      this._history = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(this._history)) this._history = [];
    } catch (e) {
      this._history = [];
    }
  },

  _saveHistory() {
    try {
      localStorage.setItem(this.STORAGE_KEY, JSON.stringify(this._history.slice(0, 10)));
    } catch (e) { /* quota or disabled — ignore */ }
  },

  _recordHistory(entry) {
    this._history.unshift(entry);
    this._history = this._history.slice(0, 10);
    this._saveHistory();
  },

  // ── UI helpers ───────────────────────────────────────────────

  _refreshUI() {
    const container = document.getElementById('tab-pipeline');
    if (!container) return;
    container.innerHTML = this._renderLayout();
    this._bindActions(container);
  },

  _tickStatusBar() {
    // Recompute "X minutes ago" text every 30s while tab is active
    if (this._tickTimer) clearInterval(this._tickTimer);
    this._tickTimer = setInterval(() => {
      if (this._running) return;  // no need to refresh during run
      const bar = document.getElementById('pipeline-status-bar');
      if (!bar) return;
      const lastRun = this._history[0];
      const lastRunText = lastRun
        ? `上次运行 <strong>${this._escape(lastRun.name)}</strong> ${lastRun.success ? '成功' : '失败'} · ${this._formatRelative(lastRun.ts)}`
        : '暂无历史记录';
      const dim = bar.querySelector('[data-last-run]');
      if (dim) dim.innerHTML = lastRunText;
    }, 30000);
  },

  _formatRelative(isoTs) {
    if (!isoTs) return '';
    const ts = new Date(isoTs).getTime();
    const diff = Date.now() - ts;
    if (diff < 0) return '刚刚';
    if (diff < 60000) return `${Math.floor(diff / 1000)} 秒前`;
    if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`;
    return `${Math.floor(diff / 86400000)} 天前`;
  },

  _escape(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
  },
};
