// Tab 8: 🕷 爬虫 — 源管理 dashboard
// 后端端点：
//   GET /api/v1/crawler/sources → 合并 link_sources.json (声明) + DB (已注册) + orphan
//   GET /api/v1/crawler/stats   → 顶部 4 卡片 + 按分类聚合
const CrawlerTab = {
  _data: null,       // /sources 完整返回
  _stats: null,      // /stats 返回
  _filter: {
    q: '',           // 搜索关键字（name / url / why）
    cat: 'all',      // category
    status: 'all',   // 'all' | 'in_db' | 'pending'
  },

  async load() {
    const container = document.getElementById('tab-crawler');
    App.renderLoading(container);
    try {
      const [data, stats] = await Promise.all([
        API.get('/api/v1/crawler/sources'),
        API.get('/api/v1/crawler/stats'),
      ]);
      this._data = data;
      this._stats = stats;
      this.render(container);
    } catch (e) {
      container.innerHTML = `<div class="empty-state"><p>加载失败: ${App.esc(e.message)}</p><p style="font-size:12px;color:var(--text-dim);margin-top:4px">后端 crawler router 需要先在 router.py 注册</p></div>`;
    }
  },

  render(container) {
    const { total_declared, total_in_db, pending_count, orphan_count, sources, orphans } = this._data;
    const { by_category } = this._stats;
    const coverage = total_declared > 0
      ? Math.round(100 * total_in_db / (total_declared + orphan_count) * 100) / 100
      : 0;

    let html = '';

    // ── ① 顶部 4 卡片 ──────────────────────────────────────────
    html += `<div class="stats-grid">
      <div class="stat-card">
        <div class="stat-value" style="color:var(--accent-bright)">${total_declared}</div>
        <div class="stat-label">📜 已声明源</div>
        <div style="font-size:11px;color:var(--text-dim);margin-top:4px">link_sources.json</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" style="color:var(--green)">${total_in_db}</div>
        <div class="stat-label">✅ 已入库</div>
        <div style="font-size:11px;color:var(--text-dim);margin-top:4px">DB 已注册</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" style="color:var(--yellow)">${pending_count}</div>
        <div class="stat-label">⏳ 待爬取</div>
        <div style="font-size:11px;color:var(--text-dim);margin-top:4px">声明了未入库</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" style="color:var(--red)">${orphan_count}</div>
        <div class="stat-label">👻 孤儿源</div>
        <div style="font-size:11px;color:var(--text-dim);margin-top:4px">DB 里有未声明</div>
      </div>
    </div>`;

    // ── ② 10 分类下钻 ──────────────────────────────────────────
    html += `<div class="card" style="margin-top:16px">
      <div class="card-header">
        <div class="card-title">📊 分类下钻</div>
        <div style="font-size:12px;color:var(--text-dim)">覆盖率 = in_db / total</div>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th style="text-align:left">分类</th>
            <th>声明总数</th>
            <th>已入库</th>
            <th>待爬取</th>
            <th>累计图片</th>
            <th>累计失败</th>
            <th style="width:140px">覆盖率</th>
          </tr>
        </thead>
        <tbody>`;
    // 稳定排序：先按 _orphan 最后，其它按 total 降序
    const ordered = Object.entries(by_category).sort(([a], [b]) => {
      if (a === '_orphan') return 1;
      if (b === '_orphan') return -1;
      return 0;
    });
    for (const [cat, b] of ordered) {
      const ratio = b.total > 0 ? Math.round(100 * b.in_db / b.total) : 0;
      const barColor = ratio >= 80 ? 'var(--green)' : ratio >= 40 ? 'var(--yellow)' : 'var(--red)';
      const labelMap = {
        lookbook_images: 'Lookbook 图集',
        videos: '视频',
        articles: '文章',
        architecture_interiors: '建筑空间',
        japanese_korean_aesthetics: '日韩美学',
        archive_reference: '档案参考',
        street_photography: '街头摄影',
        product_object_design: '产品设计',
        _orphan: '🟣 孤儿（DB 里有 / 未声明）',
      };
      const label = labelMap[cat] || cat;
      const isOrphan = cat === '_orphan';
      html += `<tr style="${isOrphan ? 'background:rgba(255,255,255,0.02)' : ''}">
        <td style="text-align:left;font-family:monospace;font-size:12px">${App.esc(label)}</td>
        <td>${b.total}</td>
        <td style="color:${b.in_db > 0 ? 'var(--green)' : 'var(--text-dim)'}">${b.in_db}</td>
        <td style="color:${b.pending > 0 ? 'var(--yellow)' : 'var(--text-dim)'}">${b.pending}</td>
        <td>${b.imgs.toLocaleString()}</td>
        <td style="color:${b.fails > b.imgs ? 'var(--red)' : 'var(--text)'}">${b.fails.toLocaleString()}</td>
        <td>
          <div style="display:flex;align-items:center;gap:6px">
            <div style="flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden">
              <div style="width:${ratio}%;height:100%;background:${barColor}"></div>
            </div>
            <span style="font-size:11px;color:var(--text-dim);min-width:30px;text-align:right">${ratio}%</span>
          </div>
        </td>
      </tr>`;
    }
    html += `</tbody></table></div>`;

    // ── ③ 过滤栏 ──────────────────────────────────────────────
    const cats = Array.from(new Set(sources.map(s => s.category))).sort();
    html += `<div class="card" style="margin-top:16px">
      <div class="card-header">
        <div class="card-title">🔍 全部源（${sources.length} 声明 + ${orphans.length} 孤儿）</div>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
        <input id="crawler-search" type="text" class="input" placeholder="搜索 name / url / why..."
               value="${App.esc(this._filter.q)}"
               style="flex:1;min-width:240px;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text)">
        <select id="crawler-cat" class="input" style="padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text)">
          <option value="all">所有分类</option>
          ${cats.map(c => `<option value="${App.esc(c)}" ${this._filter.cat === c ? 'selected' : ''}>${App.esc(c)}</option>`).join('')}
          <option value="orphan" ${this._filter.cat === 'orphan' ? 'selected' : ''}>🟣 orphan</option>
        </select>
        <select id="crawler-status" class="input" style="padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text)">
          <option value="all">所有状态</option>
          <option value="pending" ${this._filter.status === 'pending' ? 'selected' : ''}>⏳ 待爬取</option>
          <option value="in_db" ${this._filter.status === 'in_db' ? 'selected' : ''}>✅ 已入库</option>
        </select>
        <button class="btn btn-ghost btn-sm" onclick="CrawlerTab.resetFilter()">重置</button>
      </div>`;

    // ── ④ 源表格 ──────────────────────────────────────────────
    const rows = this._buildRows();
    html += `<div id="crawler-table-wrap">${this._renderRows(rows, sources.length + orphans.length)}</div>`;

    // ── 关闭 card ─────────────────────────────────────────────
    html += `</div>`;

    container.innerHTML = html;
    this._bindFilter(container);
  },

  _buildRows() {
    const { sources, orphans } = this._data;
    const f = this._filter;
    const q = (f.q || '').trim().toLowerCase();
    const all = [...sources.map(s => ({ ...s, _origin: 'declared' })), ...orphans.map(o => ({ ...o, _origin: 'orphan' }))];

    return all.filter(row => {
      // category filter
      if (f.cat === 'orphan') {
        if (row._origin !== 'orphan') return false;
      } else if (f.cat !== 'all') {
        if (row.category !== f.cat) return false;
      }
      // status filter
      if (f.status === 'pending') {
        if (row.in_db) return false;
      } else if (f.status === 'in_db') {
        if (!row.in_db) return false;
      }
      // search
      if (q) {
        const hay = `${row.name || ''}\n${row.url || ''}\n${row.why || ''}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  },

  _renderRows(rows, totalAll) {
    if (rows.length === 0) {
      return '<div class="empty-state"><p>没有匹配的源</p></div>';
    }
    const catLabel = {
      lookbook_images: 'Lookbook',
      videos: '视频',
      articles: '文章',
      architecture_interiors: '建筑',
      japanese_korean_aesthetics: '日韩',
      archive_reference: '档案',
      street_photography: '街头',
      product_object_design: '产品',
      orphan: '🟣 orphan',
    };
    let html = `<table class="data-table">
      <thead>
        <tr>
          <th style="width:60px">入库</th>
          <th style="text-align:left">源名</th>
          <th>分类</th>
          <th>类型</th>
          <th>状态</th>
          <th>图片</th>
          <th>失败</th>
          <th style="text-align:left">URL</th>
        </tr>
      </thead>
      <tbody>`;
    rows.forEach(s => {
      const imgs = s.imgs || 0;
      const fails = s.fails || 0;
      const inDb = !!s.in_db;
      // pending = 声明了但 in_db=false → 黄底
      const pending = !inDb && s._origin === 'declared';
      // 高失败率（fails > imgs 且有 imgs 或 fails>10）
      const failHigh = imgs > 0 && fails > imgs;
      const failHighEmpty = imgs === 0 && fails > 5;

      const bg = pending ? 'background:rgba(234,179,8,0.12)' : '';
      const failColor = (failHigh || failHighEmpty) ? 'var(--red)' : 'var(--text)';
      const statusLabel = pending
        ? '<span style="color:var(--yellow)">⏳ pending</span>'
        : ({approved:'✅ approved', pending:'🟡 pending', rejected:'❌ rejected', deferred:'🔖 deferred'}[s.status] || App.esc(s.status || '—'));
      const catShort = catLabel[s.category] || s.category;

      const url = s.url || '';
      html += `<tr style="${bg}">
        <td style="text-align:center;font-size:14px">${inDb ? '✅' : '⬜'}</td>
        <td style="text-align:left">
          <div style="font-weight:600">${App.esc(s.name)}</div>
          ${s.why ? `<div style="font-size:11px;color:var(--text-dim);margin-top:2px;max-width:380px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${App.esc(s.why)}">${App.esc(s.why)}</div>` : ''}
        </td>
        <td><span class="tag tag-muted" style="font-size:11px">${App.esc(catShort)}</span></td>
        <td style="font-family:monospace;font-size:11px;color:var(--text-muted)">${App.esc(s.source_type || '—')}</td>
        <td>${statusLabel}</td>
        <td>${imgs.toLocaleString()}</td>
        <td style="color:${failColor}">${fails.toLocaleString()}</td>
        <td style="text-align:left">
          ${url ? `<a href="${App.esc(url)}" target="_blank" rel="noopener" style="color:var(--accent-bright);font-size:12px;word-break:break-all" title="${App.esc(url)}">${App.esc(url.length > 60 ? url.slice(0, 60) + '…' : url)}</a>` : '<span style="color:var(--text-dim)">—</span>'}
        </td>
      </tr>`;
    });
    html += `</tbody></table>
      <div style="margin-top:8px;font-size:11px;color:var(--text-dim)">显示 ${rows.length} / ${totalAll} 个源</div>`;
    return html;
  },

  resetFilter() {
    this._filter = { q: '', cat: 'all', status: 'all' };
    this.render(document.getElementById('tab-crawler'));
  },

  _bindFilter(container) {
    const search = container.querySelector('#crawler-search');
    const cat = container.querySelector('#crawler-cat');
    const status = container.querySelector('#crawler-status');

    const apply = () => {
      this._filter.q = search.value;
      this._filter.cat = cat.value;
      this._filter.status = status.value;
      const wrap = container.querySelector('#crawler-table-wrap');
      if (wrap) {
        const { sources, orphans } = this._data;
        const rows = this._buildRows();
        wrap.innerHTML = this._renderRows(rows, sources.length + orphans.length);
      }
    };

    search.addEventListener('input', apply);
    cat.addEventListener('change', apply);
    status.addEventListener('change', apply);
  },
};
