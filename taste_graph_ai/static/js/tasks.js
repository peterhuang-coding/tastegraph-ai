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
          <div class="task-title">${this.esc(t.title)}</div>
          ${t.body ? `<div class="task-body">${this.esc(t.body)}</div>` : ''}
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

  esc(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }
};
