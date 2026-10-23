/* Read-only data-ops view.
 *
 * - The only network call is a fixed GET to the snapshot endpoint.
 * - All values from the server are inserted with textContent; innerHTML
 *   is never used with server data.
 * - Freshness is always computed against the real current clock
 *   (Date.now()) at render time, so each refresh recomputes it.
 * - Timestamps without an explicit timezone are never guessed as UTC or
 *   browser-local time: they render as "时间未知". A future evidence time
 *   is an anomaly, not a healthy snapshot.
 * - A failed refresh keeps the last trusted view and its original
 *   evidence times; the very first failure renders "未知", never 0.
 */
(function () {
  'use strict';

  var SNAPSHOT_URL = '/api/v1/data-ops/snapshot';
  var STALE_MS = 24 * 60 * 60 * 1000;

  var SECTION_META = [
    { id: 'inventory', title: '库存 / 文件缺口' },
    { id: 'sources', title: '来源 / 追溯' },
    { id: 'updates', title: '更新 / 失败 / 备份' },
    { id: 'publication', title: '候选 / 发布进度' }
  ];

  // Fixed server-side enum vocabulary; anything not in this map renders
  // as "未知" so a hostile token can never be displayed verbatim.
  var ENUM_LABELS = {
    ok: '完整',
    mismatch: '不一致',
    failed: '失败',
    succeeded: '成功',
    running: '进行中',
    partial: '部分完成'
  };

  var lastView = null;
  var sectionsEl = document.getElementById('ops-sections');
  var bannerEl = document.getElementById('ops-banner');
  var assembledEl = document.getElementById('assembled-at');
  var refreshBtn = document.getElementById('refresh-btn');

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function parseTs(value) {
    if (typeof value !== 'string') { return null; }
    var text = value.trim();
    // Require an explicit timezone designator (Z or ±HH:MM / ±HHMM);
    // a naive timestamp must not be read in the browser local zone.
    var tzIso = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})$/;
    if (!tzIso.test(text)) { return null; }
    var ms = Date.parse(text);
    if (!isFinite(ms)) { return null; }
    return new Date(ms);
  }

  function freshness(asOf, nowMs) {
    var t = parseTs(asOf);
    if (t === null) {
      return { label: '时间未知', warn: true };
    }
    var delta = nowMs - t.getTime();
    if (delta < 0) {
      return { label: '证据时间异常：位于未来', warn: true };
    }
    if (delta > STALE_MS) {
      return { label: '旧快照：证据时间超过24小时', warn: true };
    }
    return { label: '证据时间有效', warn: false };
  }

  function displayValue(value) {
    if (value === null || value === undefined) { return '未知'; }
    if (typeof value === 'boolean') { return value ? '是' : '否'; }
    if (typeof value === 'string') {
      return Object.prototype.hasOwnProperty.call(ENUM_LABELS, value)
        ? ENUM_LABELS[value]
        : value;
    }
    return String(value);
  }

  function renderSkeleton(message) {
    assembledEl.textContent = '未知';
    sectionsEl.textContent = '';
    SECTION_META.forEach(function (meta) {
      var card = el('section', 'ops-card');
      card.appendChild(el('h2', 'card-title', meta.title));
      var asof = el('p', 'asof');
      asof.appendChild(el('span', null, '证据时间：未知'));
      var chip = el('span', 'chip warn', '时间未知');
      asof.appendChild(chip);
      card.appendChild(asof);
      var table = el('table');
      var tbody = el('tbody');
      var tr = el('tr');
      tr.appendChild(el('td', null, '数据状态'));
      tr.appendChild(el('td', 'value unknown', '未知'));
      tbody.appendChild(tr);
      table.appendChild(tbody);
      card.appendChild(table);
      sectionsEl.appendChild(card);
    });
    showBanner(message);
  }

  function showBanner(message) {
    bannerEl.textContent = message || '';
    if (message) {
      bannerEl.classList.add('show');
    } else {
      bannerEl.classList.remove('show');
    }
  }

  function markReadFailure() {
    var existing = bannerEl.textContent;
    var cards = sectionsEl.querySelectorAll('section.ops-card');
    Array.prototype.forEach.call(cards, function (card) {
      var asof = card.querySelector('.asof');
      if (asof && !asof.querySelector('.chip.fail')) {
        asof.appendChild(el('span', 'chip fail', '读取失败'));
      }
    });
    return existing;
  }

  function render(view) {
    sectionsEl.textContent = '';
    var assembled = view && typeof view.assembled_at === 'string'
      ? view.assembled_at
      : null;
    assembledEl.textContent = assembled || '未知';

    var byId = {};
    (view.sections || []).forEach(function (section) {
      byId[section.id] = section;
    });

    var nowMs = Date.now();
    SECTION_META.forEach(function (meta) {
      var section = byId[meta.id] || { items: [], as_of: null };
      var fresh = freshness(section.as_of, nowMs);

      var card = el('section', 'ops-card' + (fresh.warn ? ' stale' : ''));
      card.appendChild(el('h2', 'card-title', meta.title));

      var asof = el('p', 'asof');
      asof.appendChild(el('span', null, '证据时间：' + (section.as_of || '未知')));
      asof.appendChild(el('span', 'chip' + (fresh.warn ? ' warn' : ''), fresh.label));
      card.appendChild(asof);

      var table = el('table');
      var tbody = el('tbody');
      (section.items || []).forEach(function (item) {
        var tr = el('tr');
        tr.appendChild(el('td', null, item.label));
        var shown = displayValue(item.value);
        tr.appendChild(
          el('td', 'value' + (item.value === null || item.value === undefined ? ' unknown' : ''), shown)
        );
        tr.appendChild(el('td', 'note', item.note || ''));
        tbody.appendChild(tr);
      });
      if (!section.items || !section.items.length) {
        var tr = el('tr');
        tr.appendChild(el('td', null, '数据状态'));
        tr.appendChild(el('td', 'value unknown', '未知'));
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      card.appendChild(table);
      sectionsEl.appendChild(card);
    });
  }

  function load() {
    refreshBtn.disabled = true;
    fetch(SNAPSHOT_URL, { method: 'GET', cache: 'no-store' })
      .then(function (resp) {
        if (!resp.ok) {
          throw new Error('snapshot unavailable: ' + resp.status);
        }
        return resp.json();
      })
      .then(function (view) {
        lastView = view;
        render(view);
        showBanner('');
      })
      .catch(function () {
        if (lastView) {
          // Re-render so freshness is recomputed against the current
          // clock; the evidence-time strings stay from the trusted view.
          render(lastView);
          markReadFailure();
          showBanner('读取失败：保留上次可信视图，时间仍为原证据时间。');
        } else {
          renderSkeleton('读取失败：快照暂不可用，以下数值均为未知（不是 0）。');
        }
      })
      .then(function () {
        refreshBtn.disabled = false;
      });
  }

  refreshBtn.addEventListener('click', load);
  renderSkeleton('正在读取只读快照……');
  load();
})();
