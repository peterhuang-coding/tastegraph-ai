// Tab 0: 今日动作 (Home Dashboard)
// 3 分钟运营界面 — ① 抽样打标 ② 今日采样 ③ 反馈回路
// 调试/admin tab 折叠到底部 ⚙ 调试区
const HomeTab = {
  async load() {
    const container = document.getElementById('tab-home');
    App.renderLoading(container);
    try {
      const [srcStats, pendingSources, dailyData, weeklySum, feedbackCount, spotcheck] = await Promise.all([
        API.get('/api/v1/sources/stats').catch(() => ({pending:0, approved:0, rejected:0})),
        API.get('/api/v1/sources/pending?limit=10').catch(() => []),
        API.get('/api/v1/daily/today').catch(() => ({packs:[]})),
        API.get('/api/v1/feedback/weekly-summary').catch(() => ({publish_count:0, total_reach:0, total_interactions:0})),
        API.get('/api/v1/feedback/today-count').catch(() => ({count:0})),
        API.get('/api/v1/feedback/spotcheck?count=20').catch(() => ({total_unreviewed:0, images:[]})),
      ]);
      this.render(container, { srcStats, pendingSources, dailyData, weeklySum, feedbackCount, spotcheck });
    } catch(e) {
      container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">⚠️</div><p>加载失败: ${e.message}</p></div>`;
    }
  },

  render(container, { srcStats, pendingSources, dailyData, weeklySum, feedbackCount, spotcheck }) {
    const today = new Date().toISOString().slice(0,10);
    const packCount = (dailyData.packs || []).length;
    const spotImages = (spotcheck.images || []);
    const unreviewed = spotcheck.total_unreviewed || 0;
    const sources = pendingSources || [];
    const sourceCount = srcStats.pending || sources.length;

    const html = `
    <div class="home-header" style="margin-bottom:24px;padding-bottom:16px;border-bottom:2px solid var(--border)">
      <h2 style="margin:0 0 4px;font-size:22px">${this._greeting()}</h2>
      <div style="font-size:13px;color:var(--text-muted)">${today} · moodboard. · 3 分钟搞定今天</div>
    </div>

    <!-- ① 数据源头 check -->
    <section class="home-block" style="margin-bottom:24px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <h3 style="margin:0;font-size:16px;display:flex;align-items:center;gap:8px">
          <span style="color:var(--accent);font-weight:700">①</span>
          数据源头 · check 新源
        </h3>
        <span style="font-size:12px;color:var(--text-muted)">${sourceCount} 个待审 · 累计 ✅${srcStats.approved || 0} / ❌${srcStats.rejected || 0}</span>
      </div>
      ${sources.length > 0
        ? `<p style="font-size:12px;color:var(--text-muted);margin:0 0 12px">爬虫新发现的源 · ✅ 采纳进图谱 / ❌ 拒掉避免污染</p>
           <div id="home-sources"></div>`
        : `<div style="padding:18px;text-align:center;background:var(--bg-card);border:1px dashed var(--border);border-radius:8px">
            <div style="color:var(--text-muted);font-size:13px;margin-bottom:4px">没有待审源</div>
            <div style="color:var(--text-dim);font-size:12px">累计已采纳 <strong style="color:var(--green)">${srcStats.approved || 0}</strong> 个 · 拒了 <strong style="color:var(--red)">${srcStats.rejected || 0}</strong> 个 · 下一批爬虫跑完会带新源回来</div>
          </div>`
      }
    </section>

    <!-- ② 抽检图片 20 张 -->
    <section class="home-block" style="margin-bottom:24px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <h3 style="margin:0;font-size:16px;display:flex;align-items:center;gap:8px">
          <span style="color:var(--accent);font-weight:700">②</span>
          抽检图片 · 20 张让你取舍
        </h3>
        <div style="display:flex;align-items:center;gap:10px">
          <span style="font-size:12px;color:var(--text-muted)">${unreviewed} 张待取舍</span>
          ${spotImages.length > 0 ? `<button id="home-ai-tag" style="background:transparent;border:1px solid var(--accent);color:var(--accent);padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px;font-family:inherit">🤖 AI 自动打标(${spotImages.length}张)</button>` : ''}
        </div>
      </div>
      ${spotImages.length > 0
        ? `<p style="font-size:12px;color:var(--text-muted);margin:0 0 12px">✓ 对味 → 图谱权重加 / ⭐ 精 → 进今日 pack / ⏭ 弃 · 顶部 🤖 是 Vision LLM 预打标(单独视觉,不污染你的取舍)</p>
           <div id="home-spotcheck" style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px"></div>`
        : `<div style="padding:18px;text-align:center;background:var(--bg-card);border:1px dashed var(--border);border-radius:8px">
            <div style="color:var(--text-muted);font-size:13px">没有待取舍的图 · 下一批爬完就会回来</div>
          </div>`
      }
      <div id="home-ai-tag-status" style="margin-top:8px;font-size:11px;color:var(--text-muted);min-height:16px;font-family:var(--font-mono)"></div>
    </section>

    <!-- ③ 筛选文案 5-6 个 pack -->
    <section class="home-block" style="margin-bottom:24px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        <h3 style="margin:0;font-size:16px;display:flex;align-items:center;gap:8px">
          <span style="color:var(--accent);font-weight:700">③</span>
          筛选文案 · 选 1 个去发布
        </h3>
        <span style="font-size:12px;color:var(--text-muted)">${packCount} 组候选</span>
      </div>
      ${packCount > 0 ? this._renderPackGrid(dailyData.packs) : `
        <div style="padding:18px;text-align:center;background:var(--bg-card);border:1px dashed var(--border);border-radius:8px">
          <div style="color:var(--text-muted);font-size:13px;margin-bottom:6px">今日还没生成 pack</div>
          <div style="color:var(--text-dim);font-size:12px">爬虫抓的图要经抽检 → 才能生成 pack · 先做 ①② 步</div>
        </div>
      `}
    </section>

    <!-- ④ 触发操作 -->
    <section class="home-block" style="margin-bottom:24px">
      <h3 style="margin:0 0 12px;font-size:16px;display:flex;align-items:center;gap:8px">
        <span style="color:var(--accent);font-weight:700">④</span>
        触发操作 · <span style="color:var(--text-muted);font-weight:normal;font-size:13px">不用切 tab</span>
      </h3>
      <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px">
        <button id="home-run-crawler" class="home-action-btn" style="padding:14px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px;cursor:pointer;text-align:left;color:var(--text);font-family:inherit;font-size:13px">
          <div style="font-size:14px;font-weight:600;margin-bottom:4px">🕷 跑一次爬虫</div>
          <div style="font-size:11px;color:var(--text-muted)">约 30 秒 · 5 个站</div>
        </button>
        <button id="home-run-pipeline" class="home-action-btn" style="padding:14px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px;cursor:pointer;text-align:left;color:var(--text);font-family:inherit;font-size:13px">
          <div style="font-size:14px;font-weight:600;margin-bottom:4px">⚙ 跑一次全流程</div>
          <div style="font-size:11px;color:var(--text-muted)">发现新源 → 评估 → 生成任务</div>
        </button>
        <button id="home-publish-pilot" class="home-action-btn" style="padding:14px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px;cursor:pointer;text-align:left;color:var(--text);font-family:inherit;font-size:13px">
          <div style="font-size:14px;font-weight:600;margin-bottom:4px">🚀 一键发布(视频号 Pilot)</div>
          <div style="font-size:11px;color:var(--text-muted)">入口 UI · 等 aitoearn Key 联调</div>
        </button>
        <button id="home-placeholder-2" class="home-action-btn" style="padding:14px;background:transparent;border:1px dashed var(--border);border-radius:8px;cursor:default;text-align:left;color:var(--text-dim);font-family:inherit;font-size:13px">
          <div style="font-size:14px;font-weight:600;margin-bottom:4px">📅 排期日历</div>
          <div style="font-size:11px;color:var(--text-dim)">占位 · 后续接 daily tab</div>
        </button>
      </div>
      <div id="home-publish-status" style="margin-top:10px;padding:10px 12px;background:var(--bg-card);border:1px solid var(--border);border-radius:6px;font-size:12px;color:var(--text-muted);display:none"></div>
      <div id="home-action-log" style="margin-top:10px;font-size:12px;color:var(--text-muted);font-family:var(--font-mono);min-height:18px"></div>
    </section>

    <!-- ⑤ 反馈回路 -->
    <section class="home-block" style="margin-bottom:24px">
      <h3 style="margin:0 0 12px;font-size:16px;display:flex;align-items:center;gap:8px">
        <span style="color:var(--accent);font-weight:700">⑤</span>
        反馈回路 · <span style="color:var(--text-muted);font-weight:normal;font-size:13px">你今天做了 → 系统学到了</span>
      </h3>
      ${this._feedbackLoop(srcStats, weeklySum, feedbackCount)}
    </section>
    `;

    container.innerHTML = html;
    this._bindActions();
    this._bindPackOpen();
    this._bindPackAct();
    this._bindAiTag();
    this._bindPublishPilot();

    if (spotImages.length > 0) {
      this._renderSpotcheck(spotImages);
    }

    if (sources.length > 0) {
      this._renderPendingSources(sources);
    }
  },

  _renderPendingSources(sources) {
    const el = document.getElementById('home-sources');
    if (!el) return;
    el.innerHTML = sources.map(s => {
      const score = s.ai_score != null ? Math.round(s.ai_score * 100) : null;
      const risk = s.ai_risk || 'unknown';
      const riskColor = risk === 'low' ? 'var(--green)' : risk === 'medium' ? 'var(--yellow)' : 'var(--red)';
      const reason = s.ai_reason || '';
      const url = s.url || '';
      const domain = (() => { try { return new URL(url).hostname; } catch { return url.slice(0, 40); } })();

      return `
      <div style="display:flex;gap:12px;padding:12px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px;margin-bottom:8px;align-items:center">
        <div style="flex:1;min-width:0">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
            <span style="font-size:14px;font-weight:500">${App.esc(s.name || domain)}</span>
            ${score != null ? `<span style="font-size:11px;color:var(--text-muted)">评分 ${score}</span>` : ''}
            <span style="font-size:11px;color:${riskColor};padding:1px 6px;border:1px solid ${riskColor};border-radius:3px">风险 ${App.esc(risk)}</span>
          </div>
          <div style="font-size:11px;color:var(--text-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${App.esc(domain)}</div>
          ${reason ? `<div style="font-size:11px;color:var(--text-muted);margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${App.esc(reason)}</div>` : ''}
        </div>
        <div style="flex:0 0 auto;display:flex;gap:4px">
          <button class="home-source-act" data-act="approve" data-id="${s.id}" style="background:transparent;border:1px solid var(--green);color:var(--green);padding:6px 10px;border-radius:4px;cursor:pointer;font-size:11px;font-family:inherit">✅ 采纳</button>
          <button class="home-source-act" data-act="reject" data-id="${s.id}" style="background:transparent;border:1px solid var(--red);color:var(--red);padding:6px 10px;border-radius:4px;cursor:pointer;font-size:11px;font-family:inherit">❌ 拒</button>
          <a href="${App.esc(url)}" target="_blank" rel="noopener" style="background:transparent;border:1px solid var(--border);color:var(--text-muted);padding:6px 10px;border-radius:4px;font-size:11px;text-decoration:none">查看</a>
        </div>
      </div>
    `;
    }).join('');

    this._bindSourceAct();
  },

  _renderPackGrid(packs) {
    return packs.map(p => {
      const img = p.images && p.images[0];
      const imgSrc = img ? (img.image_url || img.local_path || img.url) : '';
      const title = (p.title_options && p.title_options[0]) || p.theme || '(无标题)';
      const theme = p.theme || '';
      const score = Math.round((p.taste_score || 0) * 100);
        const status = p.status || 'draft';
        const statusMap = {
          draft:    { label: '📝 草稿',   color: 'var(--yellow)' },
          selected: { label: '✅ 已选',   color: 'var(--accent-bright)' },
          published:{ label: '📤 已发',   color: 'var(--green)' },
          rejected: { label: '❌ 已拒',   color: 'var(--red)' },
        };
        const st = statusMap[status] || statusMap.draft;
        const time = p.created_at ? new Date(p.created_at).toLocaleString('zh-CN', { hour12:false, hour:'2-digit', minute:'2-digit' }) : '';

        return `
          <div style="display:flex;gap:12px;padding:12px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px;margin-bottom:8px;align-items:center">
            <a href="${imgSrc}" target="_blank" rel="noopener" style="flex:0 0 96px;width:96px;height:96px;border-radius:6px;overflow:hidden;background:var(--bg);display:block">
              <img src="${imgSrc}" alt="" loading="lazy" style="width:100%;height:100%;object-fit:cover;display:block"
                   onerror="this.parentElement.innerHTML='<div style=padding:24px;text-align:center;color:var(--text-dim);font-size:11px>无图</div>'">
            </a>
            <div style="flex:1;min-width:0">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
                <span style="font-size:11px;color:${st.color};font-weight:600;background:var(--bg);padding:2px 6px;border-radius:3px;border:1px solid var(--border)">${st.label}</span>
                <span style="font-size:11px;color:var(--text-dim)">评分 ${score}</span>
                <span style="font-size:11px;color:var(--text-dim)">${time}</span>
              </div>
              <div style="font-size:14px;color:var(--text);font-weight:500;margin-bottom:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${App.esc(title)}</div>
              <div style="font-size:12px;color:var(--text-muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">主题 · ${App.esc(theme || '—')}</div>
            </div>
            <div style="flex:0 0 auto;display:flex;gap:4px;flex-wrap:wrap">
              <button class="home-pack-act" data-act="select" data-id="${p.id}" title="选这组发布" style="background:transparent;border:1px solid var(--green);color:var(--green);padding:6px 10px;border-radius:4px;cursor:pointer;font-size:11px;font-family:inherit">✅ 选</button>
              <button class="home-pack-act" data-act="reject" data-id="${p.id}" title="拒绝并回图谱" style="background:transparent;border:1px solid var(--red);color:var(--red);padding:6px 10px;border-radius:4px;cursor:pointer;font-size:11px;font-family:inherit">❌ 拒</button>
              <button class="home-pack-open" data-id="${p.id}" title="查看完整详情" style="background:transparent;border:1px solid var(--border);color:var(--text-muted);padding:6px 10px;border-radius:4px;cursor:pointer;font-size:11px;font-family:inherit">查看</button>
            </div>
          </div>
        `;
      }).join('');
  },

  _renderSpotcheck(images) {
    const el = document.getElementById('home-spotcheck');
    if (!el) return;
    el.innerHTML = images.map(img => `
      <div class="spot-card" data-id="${App.esc(img.image_id)}" data-local-path="${App.esc(img.local_path || '')}" style="background:var(--bg-card);border:1px solid var(--border);border-radius:8px;overflow:hidden;box-shadow:var(--shadow)">
        <a href="${App.esc(img.page_url || img.url)}" target="_blank" rel="noopener" style="display:block;aspect-ratio:1;background:var(--bg)">
          <img src="${App.esc(img.image_url || (img.local_path ? '/images/' + img.local_path.split('/').pop() : img.url || ''))}" alt="" loading="lazy"
               style="width:100%;height:100%;object-fit:cover;display:block"
               onerror="this.parentElement.innerHTML='<div style=padding:24px;text-align:center;color:var(--text-dim);font-size:12px>图加载失败</div>'">
        </a>
        <div style="padding:8px 10px;font-size:11px;color:var(--text-muted);border-bottom:1px solid var(--border)">
          ${App.esc(img.source_name || '未知源')}${img.keywords && img.keywords.length ? ' · ' + App.esc(img.keywords.slice(0,2).join(' ')) : ''}
        </div>
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--border)">
          <button class="spot-btn" data-label="对味" style="background:var(--bg-card);border:0;padding:6px 4px;cursor:pointer;font-size:12px;color:var(--green)">✓ 对味</button>
          <button class="spot-btn" data-label="精"  style="background:var(--bg-card);border:0;padding:6px 4px;cursor:pointer;font-size:12px;color:var(--accent-bright);font-weight:600">⭐ 精</button>
          <button class="spot-btn" data-label="弃"  style="background:var(--bg-card);border:0;padding:6px 4px;cursor:pointer;font-size:12px;color:var(--text-muted)">⏭ 弃</button>
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

  _feedbackLoop(srcStats, weekly, todayCount) {
    const picks = todayCount.count || 0;
    const pending = srcStats.pending || 0;
    const approved = srcStats.approved || 0;
    const pub = weekly.publish_count || 0;
    const reach = weekly.total_reach || 0;

    const xhsBlocked = pub === 0 && reach === 0;
    const statusColor = xhsBlocked ? 'var(--orange)' : 'var(--green)';
    const statusText  = xhsBlocked ? 'XHS 账号封停中' : 'XHS 正常';

    return `
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px">
        <div style="padding:14px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px">
          <div style="font-size:11px;color:var(--text-muted);margin-bottom:6px">你今天的取舍</div>
          <div style="font-size:22px;font-weight:600;color:var(--accent-bright)">${picks}</div>
          <div style="font-size:11px;color:var(--text-dim)">点过 ✓ ⭐ ⏭</div>
        </div>
        <div style="padding:14px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px">
          <div style="font-size:11px;color:var(--text-muted);margin-bottom:6px">图谱收录</div>
          <div style="font-size:22px;font-weight:600;color:var(--green)">${approved}</div>
          <div style="font-size:11px;color:var(--text-dim)">已通过的源</div>
        </div>
        <div style="padding:14px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px">
          <div style="font-size:11px;color:var(--text-muted);margin-bottom:6px">本周发布</div>
          <div style="font-size:22px;font-weight:600;color:${xhsBlocked ? 'var(--text-muted)' : 'var(--accent-bright)'}">${pub}<span style="font-size:12px;color:var(--text-muted);font-weight:normal"> 篇</span></div>
          <div style="font-size:11px;color:var(--text-dim)">${reach.toLocaleString()} 曝光</div>
        </div>
        <div style="padding:14px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px">
          <div style="font-size:11px;color:var(--text-muted);margin-bottom:6px">待审源</div>
          <div style="font-size:22px;font-weight:600;color:${pending > 0 ? 'var(--yellow)' : 'var(--text-muted)'}">${pending}</div>
          <div style="font-size:11px;color:var(--text-dim)">还没动</div>
        </div>
      </div>
      <div style="padding:10px 14px;background:var(--bg-card);border:1px solid var(--border);border-left:3px solid ${statusColor};border-radius:6px;font-size:12px;color:var(--text-muted);display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <span style="color:${statusColor};font-weight:600">● ${statusText}</span>
        <span style="color:var(--text-dim)">·</span>
        <span>你按"对味/精/弃"的动作会回流到图谱权重 — 按得越多,下一批采样越准</span>
      </div>
    `;
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

  _reload() {
    const container = document.getElementById('tab-home');
    this.load();
  },

  _bindActions() {
    const crawlerBtn = document.getElementById('home-run-crawler');
    const pipeBtn   = document.getElementById('home-run-pipeline');
    const log       = document.getElementById('home-action-log');
    if (!crawlerBtn || !pipeBtn) return;

    const setBusy = (btn, busy) => {
      btn.disabled = busy;
      btn.style.opacity = busy ? '0.5' : '1';
      btn.style.cursor = busy ? 'wait' : 'pointer';
    };

    crawlerBtn.addEventListener('click', async () => {
      setBusy(crawlerBtn, true);
      setBusy(pipeBtn, true);
      const t0 = Date.now();
      log.textContent = `▶ 爬虫启动 ${new Date().toLocaleTimeString()} …`;
      try {
        const r = await fetch('/api/v1/crawler/run', { method: 'POST' });
        const d = await r.json();
        const sec = Math.round((Date.now() - t0) / 1000);
        if (d.success) {
          const sig = (d.records || []).filter(x => x.blocked).length;
          log.innerHTML = `✅ ${new Date().toLocaleTimeString()} · 跑了 ${d.n_total} 个站 · 健康 <strong style="color:var(--green)">${d.n_healthy}</strong> · 撞反爬 <strong style="color:var(--orange)">${sig}</strong> · ${sec}s`;
        } else {
          log.innerHTML = `❌ ${new Date().toLocaleTimeString()} · ${d.error || '失败'}${d.stderr_tail ? ' · ' + d.stderr_tail.slice(-80) : ''}`;
        }
      } catch (e) {
        log.innerHTML = `❌ ${new Date().toLocaleTimeString()} · ${e.message}`;
      } finally {
        setBusy(crawlerBtn, false);
        setBusy(pipeBtn, false);
      }
    });

    pipeBtn.addEventListener('click', async () => {
      setBusy(pipeBtn, true);
      setBusy(crawlerBtn, true);
      const t0 = Date.now();
      log.textContent = `▶ Pipeline 启动 ${new Date().toLocaleTimeString()} …`;
      try {
        const d = await API.post('/api/v1/pipeline/full');
        const sec = Math.round((Date.now() - t0) / 1000);
        log.innerHTML = d.success
          ? `✅ ${new Date().toLocaleTimeString()} · ${d.message || '完成'} · ${sec}s`
          : `❌ ${new Date().toLocaleTimeString()} · ${d.message || '失败'} · ${sec}s`;
      } catch (e) {
        log.innerHTML = `❌ ${new Date().toLocaleTimeString()} · ${e.message}`;
      } finally {
        setBusy(pipeBtn, false);
        setBusy(crawlerBtn, false);
      }
    });
  },

  _bindPackOpen() {
    const container = document.getElementById('tab-home');
    if (!container) return;
    container.querySelectorAll('.home-pack-open').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.dataset.id;
        // 切到 daily tab (admin 折叠区里),触发 DailyTab 加载这个 pack 详情
        const dailyBtn = document.querySelector('[data-tab="daily"]');
        if (dailyBtn) {
          // Open admin section if hidden
          const section = document.getElementById('admin-section');
          if (section && section.hasAttribute('hidden')) {
            const toggle = document.getElementById('admin-toggle');
            if (toggle) toggle.click();
          }
          dailyBtn.click();
        }
      });
    });
  },

  _bindSourceAct() {
    const container = document.getElementById('tab-home');
    if (!container) return;
    container.querySelectorAll('.home-source-act').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.id;
        const act = btn.dataset.act;
        const card = btn.closest('[style*="background:var(--bg-card)"]');
        if (card) card.querySelectorAll('button').forEach(b => { b.disabled = true; b.style.opacity = '0.4'; });
        try {
          if (act === 'approve') {
            await fetch(`/api/v1/sources/${id}/approve`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
            this._toast(`✅ 已采纳 ${id} · 下次爬虫会用这个源`, 'success');
          } else if (act === 'reject') {
            await fetch(`/api/v1/sources/${id}/reject`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
            this._toast(`❌ 已拒 ${id} · 该源不再爬`, 'success');
          }
          setTimeout(() => this.load(), 400);
        } catch (e) {
          this._toast(`❌ ${e.message}`, 'error');
          if (card) card.querySelectorAll('button').forEach(b => { b.disabled = false; b.style.opacity = '1'; });
        }
      });
    });
  },

  _bindPackAct() {
    const container = document.getElementById('tab-home');
    if (!container) return;
    container.querySelectorAll('.home-pack-act').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.id;
        const act = btn.dataset.act;
        // disable all 3 buttons in this card during the call
        const card = btn.closest('[style*="background:var(--bg-card)"]');
        if (card) card.querySelectorAll('button').forEach(b => { b.disabled = true; b.style.opacity = '0.4'; });
        try {
          if (act === 'select') {
            await fetch(`/api/v1/daily/${id}/select`, { method: 'POST' });
            this._toast(`✅ 已选 ${id}`, 'success');
          } else if (act === 'reject') {
            await fetch(`/api/v1/daily/${id}/reject`, { method: 'POST' });
            this._toast(`❌ 已拒 ${id} · 图回图谱`, 'success');
          }
          // Refresh home to show updated status
          setTimeout(() => this.load(), 400);
        } catch (e) {
          this._toast(`❌ ${e.message}`, 'error');
          if (card) card.querySelectorAll('button').forEach(b => { b.disabled = false; b.style.opacity = '1'; });
        }
      });
    });
  },

  _toast(msg, type) {
    if (typeof App !== 'undefined' && App.toast) {
      App.toast(msg, type);
    } else {
      const log = document.getElementById('home-action-log');
      if (log) log.textContent = msg;
    }
  },

  // ── L1: AI 自动打标 ──────────────────────────────────────────
  _bindAiTag() {
    const btn = document.getElementById('home-ai-tag');
    const status = document.getElementById('home-ai-tag-status');
    if (!btn) return;
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      btn.style.opacity = '0.5';
      if (status) status.textContent = '▶ AI 打标启动 …';

      const cards = Array.from(document.querySelectorAll('.spot-card'));
      const paths = cards.map(c => {
        const img = c.querySelector('img');
        // 优先用 data-local-path(feedback/spotcheck 接口返回的字段),
        // 没有就退化到 img.src(由 home.js 自己渲染的图片 URL)
        return c.dataset.localPath || (img ? img.getAttribute('src') : '') || '';
      }).filter(Boolean);

      if (!paths.length) {
        if (status) status.textContent = '⚠️ 拿不到图片路径,无法打标';
        btn.disabled = false;
        btn.style.opacity = '1';
        return;
      }

      try {
        const res = await fetch('/api/v1/tagger/spotcheck', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ images: paths, theme_hint: '' }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        const results = data.results || [];
        this._renderAiTags(cards, results);
        if (status) status.textContent = `✅ ${results.length}/${paths.length} 张完成 · 用时 ${data.elapsed_ms}ms`;
      } catch (e) {
        if (status) status.textContent = `❌ AI 打标失败: ${e.message}`;
      } finally {
        btn.disabled = false;
        btn.style.opacity = '1';
      }
    });
  },

  _renderAiTags(cards, results) {
    // 按 image_path 后缀做轻匹配,保证顺序一致
    const byKey = new Map();
    for (const r of results) {
      const k = (r.image_path || '').split('/').pop();
      byKey.set(k, r);
    }
    cards.forEach(card => {
      const img = card.querySelector('img');
      const src = img ? (img.getAttribute('src') || '') : '';
      const key = src.split('/').pop();
      const r = byKey.get(key);
      if (!r) return;

      // 移除旧的 AI 标签区
      const old = card.querySelector('.ai-tag-strip');
      if (old) old.remove();

      const styleLbl = r.style_label || '未分类';
      const score = (typeof r.score === 'number') ? r.score.toFixed(2) : '—';
      const tags = (r.tags || []).slice(0, 4);
      const scoreColor = r.score >= 0.7 ? 'var(--green)' : (r.score >= 0.4 ? 'var(--yellow)' : 'var(--text-dim)');

      const strip = document.createElement('div');
      strip.className = 'ai-tag-strip';
      strip.style.cssText = 'padding:6px 8px;background:rgba(99,99,255,0.08);border-top:1px solid var(--border);font-size:10px;line-height:1.4';

      const chips = tags.map(t => `<span style="display:inline-block;padding:1px 5px;margin:0 3px 2px 0;background:var(--bg);border:1px solid var(--border);border-radius:3px;color:var(--text-muted)">${App.esc(t)}</span>`).join('');

      strip.innerHTML = `
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">
          <span style="font-weight:600;color:var(--accent-bright)">${App.esc(styleLbl)}</span>
          <span style="color:${scoreColor};font-family:var(--font-mono)">${score}</span>
        </div>
        ${chips ? `<div style="margin-bottom:2px">${chips}</div>` : ''}
        ${r.why ? `<div style="color:var(--text-dim);font-size:10px;line-height:1.3">${App.esc(r.why)}</div>` : ''}
      `;

      // 插在按钮区之前(从底部 stack 顺序:图 → 元数据 → AI strip → 按钮)
      const btnGrid = card.querySelector('[style*="grid-template-columns:repeat(3"]');
      if (btnGrid) {
        card.insertBefore(strip, btnGrid);
      } else {
        card.appendChild(strip);
      }
    });
  },

  // ── I2: 视频号 Pilot 入口 ─────────────────────────────────────
  _bindPublishPilot() {
    const btn = document.getElementById('home-publish-pilot');
    const box = document.getElementById('home-publish-status');
    if (!btn) return;
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      btn.style.opacity = '0.5';
      if (box) { box.style.display = 'block'; box.innerHTML = '▶ 检查 aitoearn 平台列表 …'; }

      try {
        const res = await fetch('/api/v1/publish/platforms');
        const data = await res.json();
        if (res.status === 501) {
          if (box) box.innerHTML = `<strong style="color:var(--orange)">⚠️ 先接 aitoearn</strong> · ${App.esc(data.detail || '')}`;
          return;
        }
        const platforms = data.platforms || [];
        const wechat = platforms.find(p => /wechat|视频号|shipinhao|video/i.test(p.id || p.name || ''));
        if (wechat) {
          if (box) box.innerHTML = `
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
              <strong style="color:var(--green)">✅ 视频号已接</strong>
              <span style="color:var(--text-muted)">platform: ${App.esc(wechat.id || wechat.name || 'wechat')}</span>
            </div>
            <div style="margin-top:8px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
              <input id="home-wechat-account" placeholder="account_id" style="flex:1;min-width:140px;padding:4px 8px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:inherit;font-size:12px"/>
              <a href="${App.esc(wechat.oauth_url || '#')}" target="_blank" rel="noopener" style="padding:4px 10px;background:transparent;border:1px solid var(--accent);color:var(--accent);border-radius:4px;font-size:11px;text-decoration:none">去 OAuth</a>
            </div>
          `;
        } else {
          if (box) box.innerHTML = `<strong style="color:var(--orange)">⚠️ 视频号不在平台列表里</strong> · 已支持: ${platforms.map(p => App.esc(p.id || p.name || '?')).join(', ') || '(空)'}`;
        }
      } catch (e) {
        if (box) box.innerHTML = `<strong style="color:var(--red)">❌ ${App.esc(e.message)}</strong>`;
      } finally {
        btn.disabled = false;
        btn.style.opacity = '1';
      }
    });
  },
};
