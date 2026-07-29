// Task bar (displayed across all tabs)
const Tasks = {
  renderBar(tasks) {
    const container = document.getElementById('task-bar');
    if (!tasks || tasks.length === 0) {
      container.innerHTML = '';
      return;
    }

    const iconMap = {
      review_sources: '📥',
      stale_review: '⏰',
      theme_suggestion: '💡',
      trend_alert: '📈',
      product_seed: '🌱',
      source_rotation: '🔄',
      series_idea: '📺',
      gap_alert: '⚠️',
      publish_pack: '🚀',
    };

    container.innerHTML = tasks.map(t => {
      const isPublish = t.task_type === 'publish_pack';
      const gotoBtn = t.action_url && !isPublish
        ? `<button class="btn btn-ghost btn-sm" onclick="Tasks.goto('${t.action_url}')">前往</button>`
        : '';
      const publishBtn = isPublish
        ? `<button class="btn btn-accent btn-sm" onclick="Tasks.cdpPublish('${t.id}', '${t.action_url || ''}')">发布</button>`
        : '';
      return `
      <div class="task-item priority-${t.priority}" id="task-${t.id}">
        <span class="task-icon">${iconMap[t.task_type] || '📋'}</span>
        <div class="task-text">
          <div class="task-title">${App.esc(t.title)}</div>
          ${t.body ? `<div class="task-body">${App.esc(t.body)}</div>` : ''}
        </div>
        <div class="task-actions">
          ${gotoBtn}
          ${publishBtn}
          <button class="btn btn-success btn-sm" onclick="Tasks.complete('${t.id}')">完成</button>
          <button class="btn btn-ghost btn-sm" onclick="Tasks.dismiss('${t.id}')">忽略</button>
        </div>
      </div>
    `}).join('');
  },

  async complete(taskId) {
    try {
      await API.post(`/api/v1/tasks/${taskId}/complete`);
      App.toast('任务完成');
      App.loadTaskBar();
    } catch(e) { App.toast('操作失败', 'error'); }
  },

  async dismiss(taskId) {
    try {
      await API.post(`/api/v1/tasks/${taskId}/dismiss`);
      App.toast('任务已忽略');
      App.loadTaskBar();
    } catch(e) { App.toast('操作失败', 'error'); }
  },

  async cdpPublish(taskId, actionUrl) {
    // Extract pack_id from action_url query string
    const match = actionUrl && actionUrl.match(/pack_id=([^&]+)/);
    const packId = match ? match[1] : '';
    if (!packId) { App.toast('无法解析 pack ID', 'error'); return; }

    try {
      App.toast('正在通过浏览器发布...', 'info');
      const result = await API.post('/api/v1/pipeline/cdp-publish', { pack_id: packId });
      if (result.success) {
        App.toast(`发布成功！${result.data?.post_url || ''}`, 'success');
        Tasks.complete(taskId);
      } else {
        App.toast(`发布失败: ${result.message}`, 'error');
      }
    } catch (e) {
      App.toast(`发布请求失败: ${e.message || e}`, 'error');
    }
  },

  goto(url) {
    App.switchTab(url.includes('sources') ? 'sources' : 'daily');
  },
};

// Tab 9: Task management
const TasksTab = {
  _filter: 'today',  // 'today' | 'pending' | 'history'

  async load() {
    const container = document.getElementById('tab-tasks');
    App.renderLoading(container);
    try {
      const tasks = await this._fetch();
      this.render(container, tasks);
    } catch(e) {
      container.innerHTML = `<div class="empty-state"><p>加载失败: ${App.esc(e.message)}</p></div>`;
    }
  },

  async _fetch() {
    return API.get(`/api/v1/tasks/${this._filter}`);
  },

  render(container, tasks) {
    const filters = [
      {key: 'today', label: '今日'},
      {key: 'pending', label: '待处理'},
      {key: 'history', label: '历史'},
    ];

    container.innerHTML = `
      <div style="margin-bottom:16px;display:flex;gap:8px;flex-wrap:wrap">
        ${filters.map(filter => `
          <button type="button" class="btn ${this._filter === filter.key ? 'btn-primary' : 'btn-ghost'} btn-sm"
                  onclick="TasksTab.setFilter('${filter.key}')">${filter.label}</button>
        `).join('')}
      </div>
      <div class="tasks-tab-list"></div>
    `;

    const list = container.querySelector('.tasks-tab-list');
    if (!Array.isArray(tasks) || tasks.length === 0) {
      const emptyMessages = {
        today: '今天暂无任务',
        pending: '暂无待处理任务',
        history: '暂无历史任务',
      };
      App.renderEmpty(list, emptyMessages[this._filter]);
      return;
    }

    const iconMap = {
      review_sources: '📥',
      stale_review: '⏰',
      theme_suggestion: '💡',
      trend_alert: '📈',
      product_seed: '🌱',
      source_rotation: '🔄',
      series_idea: '📺',
      gap_alert: '⚠️',
      publish_pack: '🚀',
    };
    const typeLabels = {
      review_sources: '审核来源',
      stale_review: '逾期审核',
      theme_suggestion: '主题建议',
      trend_alert: '趋势提醒',
      product_seed: '产品种子',
      source_rotation: '来源轮换',
      series_idea: '系列创意',
      gap_alert: '内容缺口',
      publish_pack: '发布任务',
    };
    const statusLabels = {
      pending: '待处理',
      completed: '已完成',
      dismissed: '已忽略',
    };

    list.innerHTML = tasks.map(task => {
      const timestamp = task.completed_at || task.created_at;
      const timeLabel = task.completed_at ? '完成于' : '创建于';
      const priorityColor = {
        high: 'var(--red)',
        medium: 'var(--yellow)',
        low: 'var(--text-dim)',
      }[task.priority] || 'var(--border)';

      return `
        <div class="card" style="border-left:3px solid ${priorityColor};display:flex;align-items:flex-start;gap:12px;flex-wrap:wrap">
          <span class="task-icon" style="font-size:24px" aria-hidden="true">${iconMap[task.task_type] || '📋'}</span>
          <div class="task-text" style="min-width:220px">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px">
              <span class="tag tag-muted">${App.esc(typeLabels[task.task_type] || task.task_type)}</span>
              <span class="card-meta">${App.esc(statusLabels[task.status] || task.status)}</span>
              <span class="card-meta">${timeLabel} ${App.esc(this._formatTime(timestamp))}</span>
            </div>
            <div class="card-title">${App.esc(task.title)}</div>
            ${task.body ? `<p style="font-size:13px;color:var(--text-muted);margin-top:6px">${App.esc(task.body)}</p>` : ''}
          </div>
          <div class="task-actions" style="margin-left:auto">
            <button type="button" class="btn btn-success btn-sm" onclick="TasksTab.complete('${task.id}')">完成</button>
            <button type="button" class="btn btn-ghost btn-sm" onclick="TasksTab.dismiss('${task.id}')">忽略</button>
          </div>
        </div>
      `;
    }).join('');
  },

  setFilter(filter) {
    if (!['today', 'pending', 'history'].includes(filter)) return;
    this._filter = filter;
    this.load();
  },

  _formatTime(value) {
    if (!value) return '时间未知';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value).replace('T', ' ').slice(0, 16);
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  },

  async complete(taskId) {
    await API.post(`/api/v1/tasks/${taskId}/complete`);
    this.load();
    App.toast('已标记完成', 'success');
  },

  async dismiss(taskId) {
    await API.post(`/api/v1/tasks/${taskId}/dismiss`);
    this.load();
    App.toast('已忽略', 'success');
  },
};
