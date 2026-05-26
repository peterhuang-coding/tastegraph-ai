// Tab 1: Source Review
const SourcesTab = {
  async load() {
    const container = document.getElementById('tab-sources');
    App.renderLoading(container);
    try {
      const [pending, stats] = await Promise.all([
        API.get('/api/v1/sources/pending?status=pending'),
        API.get('/api/v1/sources/stats'),
      ]);
      this.render(container, pending, stats);
    } catch(e) {
      container.innerHTML = `<div class="empty-state"><p>加载失败: ${e.message}</p></div>`;
    }
  },

  render(container, pending, stats) {
    let html = '';

    // Stats bar
    html += `<div class="stats-grid">
      <div class="stat-card"><div class="stat-value" style="color:var(--yellow)">${stats.pending||0}</div><div class="stat-label">待审核</div></div>
      <div class="stat-card"><div class="stat-value" style="color:var(--green)">${stats.approved||0}</div><div class="stat-label">已通过</div></div>
      <div class="stat-card"><div class="stat-value" style="color:var(--red)">${stats.rejected||0}</div><div class="stat-label">已拒绝</div></div>
      <div class="stat-card"><div class="stat-value" style="color:var(--text-muted)">${stats.deferred||0}</div><div class="stat-label">待定</div></div>
    </div>`;

    if (pending.length === 0) {
      html += '<div class="empty-state"><div class="empty-state-icon">✨</div><p>没有待审核的源</p><p style="font-size:12px;color:var(--text-dim)">触发发现引擎后会出现在这里</p></div>';
    } else {
      html += pending.map(s => this.renderCard(s)).join('');
    }

    container.innerHTML = html;

    // Bind actions
    container.querySelectorAll('.btn-approve').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.id;
        try {
          await API.post(`/api/v1/sources/${id}/approve`);
          App.toast('已通过');
          App.refreshBadges();
          this.load();
        } catch(e) { App.toast('操作失败', 'error'); }
      });
    });
    container.querySelectorAll('.btn-reject').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.id;
        const reason = prompt('拒绝原因（可选）：');
        try {
          await API.post(`/api/v1/sources/${id}/reject`, {note: reason || ''});
          App.toast('已拒绝');
          App.refreshBadges();
          this.load();
        } catch(e) { App.toast('操作失败', 'error'); }
      });
    });
    container.querySelectorAll('.btn-defer').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.id;
        try {
          await API.post(`/api/v1/sources/${id}/defer`);
          App.toast('已待定');
          App.refreshBadges();
          this.load();
        } catch(e) { App.toast('操作失败', 'error'); }
      });
    });
  },

  renderCard(s) {
    const scorePct = Math.round(s.ai_score * 100);
    return `
    <div class="card" id="source-${s.id}">
      <div class="card-header">
        <div>
          <div class="card-title">🆕 ${this.escape(s.name)}</div>
          <div class="source-path">发现路径：← ${this.escape(s.discovered_from || '手动添加')}</div>
          <div style="margin-top:6px">
            <span class="tag tag-muted">${s.source_type}</span>
            <span class="tag tag-${scorePct >= 80 ? 'green' : scorePct >= 60 ? 'yellow' : 'red'}">品味匹配 ${scorePct}%</span>
            ${s.ai_risk ? `<span class="tag tag-red">⚠ ${this.escape(s.ai_risk)}</span>` : ''}
          </div>
        </div>
        <div style="font-size:12px;color:var(--text-dim)">${s.created_at?.slice(0,10)}</div>
      </div>
      ${s.ai_reason ? `<p style="font-size:13px;color:var(--text-muted);margin-bottom:8px">${this.escape(s.ai_reason)}</p>` : ''}
      <div class="score-bar"><div class="score-fill ${scoreClass(scorePct)}" style="width:${scorePct}%"></div></div>
      <div style="margin-top:12px;display:flex;gap:8px">
        <button class="btn btn-success btn-approve" data-id="${s.id}">✅ 通过并加入图谱</button>
        <button class="btn btn-danger btn-reject" data-id="${s.id}">❌ 拒绝</button>
        <button class="btn btn-ghost btn-defer" data-id="${s.id}">🔖 待定</button>
        <a href="${this.escape(s.url)}" target="_blank" class="btn btn-ghost" style="margin-left:auto">🔗 访问</a>
      </div>
    </div>`;
  },

  escape(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }
};
