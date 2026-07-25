// Tab 3: Taste Graph Visualization
// Enhanced with: node type filter, edge relation filter, PNG export,
// neighborhood highlight, zoom controls, weight histogram, orphan stats
const GraphTab = {
  cy: null,
  _nodeTypeFilters: new Set(),  // empty = show all
  _edgeFilters: new Set(),      // empty = show all

  async load() {
    const container = document.getElementById('tab-graph');
    App.renderLoading(container);
    try {
      const [overview, nodes, edges] = await Promise.all([
        API.get('/api/v1/graph/overview'),
        API.get('/api/v1/graph/nodes'),
        API.get('/api/v1/graph/edges'),
      ]);
      this.render(container, overview, nodes, edges);
    } catch(e) {
      container.innerHTML = `<div class="empty-state"><p>加载失败: ${e.message}</p></div>`;
    }
  },

  render(container, overview, nodes, edges) {
    // Compute orphan node count and weight stats
    const connectedNodeIds = new Set();
    edges.forEach(e => { connectedNodeIds.add(e.source); connectedNodeIds.add(e.target); });
    const orphanNodes = nodes.filter(n => !connectedNodeIds.has(n.id));
    const weights = edges.map(e => e.weight);
    const posWeights = weights.filter(w => w > 0);
    const negWeights = weights.filter(w => w < 0);
    const maxWeight = Math.max(...weights.map(Math.abs), 1);

    // Weight histogram bins (5 bins)
    const histogram = this._buildHistogram(weights, 5);

    container.innerHTML = `
      <div style="display:flex;gap:16px;margin-bottom:16px;flex-wrap:wrap">
        <div style="flex:1;min-width:300px;display:flex;gap:24px;background:var(--bg-card);border-radius:var(--radius);padding:16px;border:1px solid var(--border)">
          <div><span style="font-size:24px;font-weight:700">${overview.node_count}</span><br><span style="font-size:12px;color:var(--text-muted)">节点</span></div>
          <div><span style="font-size:24px;font-weight:700">${overview.edge_count}</span><br><span style="font-size:12px;color:var(--text-muted)">边</span></div>
          ${Object.entries(overview.node_types||{}).map(([k,v]) => `
          <div><span style="font-size:24px;font-weight:700;color:var(--accent-bright)">${v}</span><br><span style="font-size:12px;color:var(--text-muted)">${k}</span></div>
          `).join('')}
        </div>
        <div style="display:flex;flex-direction:column;gap:8px;justify-content:center">
          <input type="text" id="graph-search" placeholder="搜索节点..." style="padding:8px 12px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px;width:200px">
          <div style="display:flex;gap:4px">
            <button class="btn btn-ghost btn-sm" onclick="GraphTab.resetView()">重置</button>
            <button class="btn btn-ghost btn-sm" onclick="GraphTab.exportPNG()" title="导出 PNG">⬇ PNG</button>
          </div>
        </div>
      </div>

      <!-- Node type filter -->
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;font-size:11px;align-items:center">
        <span style="color:var(--text-dim)">节点类型:</span>
        ${['concept','source','visual_element','mood','brand','color','object','location','pillar'].map(t => `
        <label style="cursor:pointer;display:flex;align-items:center;gap:3px;opacity:0.8" onmouseenter="this.style.opacity='1'" onmouseleave="this.style.opacity='0.8'">
          <input type="checkbox" class="graph-filter-node" value="${t}" checked onchange="GraphTab.applyFilters()">
          <span style="color:${this._typeColor(t)}">${this._typeLabel(t)}</span>
        </label>`).join('')}
        <span style="margin-left:12px;color:var(--text-dim)">边关系:</span>
        <label style="cursor:pointer"><input type="checkbox" class="graph-filter-edge" value="prefers" checked onchange="GraphTab.applyFilters()"> prefers</label>
        <label style="cursor:pointer"><input type="checkbox" class="graph-filter-edge" value="avoids" checked onchange="GraphTab.applyFilters()"> avoids</label>
        <label style="cursor:pointer"><input type="checkbox" class="graph-filter-edge" value="appears_with" checked onchange="GraphTab.applyFilters()"> appears_with</label>
      </div>

      <!-- Weight histogram + orphan stats -->
      <div style="display:flex;gap:16px;margin-bottom:8px;align-items:flex-end">
        <div style="flex:1;display:flex;gap:2px;align-items:flex-end;height:32px">
          ${histogram.map(b => {
            const pct = maxWeight > 0 ? (b.count / edges.length * 100) : 0;
            return `<div title="${b.label}: ${b.count}" style="flex:1;background:var(--accent);opacity:0.7;height:${Math.max(4, pct * 2)}px;border-radius:2px 2px 0 0"></div>`;
          }).join('')}
        </div>
        <div style="font-size:10px;color:var(--text-dim);white-space:nowrap">
          正边:${posWeights.length} 负边:${negWeights.length}
          ${orphanNodes.length > 0 ? ` · 孤岛节点:${orphanNodes.length}` : ''}
        </div>
      </div>

      <!-- Zoom controls -->
      <div style="display:flex;gap:4px;margin-bottom:8px">
        <button class="btn btn-ghost btn-sm" onclick="GraphTab.zoomIn()" title="放大">+</button>
        <button class="btn btn-ghost btn-sm" onclick="GraphTab.zoomOut()" title="缩小">−</button>
        <button class="btn btn-ghost btn-sm" onclick="GraphTab.fitGraph()" title="适应窗口">⊡</button>
      </div>

      <div id="cy-container" class="graph-container"></div>
      <div id="node-detail" style="margin-top:12px"></div>

      <!-- Recent updates -->
      <div id="graph-recent" style="margin-top:8px;font-size:11px;color:var(--text-dim)"></div>
    `;

    this.initCytoscape(nodes, edges);

    // Search
    document.getElementById('graph-search').addEventListener('input', (e) => {
      const q = e.target.value.toLowerCase();
      if (!q) { this.cy.elements().style('opacity', 1); return; }
      this.cy.elements().style('opacity', 0.15);
      this.cy.nodes().filter(n => n.data('label').toLowerCase().includes(q))
        .style('opacity', 1)
        .connectedEdges().style('opacity', 0.6);
      this.cy.nodes().filter(n => n.data('label').toLowerCase().includes(q))
        .connectedEdges().connectedNodes().style('opacity', 1);
    });

    // Show recent nodes
    this._showRecentNodes(edges, orphanNodes);
  },

  // ── Cytoscape init ──────────────────────────────────────────

  initCytoscape(nodes, edges) {
    if (this.cy) this.cy.destroy();

    const colorMap = {
      concept: '#6b8fa3', visual_element: '#c97a46', pillar: '#9b6bcc',
      source: '#5a9eaa', mood: '#c9a946', color_node: '#c55a8a',
      brand: '#7a9e5a', object: '#8a8a8a', location: '#5a8a9e',
    };

    const elements = [
      ...nodes.map(n => ({
        data: { id: n.id, label: n.label, nodeType: n.type, ...n.properties },
        classes: n.type,
      })),
      ...edges.map(e => ({
        data: {
          id: `${e.source}|${e.target}`, source: e.source, target: e.target,
          relation: e.relation, weight: e.weight, feedbackCount: e.feedback_count,
        },
      })),
    ];

    this.cy = cytoscape({
      container: document.getElementById('cy-container'),
      elements,
      style: [
        {
          selector: 'node',
          style: {
            'background-color': (ele) => colorMap[ele.data('nodeType')] || '#888',
            'label': 'data(label)', 'color': '#e0e0e0', 'font-size': '10px',
            'text-valign': 'bottom', 'text-halign': 'center', 'text-margin-y': 6,
            'width': (ele) => 10 + (ele.data('weight') || 1) * 4,
            'height': (ele) => 10 + (ele.data('weight') || 1) * 4,
            'border-width': 1, 'border-color': '#333',
          },
        },
        {
          selector: 'edge',
          style: {
            'width': (ele) => Math.max(1, Math.abs(ele.data('weight')) * 0.8),
            'line-color': (ele) => ele.data('weight') >= 0 ? '#4a7a9e' : '#9e4a4a',
            'target-arrow-color': (ele) => ele.data('weight') >= 0 ? '#4a7a9e' : '#9e4a4a',
            'target-arrow-shape': 'triangle', 'arrow-scale': 0.8,
            'curve-style': 'bezier', 'opacity': 0.6,
          },
        },
      ],
      layout: {
        name: 'cose', animate: false,
        nodeRepulsion: 8000, idealEdgeLength: 120, gravity: 0.3,
      },
    });

    // Click node → show detail
    this.cy.on('tap', 'node', (evt) => {
      this.showNodeDetail(evt.target);
    });
    this.cy.on('tap', (evt) => {
      if (evt.target === this.cy) {
        document.getElementById('node-detail').innerHTML = '';
      }
    });

    // Double-click node → highlight neighborhood
    this.cy.on('dbltap', 'node', (evt) => {
      const node = evt.target;
      this.cy.elements().style('opacity', 0.1);
      node.style('opacity', 1);
      node.connectedEdges().style('opacity', 0.7);
      node.connectedEdges().connectedNodes().style('opacity', 1);
    });
    this.cy.on('dbltap', (evt) => {
      if (evt.target === this.cy) {
        this.cy.elements().style('opacity', 1);
      }
    });
  },

  // ── Node detail ─────────────────────────────────────────────

  showNodeDetail(node) {
    const data = node.data();
    const connected = node.connectedEdges().length;
    document.getElementById('node-detail').innerHTML = `
      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">${App.esc(data.label)}</div>
            <div style="font-size:12px;color:var(--text-dim)">类型: ${data.nodeType} · ID: ${data.id}</div>
          </div>
          <button class="btn btn-ghost btn-sm" onclick="document.getElementById('node-detail').innerHTML=''">✕</button>
        </div>
        <div style="display:flex;gap:16px;font-size:13px;margin:8px 0">
          <span>关联边: <strong>${connected}</strong></span>
          <span>权重: <strong>${data.weight || 1}</strong></span>
        </div>
        ${data.description ? `<p style="font-size:13px;color:var(--text-muted)">${App.esc(data.description)}</p>` : ''}
      </div>`;
  },

  // ── Filters ─────────────────────────────────────────────────

  applyFilters() {
    if (!this.cy) return;
    // Collect active node type filters
    const nodeChecks = document.querySelectorAll('.graph-filter-node');
    const activeNodeTypes = new Set();
    nodeChecks.forEach(cb => { if (cb.checked) activeNodeTypes.add(cb.value); });

    // Collect active edge filters
    const edgeChecks = document.querySelectorAll('.graph-filter-edge');
    const activeEdges = new Set();
    edgeChecks.forEach(cb => { if (cb.checked) activeEdges.add(cb.value); });

    // Apply
    this.cy.nodes().forEach(n => {
      n.style('display', activeNodeTypes.has(n.data('nodeType')) ? 'element' : 'none');
    });
    this.cy.edges().forEach(e => {
      e.style('display', activeEdges.has(e.data('relation')) ? 'element' : 'none');
    });
  },

  // ── Zoom controls ───────────────────────────────────────────

  zoomIn() {
    if (this.cy) this.cy.zoom(this.cy.zoom() * 1.3);
  },
  zoomOut() {
    if (this.cy) this.cy.zoom(this.cy.zoom() * 0.7);
  },
  fitGraph() {
    if (this.cy) { this.cy.fit(); this.cy.center(); }
  },
  resetView() {
    if (this.cy) {
      this.cy.fit();
      this.cy.center();
      this.cy.elements().style('opacity', 1);
      document.getElementById('graph-search').value = '';
      // Reset all filters to checked
      document.querySelectorAll('.graph-filter-node,.graph-filter-edge').forEach(cb => cb.checked = true);
      this.applyFilters();
    }
  },

  // ── PNG Export ──────────────────────────────────────────────

  exportPNG() {
    if (!this.cy) return;
    try {
      const png = this.cy.png({ full: true, bg: '#0f0f0f', scale: 2 });
      const a = document.createElement('a');
      a.href = png;
      a.download = `taste-graph-${new Date().toISOString().slice(0,10)}.png`;
      a.click();
      App.toast('图谱已导出为 PNG', 'success');
    } catch(e) {
      App.toast('导出失败：' + e.message, 'error');
    }
  },

  // ── Helpers ─────────────────────────────────────────────────

  _buildHistogram(weights, bins) {
    if (!weights.length) return [];
    const max = Math.max(...weights.map(Math.abs));
    const step = max / bins || 1;
    const result = [];
    for (let i = 0; i < bins; i++) {
      const lo = i * step;
      const hi = (i + 1) * step;
      const count = weights.filter(w => Math.abs(w) >= lo && Math.abs(w) < hi).length;
      result.push({ label: `${lo.toFixed(1)}-${hi.toFixed(1)}`, count });
    }
    return result;
  },

  _typeColor(t) {
    const map = { concept: '#6b8fa3', source: '#5a9eaa', visual_element: '#c97a46', mood: '#c9a946', brand: '#7a9e5a', color: '#c55a8a', object: '#8a8a8a', location: '#5a8a9e', pillar: '#9b6bcc' };
    return map[t] || '#888';
  },

  _typeLabel(t) {
    const map = { concept: '概念', source: '源', visual_element: '视觉', mood: '情绪', brand: '品牌', color: '颜色', object: '物体', location: '地点', pillar: '支柱' };
    return map[t] || t;
  },

  _showRecentNodes(edges, orphanNodes) {
    // Show nodes with most recent edge updates (top 5)
    const now = Date.now();
    const scored = [];
    const seen = new Set();
    edges.forEach(e => {
      if (e.last_updated && !seen.has(e.source)) {
        seen.add(e.source);
        scored.push({ id: e.source, ts: e.last_updated });
      }
      if (e.last_updated && !seen.has(e.target)) {
        seen.add(e.target);
        scored.push({ id: e.target, ts: e.last_updated });
      }
    });
    scored.sort((a, b) => b.ts.localeCompare(a.ts));
    const recent = scored.slice(0, 5);

    let html = '';
    if (recent.length) {
      html += '<span style="margin-right:12px">最近更新: </span>';
      recent.forEach(r => {
        html += `<span style="margin-right:8px;color:var(--accent-bright)">${App.esc(r.id.split(':')[1] || r.id)}</span>`;
      });
    }
    if (orphanNodes.length > 0) {
      html += `<span style="margin-left:8px;color:var(--yellow)">⚠ ${orphanNodes.length} 个孤岛节点</span>`;
    }
    document.getElementById('graph-recent').innerHTML = html;
  }
};
