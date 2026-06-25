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
    this._packs = data.packs || [];
    if (!this._packs.length) {
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
            <img src="${img.image_url || img.local_path || img.url}" alt="图${i+1}"
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
          <button class="btn btn-accent btn-auto-publish" data-id="${pack.id}">�� 一键发布</button>
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
    const pack = this._packs.find(p => p.id === packId);
    if (!pack || !pack.images[imgIdx]) return;
    const img = pack.images[imgIdx];
    const src = img.image_url || img.local_path || img.url;

    const overlay = document.getElementById('image-modal-overlay');
    overlay.innerHTML = `
      <div class="image-modal" onclick="event.stopPropagation()">
        <div class="image-modal-header">
          <h3>图片详情 · 方案 ${pack.theme}</h3>
          <button class="image-modal-close" onclick="DailyTab.closeImageDetail()">&times;</button>
        </div>
        <div class="image-modal-body">
          <div class="image-modal-view">
            <img src="${this.esc(src)}" alt="图片 ${imgIdx+1}"
                 onerror="this.parentElement.innerHTML='<div style=color:var(--text-dim)>图片加载失败</div>'">
          </div>
          <div class="image-modal-info">
            <div>
              <div style="font-size:12px;color:var(--text-dim);margin-bottom:4px">文件</div>
              <div class="image-modal-filename">${this.esc(src.split('/').pop())}</div>
            </div>
            ${img.page_url ? `
            <div>
              <div style="font-size:12px;color:var(--text-dim);margin-bottom:4px">来源</div>
              ${img.source_name ? `<div style="font-weight:600;margin-bottom:2px">${this.esc(img.source_name)}</div>` : ''}
              <a href="${this.esc(img.page_url)}" target="_blank" style="color:var(--accent-bright);font-size:12px;word-break:break-all">${this.esc(img.page_url)}</a>
            </div>` : ''}
            ${img.keywords && img.keywords.length ? `
            <div>
              <div style="font-size:12px;color:var(--text-dim);margin-bottom:4px">关键词</div>
              <div class="image-modal-keywords">
                ${img.keywords.map(k => `<span class="tag tag-muted">${this.esc(k)}</span>`).join('')}
              </div>
            </div>` : ''}
            <div class="image-modal-actions">
              <button class="btn btn-like" onclick="DailyTab.feedbackImage('${img.image_id}', 'like')">喜欢</button>
              <button class="btn btn-dislike" onclick="DailyTab.feedbackImage('${img.image_id}', 'dislike')">不对味</button>
              <button class="btn btn-ghost" onclick="DailyTab.replaceImage('${img.image_id}')">换一张</button>
            </div>
          </div>
        </div>
      </div>`;
    overlay.style.display = 'flex';
    overlay.onclick = () => this.closeImageDetail();
    document.body.style.overflow = 'hidden';
  },

  closeImageDetail() {
    const overlay = document.getElementById('image-modal-overlay');
    overlay.style.display = 'none';
    overlay.innerHTML = '';
    document.body.style.overflow = '';
  },

  async feedbackImage(imageId, label) {
    try {
      await API.post(`/api/v1/daily/images/${imageId}/feedback`, {label});
      App.toast('反馈已记录');
      this.closeImageDetail();
    } catch(e) { App.toast('操作失败', 'error'); }
  },

  async replaceImage(imageId) {
    const newId = prompt('输入替换图片的 ID：');
    if (!newId) return;
    try {
      await API.post(`/api/v1/daily/images/${imageId}/replace`, {new_image_id: newId});
      App.toast('已替换');
      this.closeImageDetail();
    } catch(e) { App.toast('操作失败', 'error'); }
  },

  bindActions(container) {
    container.querySelectorAll('.btn-select').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const id = btn.dataset.id;
        try {
          await API.post(`/api/v1/daily/${id}/select`);
          App.toast('已选择该方案');

          // Export moodboard composite
          const exportResult = await API.post(`/api/v1/daily/${id}/export`);
          this.showPublishModal(id, exportResult);
        } catch(e) { App.toast(`操作失败: ${e.message}`, 'error'); }
      });
    });
    container.querySelectorAll('.btn-auto-publish').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const id = btn.dataset.id;
        btn.textContent = '... 发布中';
        btn.disabled = true;
        try {
          await API.post(`/api/v1/daily/${id}/select`);
          const result = await API.post(`/api/v1/daily/${id}/auto-publish`);
          if (result.success) {
            App.toast(`发布成功! ${result.post_url}`, 'success');
          } else {
            App.toast(result.error, 'error');
          }
        } catch(e) { App.toast(`发布失败: ${e.message}`, 'error'); }
        btn.textContent = '一键发布';
        btn.disabled = false;
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

  showPublishModal(packId, exportData) {
    const overlay = document.getElementById('image-modal-overlay');
    const caption = exportData.caption || '';
    overlay.innerHTML = `
      <div class="image-modal" onclick="event.stopPropagation()">
        <div class="image-modal-header">
          <h3>出品预览 · ${this.esc(exportData.theme)}</h3>
          <button class="image-modal-close" onclick="DailyTab.closePublishModal()">&times;</button>
        </div>
        <div class="image-modal-body">
          <div class="image-modal-view" style="min-height:auto;background:transparent">
            <img src="${this.esc(exportData.url)}" alt="出品预览" style="max-height:50vh" onerror="this.parentElement.innerHTML='<div style=color:var(--text-dim)>预览加载失败</div>'">
          </div>
          <div class="image-modal-info">
            <a href="${this.esc(exportData.url)}" download class="btn btn-primary" style="text-decoration:none;text-align:center;">下载出品图</a>
            <div>
              <div style="font-size:12px;color:var(--text-dim);margin-bottom:4px">文案草稿（可编辑）</div>
              <textarea class="input" id="publish-caption-${packId}" style="min-height:100px">${this.esc(caption)}</textarea>
            </div>
            <div style="font-size:12px;color:var(--text-dim)">发布链接（手动发完贴后填写）</div>
            <input type="text" id="publish-url-${packId}" placeholder="https://www.xiaohongshu.com/..." style="width:100%;padding:8px;background:var(--bg);border:1px solid var(--border);border-radius:5px;color:var(--text);font-size:13px">
            <button class="btn btn-success" id="confirm-publish-btn-${packId}" style="width:100%">确认已发布</button>
            <button class="btn btn-ghost" onclick="DailyTab.closePublishModal()" style="width:100%">取消</button>
          </div>
        </div>
      </div>`;
    overlay.style.display = 'flex';
    overlay.onclick = () => this.closePublishModal();
    document.body.style.overflow = 'hidden';

    document.getElementById(`confirm-publish-btn-${packId}`).addEventListener('click', async () => {
      const url = document.getElementById(`publish-url-${packId}`).value;
      try {
        await API.post(`/api/v1/daily/${packId}/publish`, {platform: 'xiaohongshu', post_url: url});
        App.toast('已标记发布');
        this.closePublishModal();
      } catch(e) { App.toast('操作失败', 'error'); }
    });
  },

  closePublishModal() {
    const overlay = document.getElementById('image-modal-overlay');
    overlay.style.display = 'none';
    overlay.innerHTML = '';
    document.body.style.overflow = '';
  },

  esc(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }
};
