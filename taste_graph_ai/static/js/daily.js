// Tab 2: Daily Review
const DailyTab = {
  async load() {
    const container = document.getElementById('tab-daily');
    App.renderLoading(container);
    try {
      const data = await API.get('/api/v1/daily/today');
      this.render(container, data);
    } catch(e) {
      container.innerHTML = `<div class="empty-state"><p>加载失败: ${e.message}</p></div>`;
    }
  },

  render(container, data) {
    if (!data.packs || data.packs.length === 0) {
      container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📦</div><p>今日暂无推荐方案</p><p style="font-size:12px;color:var(--text-dim)">触发推荐引擎后，每日 3 组方案会出现在这里</p></div>';
      return;
    }

    let html = `<p style="margin-bottom:16px;color:var(--text-muted)">AI 生成了 ${data.packs.length} 组方案，选择一个发布或全部拒绝：</p>`;
    data.packs.forEach((pack, i) => {
      const expanded = i === 0 ? 'open' : '';
      html += this.renderPack(pack, i, expanded);
    });
    container.innerHTML = html;
    this.bindActions(container);
  },

  renderPack(pack, index, expanded) {
    const scorePct = Math.round(pack.taste_score * 100);
    const isExpanded = expanded === 'open';
    return `
    <div class="card" id="pack-${pack.id}">
      <div class="card-header" style="cursor:pointer" onclick="DailyTab.togglePack('${pack.id}')">
        <div>
          <div class="card-title">方案 ${['A','B','C'][index] || index+1} · 品味得分 ${scorePct}</div>
          <div style="font-size:14px;color:var(--accent-bright);margin-top:4px">主题：${this.esc(pack.theme)}</div>
          <div style="font-size:12px;color:var(--text-muted)">${this.esc(pack.why_today)}</div>
        </div>
        <span class="tag tag-${scorePct >= 80 ? 'green' : scorePct >= 60 ? 'yellow' : 'red'}">${scorePct}</span>
      </div>

      <div class="pack-detail" id="pack-detail-${pack.id}" style="display:${isExpanded ? 'block' : 'none'}">
        ${pack.title_options.length ? `
        <div style="margin:8px 0">
          <span style="font-size:12px;color:var(--text-dim)">标题选项：</span>
          ${pack.title_options.map(t => `<span class="tag tag-muted" style="margin:2px">${this.esc(t)}</span>`).join('')}
        </div>` : ''}

        ${pack.images.length ? `
        <div class="image-grid">
          ${pack.images.map((img, i) => `
          <div style="position:relative" onclick="DailyTab.openImageDetail('${pack.id}', ${i})">
            <img src="${img.local_path || img.url}" alt="图${i+1}"
                 onerror="this.style.display='none';this.nextElementSibling.style.display='flex'"
                 loading="lazy">
            <div style="display:none;aspect-ratio:1;background:var(--bg);align-items:center;justify-content:center;color:var(--text-dim);font-size:12px">图${i+1}</div>
            <div style="position:absolute;bottom:4px;right:4px;font-size:10px;background:rgba(0,0,0,0.7);color:#fff;padding:2px 6px;border-radius:3px">${['', ...(img.keywords||[]).slice(0,2)].join(' ')}</div>
          </div>`).join('')}
        </div>` : ''}

        ${pack.caption ? `
        <div style="margin:12px 0">
          <div style="font-size:12px;color:var(--text-dim);margin-bottom:4px">文案草稿：</div>
          <textarea class="input" id="caption-${pack.id}">${this.esc(pack.caption)}</textarea>
        </div>` : ''}

        <div style="display:flex;gap:8px;margin-top:12px">
          <button class="btn btn-success btn-select" data-id="${pack.id}">✅ 选这组发布</button>
          <button class="btn btn-primary btn-edit" data-id="${pack.id}">📝 修改后发布</button>
          <button class="btn btn-danger btn-reject-pack" data-id="${pack.id}">❌ 拒绝</button>
        </div>
      </div>
    </div>`;
  },

  togglePack(packId) {
    const detail = document.getElementById(`pack-detail-${packId}`);
    if (detail) detail.style.display = detail.style.display === 'none' ? 'block' : 'none';
  },

  openImageDetail(packId, imgIdx) {
    // Placeholder for image detail modal
    App.toast('图片详情功能将在后续版本上线');
  },

  bindActions(container) {
    container.querySelectorAll('.btn-select').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const id = btn.dataset.id;
        try {
          await API.post(`/api/v1/daily/${id}/select`);
          App.toast('已选择该方案');

          // Ask to publish
          const url = prompt('发布后的小红书链接（可选，直接回车跳过）：');
          await API.post(`/api/v1/daily/${id}/publish`, {platform: 'xiaohongshu', post_url: url || ''});
          App.toast('已标记发布');
        } catch(e) { App.toast('操作失败', 'error'); }
      });
    });
    container.querySelectorAll('.btn-reject-pack').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const reason = prompt('拒绝原因（可选）：');
        try {
          await API.post(`/api/v1/daily/${btn.dataset.id}/reject`, {note: reason || ''});
          App.toast('已拒绝该方案');
        } catch(e) { App.toast('操作失败', 'error'); }
      });
    });
  },

  esc(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }
};
