(function() {
  'use strict';

  var selectedIds = new Map(); // id -> lock_token

  function getBar()      { return document.getElementById('bulk-bar'); }
  function getCount()    { return document.getElementById('bulk-count'); }
  function getEditBtn()  { return document.getElementById('bulk-edit-btn'); }
  function getDeleteBtn(){ return document.getElementById('bulk-delete-btn'); }
  function getSelectAll(){ return document.getElementById('select-all-cb'); }

  function updateBar() {
    var n = selectedIds.size;
    var bar = getBar(); if (!bar) return;
    bar.hidden = n === 0;
    getCount().textContent = n + ' selected';
    var dis = n === 0;
    getEditBtn().disabled = dis;
    getDeleteBtn().disabled = dis;
    var all = getSelectAll(); if (!all) return;
    var boxes = document.querySelectorAll('.txn-checkbox');
    var checked = Array.prototype.filter.call(boxes, function(b) { return b.checked; }).length;
    all.indeterminate = checked > 0 && checked < boxes.length;
    all.checked = boxes.length > 0 && checked === boxes.length;
  }

  function clearSelection() {
    selectedIds.clear();
    document.querySelectorAll('.txn-checkbox').forEach(function(b) { b.checked = false; });
    updateBar();
  }

  // Delegated checkbox listener — survives HTMX swaps.
  document.addEventListener('change', function(e) {
    if (e.target.classList.contains('txn-checkbox')) {
      var id = e.target.dataset.id;
      var lock = e.target.dataset.lock;
      if (e.target.checked) selectedIds.set(id, lock);
      else selectedIds.delete(id);
      updateBar();
    }
    if (e.target.id === 'select-all-cb') {
      document.querySelectorAll('.txn-checkbox').forEach(function(b) {
        b.checked = e.target.checked;
        if (e.target.checked) selectedIds.set(b.dataset.id, b.dataset.lock);
        else selectedIds.delete(b.dataset.id);
      });
      updateBar();
    }
  });

  // Reset selection when the list fragment is swapped (pagination, filter).
  document.addEventListener('htmx:afterSwap', function(e) {
    if (e.target && e.target.id === 'txn-list') {
      selectedIds.clear();
      updateBar();
    }
  });

  // Bulk delete — open the confirmation modal.
  document.addEventListener('click', function(e) {
    if (e.target.id === 'bulk-delete-btn' && !e.target.disabled) {
      var pairs = [];
      selectedIds.forEach(function(tok, id) {
        pairs.push('ids[]=' + encodeURIComponent(id) + '&lock_tokens[]=' + encodeURIComponent(tok));
      });
      htmx.ajax('GET', '/transactions/bulk-confirm?' + pairs.join('&'), {
        target: '#modal-slot', swap: 'innerHTML'
      });
    }

    if (e.target.id === 'bulk-edit-btn' && !e.target.disabled) {
      var tpl = document.getElementById('bulk-edit-tpl');
      var modal = tpl.content.cloneNode(true);
      var slot = document.getElementById('modal-slot');
      slot.innerHTML = '';
      slot.appendChild(modal);

      // Open the dialog.
      var dlg = document.getElementById('bulk-edit-modal');
      if (dlg && typeof dlg.showModal === 'function') { dlg.showModal(); }

      // Populate hidden id/lock_token fields.
      var hidden = document.getElementById('bulk-edit-hidden-fields');
      selectedIds.forEach(function(tok, id) {
        var inp1 = document.createElement('input');
        inp1.type = 'hidden'; inp1.name = 'ids[]'; inp1.value = id;
        var inp2 = document.createElement('input');
        inp2.type = 'hidden'; inp2.name = 'lock_tokens[]'; inp2.value = tok;
        hidden.appendChild(inp1); hidden.appendChild(inp2);
      });
      document.getElementById('bulk-edit-count').textContent = selectedIds.size;

      // Wire the field picker to populate the value select.
      var fieldSel = document.getElementById('bulk-field-select');
      var valSel = document.getElementById('bulk-value-select');
      var submitBtn = document.getElementById('bulk-edit-submit');
      var refData = null;
      try {
        refData = JSON.parse(document.getElementById('txn-ref-data').textContent);
      } catch(_) {}

      function populateValues() {
        var field = fieldSel.value;
        var opts = (refData && (
          field === 'category' ? refData.categories :
          field === 'person'   ? refData.persons :
          field === 'type'     ? refData.txn_types : []
        )) || [];
        valSel.innerHTML = '<option value="">— choose a value —</option>' +
          opts.map(function(o) { return '<option value="' + o + '">' + o + '</option>'; }).join('');
        valSel.disabled = opts.length === 0;
        submitBtn.disabled = true;
      }
      populateValues();
      fieldSel.addEventListener('change', populateValues);
      valSel.addEventListener('change', function() {
        submitBtn.disabled = valSel.value === '';
      });

      // Close modal and clear selection after bulk-edit submits.
      document.getElementById('bulk-edit-form').addEventListener('htmx:afterRequest', function() {
        var d = document.getElementById('bulk-edit-modal');
        if (d && typeof d.close === 'function') { d.close(); }
        document.getElementById('modal-slot').innerHTML = '';
        clearSelection();
      });

      htmx.process(slot);
    }
  });

  // Close bulk-delete confirm modal and clear selection after delete.
  document.addEventListener('htmx:afterRequest', function(e) {
    if (e.target && e.target.id === 'bulk-delete-form') {
      var d = document.getElementById('bulk-confirm-modal');
      if (d && typeof d.close === 'function') { d.close(); }
      document.getElementById('modal-slot').innerHTML = '';
      clearSelection();
    }
  });

})();
