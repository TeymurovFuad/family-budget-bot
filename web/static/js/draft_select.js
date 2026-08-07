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

  function selectedBoxes() {
    return Array.prototype.slice.call(document.querySelectorAll('.draft-row-cb:checked'));
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
    if (byId('draft-preview-ai-btn')) byId('draft-preview-ai-btn').disabled = !enabled;
    if (byId('draft-apply-preview-btn')) byId('draft-apply-preview-btn').disabled = !enabled;
    if (byId('draft-clear-preview-btn')) byId('draft-clear-preview-btn').disabled = !enabled;

    var field = byId('draft-bulk-field');
    var value = byId('draft-bulk-value');
    byId('draft-apply-btn').disabled = !enabled || !field || !value || !value.value;
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

  document.addEventListener('change', function(e) {
    if (e.target.classList.contains('draft-row-cb')) {
      updateBulkBar();
      return;
    }
    if (e.target.id === 'draft-select-all') {
      var on = e.target.checked;
      document.querySelectorAll('.draft-row-cb').forEach(function(cb) {
        cb.checked = on;
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
      }
      populateValues();
      return;
    }
    if (e.target.id === 'draft-bulk-value') {
      updateBulkBar();
    }
  });

  if (byId('draft-bulk-field')) {
    refData = parseRefData();
    document.querySelectorAll('.draft-type-select').forEach(function(sel) {
      var idx = sel.getAttribute('data-row-idx');
      if (idx !== null) {
        syncRowCategoryForType(idx);
      }
    });
    populateValues();
    updateBulkBar();
  }
})();
