// Tab 0: 今日动作 (Home Dashboard)
// Default landing page — what should the operator do today?
const HomeTab = {
  async load() {
    const container = document.getElementById('tab-home');
    App.renderLoading(container);
    try {
      const [srcStats, dailyData, weeklySum, feedbackCount, spotcheck] = await Promise.all([
        API.get('/api/v1/sources/stats').catch(() => ({pending:0, approved:0, rejected:0})),
        API.get('/api/v1/daily/today').catch(() => ({packs:[]})),
        API.get('/api/v1/feedback/weekly-summary').catch(() => ({publish_count:0, total_interactions:0, total_reach:0, week_start:'', week_end:''})),
        API.get('/api/v1/feedback/today-count').catch(() => ({count:0})),
        API.get('/api/v1/feedback/spotcheck?count=6').catch(() => ({total_unreviewed:0, images:[]})),
      ]);
      this.render(container, { srcStats, dailyData, weeklySum, feedbackCount, spotcheck });
    } catch(e) {
      container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">⚠️</div><p>加载失败: ${e.message}</p></div>`;
    }
  },

  render(container, { srcStats, dailyData, weeklySum, feedbackCount, spotcheck }) {
    const today = new Date().toISOString().slice(0,10);
    const greeting = this._greeting();
    const packCount = (dailyData.packs || []).length;
    const spotImages = (spotcheck.images || []);
    const unreviewed = spotcheck.total_unreviewed || 0;

    let html = `
    <div class="home-header" style="margin-bottom:24px;padding-bottom:16px;border-bottom:2px solid var(--border)">
      <h2 style="margin:0 0 4px;font-size:20px">${greeting}</h2>
      <div style="font-size:13px;color:var(--text-muted)">${today} · 2 件事你可以做（3 分钟搞定）</div>
    </div>

    ${unreviewed > 0 ? `
    <div class="home-section" style="margin-bottom:32px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <h3 style="margin:0;font-size:16px">📸 抽检 <span style="font-size:13px;color:var(--accent);font-weight:normal">${unreviewed} 张未审</span></h3>
        <button class="btn btn-sm btn-ghost" onclick="HomeTab._reload()">🔄 换一批</button>
      </div>
      <p style="font-size:13px;color:var(--text-muted);margin:0 0 16px">随机抽 ${spotImages.length} 张 · 每张点一下分类 · 反馈直接进图谱</p>
      <div id="home-spotcheck" style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px"></div>
    </div>
    ` : ''}

    <div class="home-grid" style="display:grid;grid-template-columns:repeat(2,1fr);gap:16px;margin-bottom:24px">
      ${this._cardSource(srcStats)}
      ${this._cardPacks(packCount)}
      ${this._cardFeedback(feedbackCount)}
      ${this._cardWeekly(weeklySum)}
    </div>

    ${packCount > 0 ? `
    <div class="home-section" style="margin-top:32px">
      <h3 style="margin:0 0 12px;font-size:16px">📦 今日推荐方案（已 AI 选过）</h3>
      <p style="font-size:13px;color:var(--text-muted);margin:0 0 12px">AI 选了 ${packCount} 组 · 这是精筛后的</p>
      <div id="home-packs"></div>
    </div>
    ` : ''}
    `;

    container.innerHTML = html;

    if (spotImages.length > 0) {
      this._renderSpotcheck(spotImages);
    }

    if (packCount > 0) {
      DailyTab._packs = dailyData.packs || [];
      const packsEl = document.getElementById('home-packs');
      DailyTab.render(packsEl, dailyData);
    }
  },

  _renderSpotcheck(images) {
    const el = document.getElementById('home-spotcheck');
    if (!el) return;
    el.innerHTML = images.map(img => `
      <div class="spot-card" data-id="${img.image_id}" style="background:var(--card-bg);border:1px solid var(--border);border-radius:8px;overflow:hidden;box-shadow:var(--card-shadow)">
        <a href="${App.esc(img.page_url || img.url)}" target="_blank" rel="noopener" style="display:block;aspect-ratio:1;background:var(--bg)">
          <img src="/images/${img.local_path.split('/').pop()}" alt="" loading="lazy"
               style="width:100%;height:100%;object-fit:cover;display:block"
               onerror="this.parentElement.innerHTML='<div style=padding:24px;text-align:center;color:var(--text-dim);font-size:12px>图加载失败</div>'">
        </a>
        <div style="padding:8px 10px;font-size:11px;color:var(--text-muted);border-bottom:1px solid var(--border)">
          ${App.esc(img.source_name || '未知源')}${img.keywords.length ? ' · ' + App.esc(img.keywords.slice(0,2).join(' ')) : ''}
        </div>
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--border)">
          <button class="spot-btn" data-label="对味" style="background:var(--card-bg);border:0;padding:6px 4px;cursor:pointer;font-size:12px;color:var(--green)">✓ 对味</button>
          <button class="spot-btn" data-label="精"  style="background:var(--card-bg);border:0;padding:6px 4px;cursor:pointer;font-size:12px;color:var(--accent-bright);font-weight:600">⭐ 精</button>
          <button class="spot-btn" data-label="弃"  style="background:var(--card-bg);border:0;padding:6px 4px;cursor:pointer;font-size:12px;color:var(--text-muted)">⏭ 弃</button>
        </div>
      </div>
    `).join('');
    el.querySelectorAll('.spot-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const card = btn.closest('.spot-card');
        const id = card.dataset.id;
        const label = btn.dataset.label;
        btn.parentElement.querySelectorAll('.spot-btn').forEach(b => b.style.opacity = '0.3');
        btn.style.opacity = '1';
        btn.disabled = true;
        try {
          const res = await fetch('/api/v1/feedback/curate-image', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image_id: id, label }),
          });
          if (res.ok) {
            card.style.transition = 'all 0.4s';
            card.style.opacity = '0.3';
            card.style.transform = 'scale(0.95)';
          }
        } catch(e) {}
      });
    });
  },

  _reload() {
    const container = document.getElementById('tab-home');
    this.load();
  },

  _greeting() {
    const h = new Date().getHours();
    if (h < 6)  return '🌙 夜深了';
    if (h < 11) return '☀️ 早上好';
    if (h < 14) return '🍚 中午好';
    if (h < 18) return '☕ 下午好';
    if (h < 22) return '🌆 晚上好';
    return '🌙 夜深了';
  },

  _cardSource(stats) {
    const pending = stats.pending || 0;
    const approved = stats.approved || 0;
    const hasWork = pending > 0;
    return `
    <a href="/SOURCES.html" class="home-card" style="text-decoration:none;color:inherit;display:block;padding:18px 20px;background:var(--card-bg);border:1px solid var(--border);border-radius:8px;box-shadow:var(--card-shadow);transition:all 0.15s" onmouseover="this.style.transform='translateY(-2px)'" onmouseout="this.style.transform=''">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
        <span style="font-size:13px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.05em">📡 信息源</span>
        <span style="font-size:18px">→</span>
      </div>
      <div style="font-size:24px;font-weight:600;margin-bottom:4px">${pending} <span style="font-size:14px;color:var(--text-muted);font-weight:normal">待你过目</span></div>
      <div style="font-size:12px;color:var(--text-muted)">${approved} 个已加入清单 · ${hasWork ? '<span style="color:var(--accent)">点开浏览</span>' : '今天没新源'}</div>
    </a>`;
  },

  _cardPacks(count) {
    const hasWork = count > 0;
    return `
    <div style="padding:18px 20px;background:var(--card-bg);border:1px solid var(--border);border-radius:8px;box-shadow:var(--card-shadow)">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
        <span style="font-size:13px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.05em">📦 推荐方案</span>
        <span style="font-size:11px;color:${hasWork ? 'var(--accent)' : 'var(--text-muted)'}">${hasWork ? '今日可发' : '无'}</span>
      </div>
      <div style="font-size:24px;font-weight:600;margin-bottom:4px">${count} <span style="font-size:14px;color:var(--text-muted);font-weight:normal">组方案</span></div>
      <div style="font-size:12px;color:var(--text-muted)">${hasWork ? '<span style="color:var(--accent)">下方可直接审</span>' : 'pipeline 跑完后会出现'}</div>
    </div>`;
  },

  _cardFeedback(fb) {
    const count = fb.count || 0;
    return `
    <div style="padding:18px 20px;background:var(--card-bg);border:1px solid var(--border);border-radius:8px;box-shadow:var(--card-shadow)">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
        <span style="font-size:13px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.05em">💬 今日反馈</span>
        <span style="font-size:11px;color:var(--text-muted)">对味 / 不对味</span>
      </div>
      <div style="font-size:24px;font-weight:600;margin-bottom:4px">${count} <span style="font-size:14px;color:var(--text-muted);font-weight:normal">次</span></div>
      <div style="font-size:12px;color:var(--text-muted)">进图谱调权重</div>
    </div>`;
  },

  _cardWeekly(w) {
    const pub = w.publish_count || 0;
    const reach = w.total_reach || 0;
    const engagement = w.total_interactions || 0;
    const hasData = pub > 0;
    return `
    <div style="padding:18px 20px;background:var(--card-bg);border:1px solid var(--border);border-radius:8px;box-shadow:var(--card-shadow)">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
        <span style="font-size:13px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.05em">📊 本周数据</span>
        <span style="font-size:11px;color:${hasData ? 'var(--green)' : 'var(--text-muted)'}">${hasData ? '已发布' : '未发布'}</span>
      </div>
      <div style="font-size:24px;font-weight:600;margin-bottom:4px">${pub} <span style="font-size:14px;color:var(--text-muted);font-weight:normal">篇</span></div>
      <div style="font-size:12px;color:var(--text-muted)">${reach.toLocaleString()} 曝光 · ${engagement.toLocaleString()} 互动</div>
    </div>`;
  },
};