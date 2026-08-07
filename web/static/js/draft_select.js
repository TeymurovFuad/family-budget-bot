(function() {
  'use strict';

  function byId(id) { return document.getElementById(id); }

  function selectedBoxes() {
    return Array.prototype.slice.call(document.querySelectorAll('.draft-row-cb:checked'));
  }

  function updateBulkBar() {
    var boxes = document.querySelectorAll('.draft-row-cb');
    var count = selectedBoxes().length;
    var bar = byId('draft-bulk-bar');
    if (!bar) return;

    bar.hidden = count === 0;
    byId('draft-selected-count').textContent = count + ' selected';

    var all = byId('draft-select-all');
    if (all) {
      var total = boxes.length;
      all.checked = total > 0 && count === total;
      all.indeterminate = count > 0 && count < total;
    }

    var enabled = count > 0;
    byId('draft-drop-btn').disabled = !enabled;
    byId('draft-restore-btn').disabled = !enabled;

    var field = byId('draft-bulk-field');
    var value = byId('draft-bulk-value');
    byId('draft-apply-btn').disabled = !enabled || !field || !value || !value.value;
  }

  function populateValues() {
    var field = byId('draft-bulk-field');
    var value = byId('draft-bulk-value');
    var dataNode = byId('draft-ref-data');
    if (!field || !value || !dataNode) return;

    var ref = {};
    try {
      ref = JSON.parse(dataNode.textContent || '{}');
    } catch (_) {
      ref = {};
    }

    var options = ref[field.value] || [];
    while (value.firstChild) {
      value.removeChild(value.firstChild);
    }
    var placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Choose value';
    value.appendChild(placeholder);
    options.forEach(function(v) {
      var opt = document.createElement('option');
      opt.value = String(v);
      opt.textContent = String(v);
      value.appendChild(opt);
    });
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
    if (e.target.id === 'draft-bulk-value') {
      updateBulkBar();
    }
  });

  if (byId('draft-bulk-field')) {
    populateValues();
    updateBulkBar();
  }
})();
