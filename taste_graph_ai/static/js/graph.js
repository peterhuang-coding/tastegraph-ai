// Tab 3: Taste Graph Visualization
const GraphTab = {
  cy: null,

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
    container.innerHTML = `
      <div style="display:flex;gap:16px;margin-bottom:16px">
        <div style="flex:1;display:flex;gap:24px;background:var(--bg-card);border-radius:var(--radius);padding:16px;border:1px solid var(--border)">
          <div><span style="font-size:24px;font-weight:700">${overview.node_count}</span><br><span style="font-size:12px;color:var(--text-muted)">节点</span></div>
          <div><span style="font-size:24px;font-weight:700">${overview.edge_count}</span><br><span style="font-size:12px;color:var(--text-muted)">边</span></div>
          ${Object.entries(overview.node_types||{}).map(([k,v]) => `
          <div><span style="font-size:24px;font-weight:700;color:var(--accent-bright)">${v}</span><br><span style="font-size:12px;color:var(--text-muted)">${k}</span></div>
          `).join('')}
        </div>
        <div style="display:flex;flex-direction:column;gap:8px;justify-content:center">
          <input type="text" id="graph-search" placeholder="搜索节点..." style="padding:8px 12px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px;width:200px">
          <button class="btn btn-ghost btn-sm" onclick="GraphTab.resetView()">重置视图</button>
        </div>
      </div>
      <div style="display:flex;gap:12px;font-size:11px;color:var(--text-dim);margin-bottom:8px">
        <span>🟢 概念</span><span>🟡 主题</span><span>🟣 内容支柱</span><span>🔵 源</span><span>🟠 视觉元素</span>
        <span>— 蓝色边 = prefers</span><span>— 红色边 = avoids</span>
        <span>粗细 = 权重</span>
      </div>
      <div id="cy-container" class="graph-container"></div>
      <div id="node-detail" style="margin-top:12px"></div>
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
  },

  initCytoscape(nodes, edges) {
    if (this.cy) this.cy.destroy();

    const colorMap = {
      concept: '#6b8fa3',
      visual_element: '#c97a46',
      pillar: '#9b6bcc',
      source: '#5a9eaa',
      mood: '#c9a946',
      color_node: '#c55a8a',
      brand: '#7a9e5a',
      object: '#8a8a8a',
      location: '#5a8a9e',
    };

    const elements = [
      ...nodes.map(n => ({
        data: {
          id: n.id,
          label: n.label,
          nodeType: n.type,
          ...n.properties,
        },
        classes: n.type,
      })),
      ...edges.map(e => ({
        data: {
          id: `${e.source}|${e.target}`,
          source: e.source,
          target: e.target,
          relation: e.relation,
          weight: e.weight,
          feedbackCount: e.feedback_count,
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
            'label': 'data(label)',
            'color': '#e0e0e0',
            'font-size': '10px',
            'text-valign': 'bottom',
            'text-halign': 'center',
            'text-margin-y': 6,
            'width': (ele) => 10 + (ele.data('weight') || 1) * 4,
            'height': (ele) => 10 + (ele.data('weight') || 1) * 4,
            'border-width': 1,
            'border-color': '#333',
          },
        },
        {
          selector: 'edge',
          style: {
            'width': (ele) => Math.max(1, Math.abs(ele.data('weight')) * 0.8),
            'line-color': (ele) => ele.data('weight') >= 0 ? '#4a7a9e' : '#9e4a4a',
            'target-arrow-color': (ele) => ele.data('weight') >= 0 ? '#4a7a9e' : '#9e4a4a',
            'target-arrow-shape': 'triangle',
            'arrow-scale': 0.8,
            'curve-style': 'bezier',
            'opacity': 0.6,
          },
        },
      ],
      layout: {
        name: 'cose',
        animate: false,
        nodeRepulsion: 8000,
        idealEdgeLength: 120,
        gravity: 0.3,
      },
    });

    this.cy.on('tap', 'node', (evt) => {
      const node = evt.target;
      this.showNodeDetail(node);
    });

    this.cy.on('tap', (evt) => {
      if (evt.target === this.cy) {
        document.getElementById('node-detail').innerHTML = '';
      }
    });
  },

  showNodeDetail(node) {
    const data = node.data();
    const connected = node.connectedEdges().length;
    document.getElementById('node-detail').innerHTML = `
      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">${this.esc(data.label)}</div>
            <div style="font-size:12px;color:var(--text-dim)">类型: ${data.nodeType} · ID: ${data.id}</div>
          </div>
          <button class="btn btn-ghost btn-sm" onclick="document.getElementById('node-detail').innerHTML=''">✕</button>
        </div>
        <div style="display:flex;gap:16px;font-size:13px;margin:8px 0">
          <span>关联边: <strong>${connected}</strong></span>
          <span>权重: <strong>${data.weight || 1}</strong></span>
        </div>
        ${data.description ? `<p style="font-size:13px;color:var(--text-muted)">${this.esc(data.description)}</p>` : ''}
      </div>`;
  },

  resetView() {
    if (this.cy) {
      this.cy.fit();
      this.cy.elements().style('opacity', 1);
      document.getElementById('graph-search').value = '';
    }
  },

  esc(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }
};
