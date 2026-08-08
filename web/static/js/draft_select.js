(function() {
  'use strict';

  function byId(id) { return document.getElementById(id); }

  var refData = {};

  function parseRefData() {
    var dataNode = byId('draft-ref-data');
    if (!dataNode) return {};
    try {
      return JSON.parse(dataNode.textContent || '{}');
    } catch (_) {
      return {};
    }
  }

  function categoryOptionsForType(typeValue) {
    var byType = refData.category_by_type || {};
    var options = byType[typeValue] || [];
    return Array.isArray(options) ? options : [];
  }

  function setSelectOptions(select, options, placeholderText) {
    if (!select) return;
    var current = String(select.value || '');
    while (select.firstChild) {
      select.removeChild(select.firstChild);
    }
    if (placeholderText) {
      var placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = placeholderText;
      select.appendChild(placeholder);
    }
    options.forEach(function(v) {
      var opt = document.createElement('option');
      opt.value = String(v);
      opt.textContent = String(v);
      if (String(v) === current) {
        opt.selected = true;
      }
      select.appendChild(opt);
    });
    if (select.options.length > 0 && select.selectedIndex < 0) {
      select.selectedIndex = 0;
    }
  }

  function syncRowCategoryForType(rowIdx) {
    var typeSelect = document.querySelector('.draft-type-select[data-row-idx="' + rowIdx + '"]');
    var categorySelect = document.querySelector('.draft-category-select[data-row-idx="' + rowIdx + '"]');
    if (!typeSelect || !categorySelect) return;
    var allowed = categoryOptionsForType(String(typeSelect.value || ''));
    if (!allowed.length) {
      allowed = refData.category || [];
    }
    setSelectOptions(categorySelect, allowed, 'Choose category');
    categorySelect.disabled = allowed.length === 0;
  }

  // submitBulkAction — sets the hidden action field and submits the bulk form.
  // For preview_ai: intercepts and uses SSE stream instead of a full page POST.
  // Replaces type="submit" button values, which iOS Safari can silently drop.
  var bulkFormRef = null; // assigned after DOM ready below
  function submitBulkAction(actionValue) {
    if (actionValue === 'preview_ai') {
      startReanalyzeStream();
      return;
    }
    var form = bulkFormRef || document.getElementById('draft-bulk-form');
    if (!form) return;
    var hidden = document.getElementById('draft-action-input');
    if (hidden) hidden.value = actionValue;
    appendSelectedToActionUrl(form);
    form.submit();
  }
  // Expose globally so onclick="submitBulkAction(...)" in the template works.
  window.submitBulkAction = submitBulkAction;

  // Sync all checkboxes that share the same row_idx value (summary + pick cells).
  function syncCheckboxPair(value, checked) {
    document.querySelectorAll('.draft-row-cb[value="' + value + '"]').forEach(function(cb) {
      cb.checked = checked;
    });
  }

  // selectedBoxes — returns one representative checkbox per row (dedup by value).
  function selectedBoxes() {
    var seen = {};
    return Array.prototype.slice.call(document.querySelectorAll('.draft-row-cb:checked')).filter(function(cb) {
      var v = cb.value;
      if (seen[v]) return false;
      seen[v] = true;
      return true;
    });
  }

  function selectedRowTypes() {
    var types = new Set();
    selectedBoxes().forEach(function(cb) {
      var idx = cb.value;
      var typeSelect = document.querySelector('.draft-type-select[data-row-idx="' + idx + '"]');
      if (!typeSelect) return;
      var val = String(typeSelect.value || '').trim();
      if (val) types.add(val);
    });
    return types;
  }

  var REANALYZE_MAX_ROWS = 20;

  function updateBulkBar() {
    var boxes = document.querySelectorAll('.draft-row-cb');
    var count = selectedBoxes().length;
    var bar = byId('draft-bulk-bar');
    if (!bar) return;

    byId('draft-selected-count').textContent = count + ' selected';

    var all = byId('draft-select-all');
    if (all) {
      var total = boxes.length;
      all.checked = total > 0 && count === total;
      all.indeterminate = count > 0 && count < total;
      all.disabled = total === 0;
    }

    var enabled = count > 0;
    byId('draft-drop-btn').disabled = !enabled;
    byId('draft-restore-btn').disabled = !enabled;

    // AI re-analyze button — enabled whenever any rows are selected (no row cap; server batches by 20)
    var previewBtn = byId('draft-preview-ai-btn');
    if (previewBtn) {
      previewBtn.disabled = !enabled;
      previewBtn.title = '';
    }
    var aiCounter = byId('draft-ai-row-counter');
    if (aiCounter) {
      aiCounter.textContent = count + ' row' + (count === 1 ? '' : 's') + ' selected';
    }

    // #6 — Apply AI suggestion gating: only enable if at least one selected row has ai-changed
    var applyPreviewBtn = byId('draft-apply-preview-btn');
    if (applyPreviewBtn) {
      var hasAiChanged = selectedBoxes().some(function(cb) {
        var row = cb.closest('tr') || cb.closest('.draft-row');
        return row && row.classList.contains('draft-row--ai-changed');
      });
      applyPreviewBtn.disabled = !enabled || !hasAiChanged;
    }

    if (byId('draft-clear-preview-btn')) byId('draft-clear-preview-btn').disabled = !enabled;

    // "Save all valid" acts on all valid rows — always enabled regardless of selection
    // (no-op: button is enabled by default and we intentionally do not disable it here)

    // #2 — Mixed-type inline warning for category field
    var field = byId('draft-bulk-field');
    var value = byId('draft-bulk-value');
    var mixedWarning = byId('draft-mixed-type-warning');
    if (field && field.value === 'category') {
      var types = selectedRowTypes();
      if (mixedWarning) {
        mixedWarning.style.display = types.size > 1 ? '' : 'none';
      }
    } else {
      if (mixedWarning) mixedWarning.style.display = 'none';
    }

    byId('draft-apply-btn').disabled = !enabled || !field || !value || !value.value;
  }

  function selectedIndices() {
    return selectedBoxes().map(function(cb) { return cb.value; });
  }

  function appendSelectedToActionUrl(form) {
    var indices = selectedIndices();
    var base = form.getAttribute('action') || '';
    // Strip any existing ?selected= param
    base = base.replace(/([?&])selected=[^&]*/g, '').replace(/[?&]$/, '');
    if (indices.length > 0) {
      var sep = base.indexOf('?') >= 0 ? '&' : '?';
      form.setAttribute('action', base + sep + 'selected=' + indices.join(','));
    } else {
      form.setAttribute('action', base);
    }
  }

  function restoreSelectionsFromUrl() {
    var search = window.location.search;
    var match = search.match(/[?&]selected=([^&]*)/);
    if (!match) return;
    var raw = match[1];
    if (!raw) return;
    var parts = raw.split(',');
    parts.forEach(function(part) {
      var idx = part.trim();
      syncCheckboxPair(idx, true);
    });
    updateBulkBar();
  }

  function populateValues() {
    var field = byId('draft-bulk-field');
    var value = byId('draft-bulk-value');
    if (!field || !value) return;

    var options = refData[field.value] || [];
    if (field.value === 'category') {
      var types = selectedRowTypes();
      if (types.size === 1) {
        var onlyType = Array.from(types)[0];
        options = categoryOptionsForType(onlyType);
      } else if (types.size > 1) {
        options = [];
      }
    }

    var placeholder = 'Choose value';
    if (field.value === 'category' && selectedRowTypes().size > 1) {
      placeholder = 'Select rows with one type';
    }
    setSelectOptions(value, options, placeholder);
    value.disabled = options.length === 0;
    updateBulkBar();
  }

  // #16 — client-side invalid highlight when type/category changes
  function updateRowInvalidClass(rowIdx) {
    var typeSelect = document.querySelector('.draft-type-select[data-row-idx="' + rowIdx + '"]');
    var categorySelect = document.querySelector('.draft-category-select[data-row-idx="' + rowIdx + '"]');
    var row = document.querySelector('.draft-row[data-row-idx="' + rowIdx + '"]');
    if (!typeSelect || !categorySelect || !row) return;
    var allowed = categoryOptionsForType(String(typeSelect.value || ''));
    if (!allowed.length) {
      row.classList.remove('draft-row--invalid');
      return;
    }
    var cat = String(categorySelect.value || '');
    if (cat && allowed.indexOf(cat) === -1) {
      row.classList.add('draft-row--invalid');
    } else {
      row.classList.remove('draft-row--invalid');
    }
  }

  document.addEventListener('change', function(e) {
    if (e.target.classList.contains('draft-row-cb')) {
      // Sync all checkboxes for the same row (summary + pick cells share the same value).
      syncCheckboxPair(e.target.value, e.target.checked);
      updateBulkBar();
      return;
    }
    if (e.target.id === 'draft-select-all') {
      var on = e.target.checked;
      // Check only the first checkbox per value to avoid double-counting, then sync.
      var seen = {};
      document.querySelectorAll('.draft-row-cb').forEach(function(cb) {
        if (!seen[cb.value]) {
          seen[cb.value] = true;
          cb.checked = on;
          syncCheckboxPair(cb.value, on);
        }
      });
      updateBulkBar();
      return;
    }
    if (e.target.id === 'draft-bulk-field') {
      populateValues();
      return;
    }
    if (e.target.classList.contains('draft-type-select')) {
      var idx = e.target.getAttribute('data-row-idx');
      if (idx !== null) {
        syncRowCategoryForType(idx);
        updateRowInvalidClass(idx);
      }
      populateValues();
      return;
    }
    if (e.target.classList.contains('draft-category-select')) {
      var idx = e.target.getAttribute('data-row-idx');
      if (idx !== null) {
        updateRowInvalidClass(idx);
      }
      return;
    }
    if (e.target.id === 'draft-bulk-value') {
      updateBulkBar();
    }
  });

  // #9 — AI preview collapsible row toggle
  document.addEventListener('click', function(e) {
    if (!e.target.classList.contains('draft-preview-toggle')) return;
    var targetId = e.target.getAttribute('data-target');
    if (!targetId) return;
    var detailRow = document.getElementById(targetId);
    if (!detailRow) return;
    var expanded = e.target.getAttribute('aria-expanded') === 'true';
    if (expanded) {
      detailRow.hidden = true;
      e.target.setAttribute('aria-expanded', 'false');
      e.target.textContent = '▾ Details';
    } else {
      detailRow.hidden = false;
      e.target.setAttribute('aria-expanded', 'true');
      e.target.textContent = '▴ Hide';
    }
  });

  if (byId('draft-bulk-field')) {
    // #7 — load refData first, then populate values so the category
    // dropdown is filled on initial render without requiring a field change.
    refData = parseRefData();
    document.querySelectorAll('.draft-type-select').forEach(function(sel) {
      var idx = sel.getAttribute('data-row-idx');
      if (idx !== null) {
        syncRowCategoryForType(idx);
      }
    });
    populateValues();
    updateBulkBar();
    restoreSelectionsFromUrl();
  }

  // Single-row forms: append ?selected= so server preserves selection state
  document.querySelectorAll('.draft-row-single-form').forEach(function(form) {
    form.addEventListener('submit', function() {
      appendSelectedToActionUrl(form);
    });
  });

  // Collapsed rows — tap/click summary bar to expand/collapse on any screen size.
  // Rows default to EXPANDED (CSS default, no class needed) — safe for no-JS.
  // An inline script after the table immediately collapses mobile rows before first paint.
  // This JS only handles the toggle and reactive breakpoint crossing.

  var mobileQuery = window.matchMedia('(max-width: 47.99rem)');

  function collapseAll() {
    document.querySelectorAll('.draft-row').forEach(function(row) {
      row.classList.add('draft-row--collapsed');
    });
  }

  function expandAll() {
    document.querySelectorAll('.draft-row').forEach(function(row) {
      row.classList.remove('draft-row--collapsed');
    });
  }

  // Reactive: crossing the breakpoint resets all rows to the new default.
  mobileQuery.addEventListener('change', function(e) {
    if (e.matches) { collapseAll(); } else { expandAll(); }
  });

  document.querySelectorAll('.draft-row-summary-toggle').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var row = btn.closest('.draft-row');
      if (!row) return;
      row.classList.toggle('draft-row--collapsed');
    });
  });

  // Persist checkbox selections into the form action URL on submit.
  // Also used by submitBulkAction() above.
  var bulkForm = byId('draft-bulk-form');
  bulkFormRef = bulkForm;
  if (bulkForm) {
    bulkForm.addEventListener('submit', function() {
      appendSelectedToActionUrl(bulkForm);
    });
  }

  // ── SSE re-analyze stream ────────────────────────────────────────────────────
  // Tracks the open EventSource so a second click closes the first stream before
  // opening a new one — prevents concurrent save_user_draft races (Tester #5).
  var _activeStream = null;

  // Map SSE status → text shown inside the status cell (expanded row view).
  function _streamBadgeText(status) {
    switch (status) {
      case 'pending':   return '⏳ Pending';
      case 'analyzing': return '🔄 Analysing…';
      case 'changed':   return '✏️ AI changed';
      case 'unchanged': return '✓ No change';
      case 'error':     return '❌ Failed';
      case 'timeout':   return '⏱ Timed out';
      case 'skipped':   return '— Skipped';
      default:          return status;
    }
  }

  // Map SSE status → CSS modifier for the collapsed summary status span.
  function _streamSummaryClass(status) {
    switch (status) {
      case 'pending':   return 'draft-summary-status--pending';
      case 'analyzing': return 'draft-summary-status--analyzing';
      case 'changed':   return 'draft-summary-status--ai';
      case 'error':
      case 'timeout':   return 'draft-summary-status--error';
      default:          return '';
    }
  }

  // Map SSE status → text in the collapsed summary bar.
  function _streamSummaryText(status, reason) {
    switch (status) {
      case 'pending':   return '⏳ Pending';
      case 'analyzing': return '🔄 Analysing…';
      case 'changed':   return '✏️ AI ready';
      case 'unchanged': return '✓ No change';
      case 'error':     return '❌ ' + (reason || 'Failed');
      case 'timeout':   return '⏱ Timed out';
      case 'skipped':   return '— Skipped';
      default:          return status;
    }
  }

  // Remove AI badge elements from a status cell before injecting stream badges.
  // Server-rendered .draft-preview-reason--inline (the pre-existing AI reason)
  // is NOT removed here — only stream-injected .draft-stream-reason--inline is
  // cleared. This means a failed/disconnected stream leaves prior reason text
  // intact until the next full page load (Reviewer #1).
  function _clearAiBadges(statusCell) {
    ['.draft-preview-badge', '.draft-preview-toggle', '.draft-stream-reason--inline', '.draft-stream-badge']
      .forEach(function(sel) {
        statusCell.querySelectorAll(sel).forEach(function(el) { el.remove(); });
      });
  }

  // Apply a stream status to a single row: update classes, status cell, summary bar.
  // data = full result payload (for 'changed' status, includes proposed/changed_fields).
  function _setRowStreamStatus(idx, status, reason, data) {
    var row = document.querySelector('.draft-row[data-row-idx="' + idx + '"]');
    if (!row) return;

    // Row-level highlight classes (used by updateBulkBar to gate Apply AI button).
    row.classList.remove('draft-row--ai-changed', 'draft-row--ai-error');
    if (status === 'changed') row.classList.add('draft-row--ai-changed');
    if (status === 'error' || status === 'timeout') row.classList.add('draft-row--ai-error');

    // ── Status cell (expanded view) ──────────────────────────────────────────
    var statusCell = row.querySelector('.draft-cell--status');
    if (statusCell) {
      _clearAiBadges(statusCell);

      var badge = document.createElement('span');
      badge.className = 'draft-stream-badge draft-stream-badge--' + status;
      badge.textContent = _streamBadgeText(status);

      // Show reason inline for error/timeout states.
      // Uses draft-stream-reason--inline (not draft-preview-reason--inline) so
      // _clearAiBadges only removes stream-injected reasons, not server-rendered ones.
      if (reason && (status === 'error' || status === 'timeout')) {
        var rs = document.createElement('span');
        rs.className = 'draft-preview-reason draft-stream-reason--inline';
        rs.textContent = reason;
        statusCell.insertBefore(rs, statusCell.firstChild);
      }
      statusCell.insertBefore(badge, statusCell.firstChild);
    }

    // ── Summary bar (collapsed view) ────────────────────────────────────────
    var summaryStatus = row.querySelector('.draft-summary-status');
    if (summaryStatus) {
      summaryStatus.className = 'draft-summary-status ' + _streamSummaryClass(status);
      summaryStatus.textContent = _streamSummaryText(status, reason);
    }

    // ── Per-row Apply AI button ──────────────────────────────────────────────
    // Dynamically inject / remove the per-row Apply AI form so the user can
    // apply changes row-by-row without a page reload (server already saved the
    // _ai_preview via SSE, so the POST endpoint will find it).
    var userId = bulkForm ? bulkForm.getAttribute('data-user-id') : null;
    var actionsDiv = row.querySelector('.draft-row-actions');
    if (actionsDiv) {
      var existingApply = actionsDiv.querySelector('.draft-row-apply-ai-form');
      if (existingApply) existingApply.remove();

      if (status === 'changed' && userId) {
        var applyForm = document.createElement('form');
        applyForm.method = 'post';
        applyForm.action = '/drafts/' + userId + '/row/' + idx + '/apply-ai-preview';
        applyForm.className = 'draft-row-single-form draft-row-apply-ai-form';
        var applyBtn = document.createElement('button');
        applyBtn.type = 'submit';
        applyBtn.className = 'btn btn--sm btn--accent';
        applyBtn.textContent = '✓ Apply AI';
        applyBtn.setAttribute('aria-label', 'Apply AI changes');
        applyForm.appendChild(applyBtn);
        actionsDiv.appendChild(applyForm);
        // Register ?selected= appender so server preserves selection state.
        applyForm.addEventListener('submit', function() {
          appendSelectedToActionUrl(applyForm);
        });
      }
    }
  }

  // Main SSE function — called by submitBulkAction('preview_ai').
  function startReanalyzeStream() {
    // Always close any prior stream first — even if we return early below.
    // This prevents a stale _activeStream from persisting across calls
    // that hit an early-return guard (Reviewer #3).
    if (_activeStream) {
      _activeStream.close();
      _activeStream = null;
    }

    var form = bulkFormRef || byId('draft-bulk-form');
    if (!form) return;
    var userId = form.getAttribute('data-user-id');
    if (!userId) return;

    var idxs = selectedIndices();
    if (!idxs.length) return;

    var instruction = (byId('draft-ai-instruction') || {}).value || '';

    // Build SSE URL with all selected row indices and the instruction.
    var params = idxs.map(function(i) { return 'row_idx=' + encodeURIComponent(i); });
    if (instruction) params.push('ai_instruction=' + encodeURIComponent(instruction));
    var url = '/drafts/' + encodeURIComponent(userId) + '/reanalyze-stream?' + params.join('&');

    var total = idxs.length;
    var doneCount = 0;

    // Set every selected row to ⏳ pending (clears stale badges from prior run).
    idxs.forEach(function(idx) { _setRowStreamStatus(idx, 'pending', '', null); });

    // Lock UI.
    var previewBtn = byId('draft-preview-ai-btn');
    if (previewBtn) {
      previewBtn.disabled = true;
      previewBtn.textContent = '⏳ Analysing…';
    }
    var counter = byId('draft-ai-row-counter');
    // Silence aria-live during high-frequency stream updates to avoid flooding
    // screen readers (Designer #6a). Flip back to polite at stream end.
    if (counter) {
      counter.setAttribute('aria-live', 'off');
      counter.textContent = 'Analysing… 0 / ' + total;
    }

    var es = new EventSource(url);
    _activeStream = es;

    es.addEventListener('analyzing', function(e) {
      try {
        var data = JSON.parse(e.data);
        _setRowStreamStatus(data.idx, 'analyzing', '', null);
      } catch (_) {}
    });

    es.addEventListener('result', function(e) {
      try {
        var data = JSON.parse(e.data);
        doneCount++;
        _setRowStreamStatus(data.idx, data.status, data.reason || '', data);
        if (counter) counter.textContent = 'Analysing… ' + doneCount + ' / ' + total;
        // Re-evaluate Apply AI / Clear button states as rows complete.
        updateBulkBar();
      } catch (_) {}
    });

    es.addEventListener('done', function(e) {
      es.close();
      _activeStream = null;
      _onStreamFinished(previewBtn, counter, total, e.data);
    });

    // Server-sent error event (e.g. draft not found).
    es.addEventListener('error', function(e) {
      if (e.data) {
        try {
          var msg = JSON.parse(e.data).message || 'AI analysis error.';
          if (counter) counter.textContent = msg;
        } catch (_) {
          if (counter) counter.textContent = 'AI analysis error.';
        }
      }
      es.close();
      _activeStream = null;
      _onStreamError(idxs, previewBtn, counter);
    });

    // Network / connection error (EventSource built-in onerror).
    es.onerror = function() {
      if (es.readyState === EventSource.CLOSED) return;
      es.close();
      _activeStream = null;
      _onStreamError(idxs, previewBtn, counter);
    };
  }

  function _onStreamFinished(previewBtn, counter, total, rawData) {
    if (previewBtn) {
      previewBtn.disabled = false;
      previewBtn.textContent = '🔍 Re-analyze';
    }
    var summary = 'Done — ' + total + ' rows';
    try {
      var d = JSON.parse(rawData);
      var parts = [];
      if (d.changed)   parts.push(d.changed   + ' changed');
      if (d.unchanged) parts.push(d.unchanged  + ' unchanged');
      if (d.failed)    parts.push(d.failed     + ' failed');
      if (d.timed_out) parts.push(d.timed_out  + ' timed out');
      if (d.skipped)   parts.push(d.skipped    + ' skipped');
      if (parts.length) summary = 'Done — ' + parts.join(' · ');
    } catch (_) {}
    if (counter) {
      // Re-enable aria-live now that the stream is done — screen reader announces
      // the final summary once (Designer #6a).
      counter.setAttribute('aria-live', 'polite');
      counter.setAttribute('aria-atomic', 'true');
      counter.textContent = summary;
      // Fade out after 6s, then reset to selection count.
      setTimeout(function() {
        counter.classList.add('draft-ai-counter--fading');
        setTimeout(function() {
          counter.classList.remove('draft-ai-counter--fading');
          counter.setAttribute('aria-live', 'off');
          counter.removeAttribute('aria-atomic');
          var n = selectedIndices().length;
          counter.textContent = n + ' row' + (n === 1 ? '' : 's') + ' selected';
        }, 800); // match CSS fade duration
      }, 6000);
    }
    updateBulkBar();
  }

  function _onStreamError(idxs, previewBtn, counter) {
    // Un-stick any rows still showing ⏳/🔄 — they were never completed.
    idxs.forEach(function(idx) {
      var row = document.querySelector('.draft-row[data-row-idx="' + idx + '"]');
      if (!row) return;
      var badge = row.querySelector('.draft-stream-badge--pending, .draft-stream-badge--analyzing');
      if (badge) badge.remove();
      var s = row.querySelector('.draft-summary-status');
      if (s && (s.classList.contains('draft-summary-status--pending') || s.classList.contains('draft-summary-status--analyzing'))) {
        s.className = 'draft-summary-status';
        s.textContent = '';
      }
    });
    if (previewBtn) {
      previewBtn.disabled = false;
      previewBtn.textContent = '🔍 Re-analyze';
    }
    if (counter) counter.textContent = 'Connection lost — please try again.';
    updateBulkBar();
  }

})();
