// Tab 4: Publish History & Analytics
const HistoryTab = {
  async load() {
    const container = document.getElementById('tab-history');
    App.renderLoading(container);
    try {
      const [list, stats] = await Promise.all([
        API.get('/api/v1/history/list'),
        API.get('/api/v1/history/stats'),
      ]);
      this.render(container, list, stats);
    } catch(e) {
      container.innerHTML = `<div class="empty-state"><p>加载失败: ${e.message}</p></div>`;
    }
  },

  render(container, list, stats) {
    let html = '';

    // Analysis panel
    html += `<div class="analysis-panel">
      <h3 style="margin-bottom:16px;font-size:16px">📊 数据分析</h3>
      <div class="stats-grid" style="margin-bottom:0">
        <div class="stat-card"><div class="stat-value">${stats.total_published}</div><div class="stat-label">总发布数</div></div>
        <div class="stat-card"><div class="stat-value">${(stats.avg_engagement * 100).toFixed(1)}%</div><div class="stat-label">平均互动率</div></div>
        <div class="stat-card"><div class="stat-value" style="font-size:14px">${stats.top_themes?.[0]?.name || '暂无'}</div><div class="stat-label">最佳主题</div></div>
        <div class="stat-card"><div class="stat-value" style="font-size:14px;color:var(--text-muted)">${stats.recent_trend || '暂无'}</div><div class="stat-label">近期趋势</div></div>
      </div>
      ${stats.top_themes?.length ? `
      <div style="margin-top:16px">
        <span style="font-size:12px;color:var(--text-dim)">热门主题：</span>
        ${stats.top_themes.map(t => `<span class="tag tag-muted">${t.name} (${t.count})</span>`).join(' ')}
      </div>` : ''}
    </div>`;

    // History list
    html += `<h3 style="margin:24px 0 16px;font-size:16px">📋 发布记录</h3>`;

    if (list.length === 0) {
      html += '<div class="empty-state"><div class="empty-state-icon">📭</div><p>暂无发布记录</p></div>';
    } else {
      html += `<div style="overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;font-size:14px">
          <thead>
            <tr style="border-bottom:1px solid var(--border);text-align:left;color:var(--text-muted);font-size:12px">
              <th style="padding:10px">日期</th>
              <th>主题</th>
              <th>平台</th>
              <th>互动数</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            ${list.map(item => `
            <tr style="border-bottom:1px solid var(--border)">
              <td style="padding:10px">${(item.published_at || '').slice(0,10)}</td>
              <td>${this.esc(item.theme || '未命名')}</td>
              <td><span class="tag tag-muted">${this.esc(item.platform)}</span></td>
              <td>❤️ ${item.likes || 0} · 💾 ${item.saves || 0} · 💬 ${item.comments || 0}</td>
              <td>${item.post_url ? `<a href="${this.esc(item.post_url)}" target="_blank" class="btn btn-ghost btn-sm">查看</a>` : '-'}</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
    }

    container.innerHTML = html;
  },

  esc(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }
};
