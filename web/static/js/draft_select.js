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
  // Replaces type="submit" button values, which iOS Safari can silently drop.
  var bulkFormRef = null; // assigned after DOM ready below
  function submitBulkAction(actionValue) {
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
})();
