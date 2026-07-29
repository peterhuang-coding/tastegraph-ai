// Tab 11: 🔥 潮流 — Trend Briefing
// 4 KPI + 3 列布局：左（虚拟列表） / 中（本周趋势） / 右（历史报告）
// 底部：已决策列表 (采用/搁置/弃)
const TrendTab = {
  async load() {
    const container = document.getElementById('tab-trend');
    App.renderLoading(container);
    try {
      const [virt, snap, history, dec] = await Promise.all([
        API.get('/api/v1/trend/virtual-lists'),
        API.get('/api/v1/trend/snapshot?days=14'),
        API.get('/api/v1/trend/history'),
        API.get('/api/v1/trend/decisions'),
      ]);
      this.render(container, { virt, snap, history, dec });
    } catch (e) {
      container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">⚠️</div><p>加载失败: ${App.esc(e.message)}</p><p style="font-size:12px;color:var(--text-dim)">确认 router.py 已 include trend.router</p></div>`;
    }
  },

  render(container, { virt, snap, history, dec }) {
    const lists = virt.lists || [];
    const rising = snap.rising || [];
    const fading = snap.fading || [];
    const reports = history.reports || [];
    const adopted = dec.adopted || [];
    const held = dec.held || [];
    const rejected = dec.rejected || [];
    const totalDec = adopted.length + held.length + rejected.length;

    let html = '';

    // ── Header strip ──
    html += `<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
      <h3 style="margin:0;font-size:16px">🔥 潮流趋势简报</h3>
      <span style="font-size:12px;color:var(--text-muted)">分析周期 ${snap.days || 14} 天 · 共 ${snap.image_count || 0} 张图 / ${snap.unique_keywords || 0} 个独立关键词</span>
    </div>`;

    // ── 4 KPI cards ──
    html += `<div class="analysis-panel" style="margin-top:0">
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-value">${this.fmtNum(snap.total_keywords || 0)}</div>
          <div class="stat-label">本周关键词总数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" style="color:#7fc97f">${rising.length}</div>
          <div class="stat-label">上升中（候选）</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" style="color:#c97f7f">${fading.length}</div>
          <div class="stat-label">消退中</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" style="color:var(--accent-bright)">${totalDec}</div>
          <div class="stat-label">已决策（${adopted.length} 采用 / ${held.length} 搁置 / ${rejected.length} 弃）</div>
        </div>
      </div>
      ${snap.error ? `<p style="margin-top:12px;font-size:12px;color:#c97f7f">⚠️ ${App.esc(snap.error)}</p>` : ''}
    </div>`;

    // ── 3-column grid ──
    html += `<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-top:16px">`;

    // ---------- Column 1: 虚拟列表 ----------
    html += `<div class="analysis-panel" style="margin-top:0">
      <h4 style="margin:0 0 12px;font-size:14px">📚 虚拟列表源（${lists.reduce((a, l) => a + l.count, 0)} 条）</h4>
      <div style="display:flex;flex-direction:column;gap:6px;max-height:600px;overflow-y:auto">`;
    for (const list of lists) {
      const isArticles = list.category === 'articles';
      html += `<div style="border:1px solid var(--border);border-radius:6px;background:var(--bg);overflow:hidden">
        <div onclick="TrendTab.toggleList('${App.esc(list.category)}')" style="padding:8px 12px;cursor:pointer;display:flex;justify-content:space-between;align-items:center">
          <div>
            <span style="font-weight:600;font-size:13px">${isArticles ? '📰 ' : ''}${App.esc(list.category)}</span>
            ${list.sample_names?.length ? `<span style="font-size:11px;color:var(--text-muted);margin-left:6px">${App.esc(list.sample_names.slice(0, 2).join(' · '))}</span>` : ''}
          </div>
          <span class="tag tag-muted">${list.count}</span>
        </div>
        <div id="trend-list-${App.esc(list.category)}" style="display:none;border-top:1px solid var(--border);padding:6px 12px;background:var(--card)">
          ${list.items.map(it => `
            <div style="padding:4px 0;font-size:12px;border-bottom:1px solid var(--border)">
              <a href="${App.esc(it.url)}" target="_blank" rel="noopener" style="color:var(--accent-bright);text-decoration:none;font-weight:500">${App.esc(it.name)}</a>
              ${it.why ? `<div style="color:var(--text-dim);font-size:11px;margin-top:2px;line-height:1.4">${App.esc(it.why.slice(0, 120))}${it.why.length > 120 ? '…' : ''}</div>` : ''}
            </div>
          `).join('')}
        </div>
      </div>`;
    }
    html += `</div></div>`;

    // ---------- Column 2: 本周趋势 ----------
    html += `<div>
      <div class="analysis-panel" style="margin-top:0">
        <h4 style="margin:0 0 12px;font-size:14px;color:#7fc97f">📈 上升中 · Top ${rising.length}</h4>
        ${rising.length ? rising.map((r, i) => this.renderKeywordCard(r, i, 'rising')).join('') :
          '<div class="empty-state" style="padding:24px"><p style="font-size:12px;color:var(--text-dim)">暂无上升数据</p></div>'}
      </div>

      <div class="analysis-panel" style="margin-top:12px">
        <h4 style="margin:0 0 12px;font-size:14px;color:#c97f7f">📉 消退中 · Top ${fading.length}</h4>
        ${fading.length ? fading.map((f, i) => this.renderKeywordCard(f, i, 'fading')).join('') :
          '<div class="empty-state" style="padding:24px"><p style="font-size:12px;color:var(--text-dim)">暂无消退数据</p></div>'}
      </div>
    </div>`;

    // ---------- Column 3: 历史报告 ----------
    html += `<div class="analysis-panel" style="margin-top:0">
      <h4 style="margin:0 0 12px;font-size:14px">📜 历史报告（${reports.length} 份）</h4>
      ${reports.length ? `<div style="display:flex;flex-direction:column;gap:6px;max-height:600px;overflow-y:auto">` +
        reports.map((r, i) => `
          <div style="border:1px solid var(--border);border-radius:6px;background:var(--bg);overflow:hidden">
            <div onclick="TrendTab.toggleReport(${i})" style="padding:8px 12px;cursor:pointer;display:flex;justify-content:space-between;align-items:center">
              <div>
                <span style="font-weight:600;font-size:13px">${App.esc(r.date || r.filename)}</span>
                <span style="font-size:11px;color:var(--text-muted);margin-left:6px">${App.esc(r.filename)}</span>
              </div>
              <span style="font-size:11px;color:var(--text-dim)">${this.fmtSize(r.size)}</span>
            </div>
            <div id="trend-report-${i}" style="display:none;border-top:1px solid var(--border);padding:10px 12px;background:var(--card)">
              <pre style="margin:0;font-family:var(--font-mono);font-size:11px;line-height:1.5;white-space:pre-wrap;color:var(--text-muted);max-height:300px;overflow-y:auto">${App.esc(r.preview)}</pre>
            </div>
          </div>
        `).join('') + `</div>` :
        '<div class="empty-state" style="padding:24px"><p style="font-size:12px;color:var(--text-dim)">暂无历史报告</p></div>'}
    </div>`;

    html += `</div>`;  // close 3-col grid

    // ── Bottom: 已决策列表 ──
    html += `<h3 style="margin:24px 0 12px;font-size:16px">📋 信息员决策记录</h3>`;
    html += `<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px">`;

    const renderDecCol = (title, items, color, emoji) => `
      <div class="analysis-panel" style="margin-top:0">
        <h4 style="margin:0 0 12px;font-size:14px;color:${color}">${emoji} ${title} (${items.length})</h4>
        ${items.length ? `<div style="display:flex;flex-direction:column;gap:6px;max-height:300px;overflow-y:auto">` +
          items.slice().reverse().map(d => `
            <div style="padding:8px 10px;border:1px solid var(--border);border-radius:4px;background:var(--bg);font-size:12px">
              <div style="font-weight:600">${App.esc(d.keyword)}</div>
              <div style="color:var(--text-dim);font-size:11px;margin-top:4px">${App.esc((d.decided_at || '').slice(0, 19).replace('T', ' '))}</div>
              ${d.context && Object.keys(d.context).length ? `<div style="color:var(--text-muted);font-size:11px;margin-top:2px">${App.esc(JSON.stringify(d.context).slice(0, 80))}</div>` : ''}
            </div>
          `).join('') + `</div>` :
          `<div style="padding:16px;text-align:center;color:var(--text-dim);font-size:12px">暂无</div>`}
      </div>`;

    html += renderDecCol('采用 (Adopt)', adopted, '#7fc97f', '🟢');
    html += renderDecCol('搁置 (Hold)', held, '#d4a85f', '🟡');
    html += renderDecCol('弃 (Reject)', rejected, '#c97f7f', '🔴');
    html += `</div>`;

    container.innerHTML = html;
  },

  renderKeywordCard(item, index, kind) {
    const k = item.keyword;
    const c = item.count;
    const recent = item.recent || 0;
    const delta = item.delta || 0;
    const color = kind === 'rising' ? '#7fc97f' : '#c97f7f';
    const sign = delta > 0 ? '+' : '';
    return `
      <div style="padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);margin-bottom:6px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <span style="font-weight:600;font-size:13px" title="${App.esc(k)}">${App.esc(k.length > 28 ? k.slice(0, 28) + '…' : k)}</span>
          <span style="font-family:var(--font-mono);font-size:11px;color:${color}">${c}次 · ${sign}${delta}</span>
        </div>
        <div style="display:flex;gap:4px">
          <button class="btn btn-sm" style="background:#7fc97f22;color:#7fc97f;border:1px solid #7fc97f55;padding:3px 8px;font-size:11px;cursor:pointer;border-radius:3px" onclick="TrendTab.decide('${App.esc(k).replace(/'/g, "\\'")}', 'adopt')">🟢 采用</button>
          <button class="btn btn-sm" style="background:#d4a85f22;color:#d4a85f;border:1px solid #d4a85f55;padding:3px 8px;font-size:11px;cursor:pointer;border-radius:3px" onclick="TrendTab.decide('${App.esc(k).replace(/'/g, "\\'")}', 'hold')">🟡 搁置</button>
          <button class="btn btn-sm" style="background:#c97f7f22;color:#c97f7f;border:1px solid #c97f7f55;padding:3px 8px;font-size:11px;cursor:pointer;border-radius:3px" onclick="TrendTab.decide('${App.esc(k).replace(/'/g, "\\'")}', 'reject')">🔴 弃</button>
        </div>
      </div>`;
  },

  toggleList(cat) {
    const el = document.getElementById('trend-list-' + cat);
    if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
  },

  toggleReport(idx) {
    const el = document.getElementById('trend-report-' + idx);
    if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
  },

  async decide(keyword, decision) {
    try {
      await API.post('/api/v1/trend/decide', {
        keyword,
        decision,
        context: { source: 'trend_tab', at: new Date().toISOString() },
      });
      App.toast(`${decision === 'adopt' ? '🟢 已采用' : decision === 'hold' ? '🟡 已搁置' : '🔴 已弃'}：${keyword}`, 'success');
      // 重新加载以更新决策列表
      this.load();
    } catch (e) {
      App.toast(`决策失败: ${e.message}`, 'error');
    }
  },

  fmtNum(n) {
    n = Number(n) || 0;
    if (n >= 10000) return (n / 10000).toFixed(1) + 'w';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
    return String(n);
  },

  fmtSize(bytes) {
    if (!bytes) return '0B';
    if (bytes < 1024) return bytes + 'B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + 'KB';
    return (bytes / (1024 * 1024)).toFixed(1) + 'MB';
  },
};
