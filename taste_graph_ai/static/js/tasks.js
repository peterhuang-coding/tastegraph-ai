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
    };

    container.innerHTML = tasks.map(t => `
      <div class="task-item priority-${t.priority}" id="task-${t.id}">
        <span class="task-icon">${iconMap[t.task_type] || '📋'}</span>
        <div class="task-text">
          <div class="task-title">${this.esc(t.title)}</div>
          ${t.body ? `<div class="task-body">${this.esc(t.body)}</div>` : ''}
        </div>
        <div class="task-actions">
          ${t.action_url ? `<button class="btn btn-ghost btn-sm" onclick="Tasks.goto('${t.action_url}')">前往</button>` : ''}
          <button class="btn btn-success btn-sm" onclick="Tasks.complete('${t.id}')">完成</button>
          <button class="btn btn-ghost btn-sm" onclick="Tasks.dismiss('${t.id}')">忽略</button>
        </div>
      </div>
    `).join('');
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

  goto(url) {
    App.switchTab(url.includes('sources') ? 'sources' : 'daily');
  },

  esc(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }
};
