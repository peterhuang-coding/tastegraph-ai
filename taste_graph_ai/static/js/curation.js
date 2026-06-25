// TasteGraph AI - Manual Curation Tab (手动选图)
const CurationTab = {
  _selected: new Set(),
  _images: [],
  _total: 0,
  _page: 1,

  async load() {
    this._selected.clear();
    this._page = 1;
    const container = document.getElementById('tab-curation');
    App.renderLoading(container);
    try {
      const data = await API.get('/api/v1/images/pending?page=1&limit=50');
      this._images = data.images || [];
      this._total = data.total || 0;
      this.render(container, data);
      this.loadFailures();
    } catch(e) {
      container.innerHTML = `<div class="empty-state"><p>加载失败: ${e.message}</p></div>`;
    }
  },

  render(container, data) {
    let html = this.renderHeader(data);
    html += this.renderGrid(data.images);
    html += this.renderPagination(data);
    html += this.renderForm();
    container.innerHTML = html;
    this.bindActions(container);
  },

  renderHeader(data) {
    return `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
        <div>
          <h2 style="font-size:18px;font-weight:600">手动选图</h2>
          <p style="font-size:12px;color:var(--text-muted);margin-top:4px">
            共 ${data.total} 张待选图片，选择 9 张创建你的策展包
          </p>
        </div>
        <span id="curation-count" class="tag tag-muted" style="font-size:14px;padding:6px 14px">
          已选 0/9
        </span>
      </div>`;
  },

  renderGrid(images) {
    if (!images || !images.length) {
      return '<div class="empty-state"><p>暂无待选图片。请先运行 Pipeline 抓取图片。</p></div>';
    }
    return `
    <div class="curation-grid">
      ${images.map(img => {
        const isSelected = this._selected.has(img.image_id);
        const src = img.image_url || img.url;
        return `
        <div class="curation-item ${isSelected ? 'selected' : ''}"
             data-id="${img.image_id}"
             onclick="CurationTab.toggleImage('${img.image_id}')">
          <img src="${this.esc(src)}" alt="图片" loading="lazy"
               onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
          <div class="curation-img-fallback" style="display:none">图片加载失败</div>
          <div class="curation-check">${isSelected ? '✓' : ''}</div>
          <div class="curation-overlay">
            <span>${img.source_name ? this.esc(img.source_name) : Math.round(img.final_score * 100) + '分'}</span>
          </div>
        </div>`;
      }).join('')}
    </div>`;
  },

  renderPagination(data) {
    const totalPages = Math.ceil(data.total / data.limit);
    if (totalPages <= 1) return '';
    return `
    <div class="curation-pagination">
      <button class="btn btn-ghost btn-sm" onclick="CurationTab.goPage(${this._page - 1})"
              ${this._page <= 1 ? 'disabled' : ''}>← 上一页</button>
      <span style="font-size:12px;color:var(--text-muted)">第 ${this._page}/${totalPages} 页</span>
      <button class="btn btn-ghost btn-sm" onclick="CurationTab.goPage(${this._page + 1})"
              ${this._page >= totalPages ? 'disabled' : ''}>下一页 →</button>
    </div>`;
  },

  renderForm() {
    const remaining = 9 - this._selected.size;
    const canSubmit = this._selected.size === 9;
    return `
    <div class="curation-form">
      <h3 style="font-size:16px;font-weight:600;margin-bottom:16px">创建策展包</h3>
      <div style="margin-bottom:12px">
        <label style="font-size:12px;color:var(--text-dim)">主题 *</label>
        <input type="text" id="curation-theme" class="input"
               placeholder="例如：东京阴天角落、柏林周末早餐" maxlength="50">
      </div>
      <div style="margin-bottom:12px">
        <label style="font-size:12px;color:var(--text-dim)">标题</label>
        <input type="text" id="curation-title" class="input"
               placeholder="小红书标题（可选）" maxlength="100">
      </div>
      <div style="margin-bottom:12px">
        <label style="font-size:12px;color:var(--text-dim)">文案</label>
        <textarea id="curation-caption" class="input"
                  placeholder="写一段文案描述你的选择..." style="min-height:100px"></textarea>
      </div>
      <button id="curation-submit-btn" class="btn btn-primary"
              style="width:100%" disabled>还需选择 ${remaining} 张图片</button>
    </div>`;
  },

  toggleImage(imageId) {
    if (this._selected.has(imageId)) {
      this._selected.delete(imageId);
    } else if (this._selected.size >= 9) {
      App.toast('最多选择 9 张图片', 'error');
      return;
    } else {
      this._selected.add(imageId);
    }
    this.updateUI();
  },

  updateUI() {
    // Update grid items
    document.querySelectorAll('.curation-item').forEach(el => {
      const id = el.dataset.id;
      const isSelected = this._selected.has(id);
      el.classList.toggle('selected', isSelected);
      el.querySelector('.curation-check').textContent = isSelected ? '✓' : '';
    });
    // Update count badge
    const badge = document.getElementById('curation-count');
    if (badge) {
      badge.textContent = `已选 ${this._selected.size}/9`;
      badge.className = this._selected.size === 9 ? 'tag tag-green' : 'tag tag-muted';
      badge.style.cssText = 'font-size:14px;padding:6px 14px';
    }
    // Update submit button
    const btn = document.getElementById('curation-submit-btn');
    const theme = document.getElementById('curation-theme')?.value?.trim();
    if (btn) {
      const remaining = 9 - this._selected.size;
      const canSubmit = this._selected.size === 9 && theme;
      btn.disabled = !canSubmit;
      if (!canSubmit) {
        btn.textContent = remaining > 0 ? `还需选择 ${remaining} 张图片` : '请填写主题';
      } else {
        btn.textContent = '创建策展包';
      }
    }
  },

  async goPage(page) {
    if (page < 1) return;
    this._page = page;
    this._selected.clear();
    const container = document.getElementById('tab-curation');
    App.renderLoading(container);
    try {
      const data = await API.get(`/api/v1/images/pending?page=${page}&limit=50`);
      this._images = data.images || [];
      this._total = data.total || 0;
      this.render(container, data);
    } catch(e) {
      container.innerHTML = `<div class="empty-state"><p>加载失败: ${e.message}</p></div>`;
    }
  },

  bindActions(container) {
    const themeInput = document.getElementById('curation-theme');
    if (themeInput) {
      themeInput.addEventListener('input', () => this.updateUI());
    }

    const submitBtn = document.getElementById('curation-submit-btn');
    if (submitBtn) {
      submitBtn.addEventListener('click', async () => {
        const theme = themeInput?.value?.trim();
        const title = document.getElementById('curation-title')?.value?.trim() || '';
        const caption = document.getElementById('curation-caption')?.value?.trim() || '';
        const imageIds = Array.from(this._selected);

        if (imageIds.length !== 9 || !theme) return;
        submitBtn.textContent = '创建中...';
        submitBtn.disabled = true;

        try {
          const pack = await API.post('/api/v1/packs/curated', {
            image_ids: imageIds, theme, title, caption,
          });
          App.toast('策展包创建成功！', 'success');
          this.showPreview(pack);
        } catch(e) {
          App.toast(`创建失败: ${e.message}`, 'error');
          submitBtn.textContent = '创建策展包';
          submitBtn.disabled = false;
        }
      });
    }
  },

  showPreview(pack) {
    const overlay = document.getElementById('image-modal-overlay');
    overlay.innerHTML = `
      <div class="image-modal" onclick="event.stopPropagation()" style="max-width:720px">
        <div class="image-modal-header">
          <h3>策展包 · ${this.esc(pack.theme)}</h3>
          <button class="image-modal-close" onclick="CurationTab.closePreview()">×</button>
        </div>
        <div class="image-modal-body" style="flex-direction:column">
          <div style="margin-bottom:12px;font-size:12px;color:var(--text-muted)">
            品味得分: <span class="tag tag-green">${Math.round(pack.taste_score)}</span>
            | 状态: ${pack.status === 'selected' ? '已就绪，可以发布' : pack.status}
          </div>
          <div class="image-grid">
            ${pack.images.map(img => `
              <div style="position:relative">
                <img src="${img.image_url}" alt="" style="width:100%;aspect-ratio:1;object-fit:cover;border-radius:4px"
                     onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
                <div style="display:none;width:100%;aspect-ratio:1;background:var(--bg-hover);align-items:center;justify-content:center;font-size:12px;color:var(--text-dim);border-radius:4px">图片</div>
              </div>
            `).join('')}
          </div>
          ${pack.caption ? `<textarea class="input" readonly style="margin-top:12px;min-height:80px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:var(--radius);padding:12px;font-family:var(--font);font-size:14px;width:100%;resize:vertical">${this.esc(pack.caption)}</textarea>` : ''}
          <div style="display:flex;gap:8px;margin-top:16px">
            <button class="btn btn-accent" style="flex:1" id="auto-publish-btn-${pack.id}" onclick="CurationTab.autoPublish('${pack.id}')">一键发布小红书</button>
            <button class="btn btn-success" style="flex:1" onclick="CurationTab.publishCurated('${pack.id}')">导出并发布</button>
            <button class="btn btn-ghost" onclick="CurationTab.closePreview(); CurationTab.load()">返回选图</button>
          </div>
        </div>
      </div>`;
    overlay.style.display = 'flex';
    overlay.onclick = () => this.closePreview();
    document.body.style.overflow = 'hidden';
  },

  closePreview() {
    const overlay = document.getElementById('image-modal-overlay');
    overlay.style.display = 'none';
    document.body.style.overflow = '';
  },

  async publishCurated(packId) {
    try {
      const exportResult = await API.post(`/api/v1/daily/${packId}/export`);
      this.closePreview();
      DailyTab.showPublishModal(packId, exportResult);
    } catch(e) {
      App.toast(`导出失败: ${e.message}`, 'error');
    }
  },

  async autoPublish(packId) {
    const btn = document.getElementById(`auto-publish-btn-${packId}`);
    if (btn) { btn.textContent = '... 发布中'; btn.disabled = true; }
    try {
      const result = await API.post(`/api/v1/daily/${packId}/auto-publish`);
      if (result.success) {
        App.toast(`发布成功！${result.post_url}`, 'success');
        this.closePreview();
      } else {
        App.toast(result.error || '发布失败', 'error');
      }
    } catch(e) {
      App.toast(`发布失败: ${e.message}`, 'error');
    }
    if (btn) { btn.textContent = '一键发布小红书'; btn.disabled = false; }
  },

  esc(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  },

  async loadFailures() {
    try {
      const data = await API.get('/api/v1/scrape-failures');
      this.renderFailures(data);
    } catch(e) { /* ignore */ }
  },

  renderFailures(data) {
    const container = document.getElementById('tab-curation');
    let panel = document.getElementById('failures-panel');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'failures-panel';
      container.appendChild(panel);
    }
    if (!data || !data.total) {
      panel.innerHTML = '';
      return;
    }
    const reasons = {
      'page_fetch_failed': '页面抓取失败',
      'image_download_failed': '图片下载失败',
      'image_too_small': '图片尺寸太小',
      'bad_url_skipped': '低质量链接已跳过',
      'not_image_url': '非图片链接',
    };
    let html = '<div class="curation-form" style="margin-top:32px"><h3 style="font-size:16px;font-weight:600;margin-bottom:12px">抓取失败记录 <span style="font-size:12px;color:var(--text-muted);font-weight:400">(共' + data.total + '条)</span></h3>';
    if (data.by_reason && data.by_reason.length) {
      html += '<div style="font-size:12px;margin-bottom:16px;display:flex;flex-wrap:wrap;gap:8px">';
      for (const r of data.by_reason) {
        html += '<span class="tag tag-muted">' + (reasons[r.reason] || r.reason) + ': ' + r.cnt + '</span>';
      }
      html += '</div>';
    }
    if (data.by_source && data.by_source.length) {
      html += '<div style="font-size:12px;margin-bottom:12px">';
      html += '<div style="color:var(--text-dim);margin-bottom:6px">按来源分类:</div>';
      for (const s of data.by_source.slice(0, 10)) {
        html += '<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border)"><span>' + this.esc(s.source_name || '未知') + '</span><span style="color:var(--text-muted)">' + (reasons[s.reason] || s.reason) + ' ×' + s.cnt + '</span></div>';
      }
      html += '</div>';
    }
    html += '</div>';
    panel.innerHTML = html;
  }
};
