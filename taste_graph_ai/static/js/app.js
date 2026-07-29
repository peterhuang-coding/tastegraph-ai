// TasteGraph AI - Core App
const App = {
  state: { pendingSources: 0, pendingTasks: 0 },

  async init() {
    this.bindTabs();
    this.bindKeyboard();
    this.bindRefresh();
    await this.checkHealth();
    await this.loadTaskBar();
    SourcesTab.load();
    this.refreshBadges();
    setInterval(() => this.refreshBadges(), 60000);
  },

  bindTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        const tab = btn.dataset.tab;
        document.getElementById(`tab-${tab}`).classList.add('active');
        this.onTabChange(tab);
      });
    });
  },

  bindKeyboard() {
    document.addEventListener('keydown', e => {
      if (e.key === '1' && e.metaKey) { e.preventDefault(); this.switchTab('sources'); }
      if (e.key === '2' && e.metaKey) { e.preventDefault(); this.switchTab('daily'); }
      if (e.key === '3' && e.metaKey) { e.preventDefault(); this.switchTab('graph'); }
      if (e.key === '4' && e.metaKey) { e.preventDefault(); this.switchTab('history'); }
      if (e.key === '5' && e.metaKey) { e.preventDefault(); this.switchTab('curation'); }
      if (e.key === '6' && e.metaKey) { e.preventDefault(); this.switchTab('health'); }
      if (e.key === '7' && e.metaKey) { e.preventDefault(); this.switchTab('pipeline'); }
      if (e.key === '8' && e.metaKey) { e.preventDefault(); this.switchTab('crawler'); }
      if (e.key === '9' && e.metaKey) { e.preventDefault(); this.switchTab('tasks'); }
      if (e.key === '0' && e.metaKey) { e.preventDefault(); this.switchTab('weekly'); }
    });
  },

  switchTab(name) {
    document.querySelector(`[data-tab="${name}"]`).click();
  },

  bindRefresh() {
    document.getElementById('refresh-btn').addEventListener('click', () => this.refresh());
    document.addEventListener('keydown', e => {
      if (e.key === 'r' && e.metaKey && !e.shiftKey) { e.preventDefault(); this.refresh(); }
    });
  },

  async refresh() {
    const btn = document.getElementById('refresh-btn');
    btn.textContent = '⟳ 运行中...';
    btn.disabled = true;

    const activeTab = document.querySelector('.tab-btn.active')?.dataset?.tab;
    const container = document.getElementById(`tab-${activeTab}`);
    if (container) {
      container.innerHTML = '<div class="loading"><div class="spinner"></div><p style="margin-top:12px">正在运行推荐引擎...</p><p style="font-size:12px;color:var(--text-dim);margin-top:4px">发现新源 → 评估质量 → 生成运营任务</p></div>';
    }

    try {
      const result = await API.post('/api/v1/pipeline/full');
      if (result.success) {
        this.toast(result.message, 'success');
      } else {
        this.toast(result.message, 'error');
      }
    } catch(e) {
      this.toast(`Pipeline 失败: ${e.message}`, 'error');
    }

    await this.checkHealth();
    await this.loadTaskBar();
    await this.refreshBadges();
    if (activeTab === 'sources') SourcesTab.load();
    if (activeTab === 'daily') DailyTab.load();
    if (activeTab === 'graph') GraphTab.load();
    if (activeTab === 'history') HistoryTab.load();
    if (activeTab === 'curation') CurationTab.load();
    if (activeTab === 'health') HealthTab.load();
    if (activeTab === 'pipeline') PipelineTab.load();
    if (activeTab === 'crawler') CrawlerTab.load();
    if (activeTab === 'tasks') TasksTab.load();
    if (activeTab === 'weekly') WeeklyTab.load();

    btn.textContent = '⟳ 刷新';
    btn.disabled = false;
  },

  async onTabChange(tab) {
    if (tab === 'sources') SourcesTab.load();
    if (tab === 'daily') DailyTab.load();
    if (tab === 'graph') GraphTab.load();
    if (tab === 'history') HistoryTab.load();
    if (tab === 'curation') CurationTab.load();
    if (tab === 'health') HealthTab.load();
    if (tab === 'pipeline') PipelineTab.load();
    if (tab === 'crawler') CrawlerTab.load();
    if (tab === 'tasks') TasksTab.load();
    if (tab === 'weekly') WeeklyTab.load();
  },

  async checkHealth() {
    try {
      const r = await API.get('/api/health');
      const dot = document.getElementById('health-indicator');
      dot.className = 'health-dot ' + (r.status === 'healthy' ? 'ok' : 'error');
      dot.title = JSON.stringify(r.components, null, 2);
    } catch(e) {
      document.getElementById('health-indicator').className = 'health-dot error';
    }
  },

  async loadTaskBar() {
    try {
      const r = await API.get('/api/v1/tasks/pending');
      Tasks.renderBar(r);
    } catch(e) { console.error('Failed to load tasks', e); }
  },

  async refreshBadges() {
    try {
      const stats = await API.get('/api/v1/sources/stats');
      const badge = document.getElementById('sources-badge');
      const count = (stats.pending || 0) + (stats.deferred || 0);
      if (count > 0) {
        badge.textContent = count;
        badge.classList.remove('hidden');
      } else {
        badge.classList.add('hidden');
      }
    } catch(e) {}
  },

  toast(msg, type='success') {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => { el.remove(); }, 3000);
  },

  renderLoading(container) {
    container.innerHTML = '<div class="loading"><div class="spinner"></div><p style="margin-top:12px">加载中...</p></div>';
  },

  renderEmpty(container, msg='暂无数据') {
    container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">📭</div><p>${msg}</p></div>`;
  },

  // Shared HTML escape utility — use this instead of copy-pasting esc() everywhere
  esc(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }
};

// API helper
const API = {
  base: '',
  async get(url) {
    const r = await fetch(this.base + url);
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  async post(url, body={}) {
    const r = await fetch(this.base + url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  async patch(url, body={}) {
    const r = await fetch(this.base + url, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  async del(url) {
    const r = await fetch(this.base + url, { method: 'DELETE' });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  }
};

// Template helper
function h(tag, attrs={}, ...children) {
  const el = document.createElement(tag);
  Object.entries(attrs).forEach(([k,v]) => {
    if (k === 'className') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2).toLowerCase(), v);
    else el.setAttribute(k, v);
  });
  children.forEach(c => {
    if (typeof c === 'string') el.appendChild(document.createTextNode(c));
    else if (c instanceof Node) el.appendChild(c);
  });
  return el;
}
