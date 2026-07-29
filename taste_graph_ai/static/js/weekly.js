// Tab 10: Weekly Feedback Report — 反馈周报
// 4 KPI cards + 2 CSS-only bar charts + Top 10 posts table.
const WeeklyTab = {
  async load() {
    const container = document.getElementById('tab-weekly');
    App.renderLoading(container);
    try {
      const [summary, trend, topPosts, report] = await Promise.all([
        API.get('/api/v1/feedback/weekly-summary'),
        API.get('/api/v1/feedback/weekly-trend?weeks=8'),
        API.get('/api/v1/feedback/top-posts?limit=10'),
        API.get('/api/v1/feedback/weekly-report'),
      ]);
      this.render(container, { summary, trend, topPosts, report });
    } catch (e) {
      container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">⚠️</div><p>加载失败: ${App.esc(e.message)}</p></div>`;
    }
  },

  render(container, { summary, trend, topPosts, report }) {
    let html = '';

    // ── Header strip ──
    html += `<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
      <h3 style="margin:0;font-size:16px">📊 本周反馈周报</h3>
      <span style="font-size:12px;color:var(--text-muted)">${App.esc(summary.week_start?.slice(0,10) || '')} → ${App.esc((summary.week_end || '').slice(0,10) || 'now')}</span>
    </div>`;

    // ── 4 KPI cards ──
    html += `<div class="analysis-panel" style="margin-top:0">
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-value">${summary.publish_count}</div>
          <div class="stat-label">本周发布数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value" title="${summary.reach_is_estimate ? 'DB 未存 impressions，按 likes × 8 估算' : ''}">${this.fmtNum(summary.total_reach)}${summary.reach_is_estimate ? '*' : ''}</div>
          <div class="stat-label">总曝光${summary.reach_is_estimate ? '（估算）' : ''}</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${this.fmtNum(summary.total_interactions)}</div>
          <div class="stat-label">总互动（赞+评+藏）</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${summary.avg_engagement.toFixed(2)}</div>
          <div class="stat-label">平均互动率 (0-10)</div>
        </div>
      </div>
      ${summary.message ? `<p style="margin-top:12px;font-size:13px;color:var(--text-muted)">${App.esc(summary.message)}</p>` : ''}
    </div>`;

    // ── Suggestions strip ──
    if (report?.suggestions?.length) {
      html += `<div class="analysis-panel" style="margin-top:16px">
        <h4 style="margin:0 0 12px;font-size:14px">💡 周报建议</h4>
        <div style="display:flex;flex-direction:column;gap:6px;font-size:13px;color:var(--text)">
          ${report.suggestions.map(s => `<div style="padding:6px 10px;background:var(--bg);border-radius:4px;border-left:2px solid var(--accent)">${App.esc(s)}</div>`).join('')}
        </div>
      </div>`;
    }

    // ── 2 CSS bar charts ──
    const series = trend.series || [];
    html += `<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px">
      <div class="analysis-panel" style="margin-top:0">
        <h4 style="margin:0 0 12px;font-size:14px">📈 过去 ${trend.weeks} 周发布数</h4>
        ${this.renderBars(series.map(w => ({ label: w.week_label, value: w.publish_count })), '次')}
      </div>
      <div class="analysis-panel" style="margin-top:0">
        <h4 style="margin:0 0 12px;font-size:14px">📈 过去 ${trend.weeks} 周平均互动率</h4>
        ${this.renderBars(series.map(w => ({ label: w.week_label, value: w.avg_engagement })), '', { max: 10, decimals: 2 })}
      </div>
    </div>`;

    // ── Top 10 posts table ──
    html += `<h3 style="margin:24px 0 12px;font-size:16px">🏆 表现最好笔记 Top ${topPosts.limit}</h3>`;
    if (!topPosts.posts?.length) {
      html += `<div class="empty-state"><div class="empty-state-icon">📭</div><p>暂无记录 — 先录入发布互动数据</p></div>`;
    } else {
      html += `<div style="overflow-x:auto;border:1px solid var(--border);border-radius:var(--radius)">
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <thead>
            <tr style="border-bottom:1px solid var(--border);text-align:left;color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:0.5px">
              <th style="padding:10px 12px;width:32px">#</th>
              <th style="padding:10px 12px">主题</th>
              <th style="padding:10px 12px;width:90px">发布日</th>
              <th style="padding:10px 12px;text-align:right;width:60px">赞</th>
              <th style="padding:10px 12px;text-align:right;width:60px">藏</th>
              <th style="padding:10px 12px;text-align:right;width:60px">评</th>
              <th style="padding:10px 12px;text-align:right;width:80px">互动</th>
              <th style="padding:10px 12px;text-align:right;width:70px">评分</th>
              <th style="padding:10px 12px;width:60px">链接</th>
            </tr>
          </thead>
          <tbody>
            ${topPosts.posts.map((p, i) => `
            <tr style="border-bottom:1px solid var(--border)">
              <td style="padding:10px 12px;color:var(--text-dim);font-family:var(--font-mono)">${i + 1}</td>
              <td style="padding:10px 12px;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${App.esc(p.theme)}">${App.esc(p.theme)}</td>
              <td style="padding:10px 12px;color:var(--text-muted);font-size:12px">${App.esc((p.published_at || '').slice(0,10))}</td>
              <td style="padding:10px 12px;text-align:right;font-family:var(--font-mono)">${p.likes}</td>
              <td style="padding:10px 12px;text-align:right;font-family:var(--font-mono)">${p.saves}</td>
              <td style="padding:10px 12px;text-align:right;font-family:var(--font-mono)">${p.comments}</td>
              <td style="padding:10px 12px;text-align:right;font-family:var(--font-mono);color:var(--accent-bright)">${p.total_interactions}</td>
              <td style="padding:10px 12px;text-align:right;font-family:var(--font-mono);font-weight:600;color:${this.scoreColor(p.engagement_rate)}">${p.engagement_rate.toFixed(1)}</td>
              <td style="padding:10px 12px">${p.post_url ? `<a href="${App.esc(p.post_url)}" target="_blank" rel="noopener" style="color:var(--accent-bright);text-decoration:none;font-size:12px">查看 ↗</a>` : '<span style="color:var(--text-dim)">—</span>'}</td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
    }

    // ── Footer note ──
    if (summary.reach_is_estimate) {
      html += `<p style="margin-top:12px;font-size:11px;color:var(--text-dim)">* 总曝光按本周点赞数 × 8 估算（XHS 典型曝光/点赞比 ≈ 8）。精确曝光数据请从 XHS 创作者中心导入。</p>`;
    }

    container.innerHTML = html;
  },

  // ── Tiny CSS bar chart (flex + div) ──
  renderBars(items, unit = '', opts = {}) {
    if (!items.length) {
      return '<div class="empty-state" style="padding:24px"><p>数据收集中</p></div>';
    }
    const max = opts.max || Math.max(1, ...items.map(i => i.value));
    const decimals = opts.decimals ?? 0;
    return `<div style="display:flex;align-items:flex-end;gap:6px;height:140px;padding:8px 4px 0;border-bottom:1px solid var(--border)">
      ${items.map(item => {
        const pct = max > 0 ? (item.value / max) * 100 : 0;
        const h = Math.max(2, pct);  // minimum visible bar
        const color = this.barColor(item.value, max);
        return `<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;min-width:0">
          <div style="font-size:10px;color:var(--text-muted);font-family:var(--font-mono);height:14px;line-height:14px">${item.value > 0 ? item.value.toFixed(decimals) : ''}</div>
          <div style="width:100%;max-width:32px;height:${h}%;background:${color};border-radius:2px 2px 0 0;transition:height 0.3s;min-height:2px" title="${item.label}: ${item.value.toFixed(decimals)}${unit}"></div>
          <div style="font-size:10px;color:var(--text-dim);font-family:var(--font-mono)">${item.label}</div>
        </div>`;
      }).join('')}
    </div>`;
  },

  barColor(value, max) {
    if (value <= 0) return 'var(--border)';
    const ratio = value / max;
    if (ratio >= 0.7) return 'var(--accent-bright)';
    if (ratio >= 0.4) return 'var(--accent)';
    return '#4a6a82';
  },

  scoreColor(score) {
    if (score >= 7) return '#7fc97f';      // 爆款级 - green
    if (score >= 5) return 'var(--accent-bright)';  // 不错 - blue
    if (score >= 3) return 'var(--text-muted)';     // 一般 - gray
    if (score >= 1) return '#c97f7f';      // 偏低 - red
    return 'var(--text-dim)';              // 无互动 - dim
  },

  fmtNum(n) {
    n = Number(n) || 0;
    if (n >= 10000) return (n / 10000).toFixed(1) + 'w';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
    return String(n);
  },
};