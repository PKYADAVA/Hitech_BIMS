// Applied to every DataTable on the site as soon as this script runs (i.e.
// before any page's own $(document).ready() handler calls .DataTable()),
// since defaults must be set before initialization, not inside a ready
// callback of our own - ready handlers fire in registration order, and
// individual pages register theirs earlier in the document than this file.
$.extend(true, $.fn.dataTable.defaults, {
  dom: "Blfrtip",
  buttons: [
    { extend: "copyHtml5", exportOptions: { columns: "th:not(:last-child)" } },
    { extend: "csvHtml5", exportOptions: { columns: "th:not(:last-child)" } },
    { extend: "excelHtml5", exportOptions: { columns: "th:not(:last-child)" } },
    { extend: "pdfHtml5", exportOptions: { columns: "th:not(:last-child)" }, orientation: "landscape" },
    { extend: "print", exportOptions: { columns: "th:not(:last-child)" } },
    "colvis",
  ],
});

// ---------------------------------------------------------------------------
// Global searchable dropdowns: every select.form-select on the site becomes a
// searchable Select2 (Bootstrap 5 theme), including selects added to the DOM
// later (dynamic table rows, generated modals). Opt out with data-no-search.
// ---------------------------------------------------------------------------
(function ($) {
  function searchableSelect(el) {
    const $el = $(el);
    if (!$el.is('select.form-select') || el.multiple || el.size > 1) return;
    if ($el.is('[data-no-search]') || $el.hasClass('select2-hidden-accessible')) return;
    if ($el.closest('.dataTables_length').length) return; // keep DataTables' page-size menu native
    const small = $el.hasClass('form-select-sm');
    const $modal = $el.closest('.modal');
    $el.select2({
      theme: 'bootstrap-5',
      width: el.style.width ? 'style' : '100%',
      selectionCssClass: small ? 'select2--small' : '',
      dropdownCssClass: small ? 'select2--small' : '',
      dropdownParent: $modal.length ? $modal : $(document.body),
    });
    // Select2 raises only jQuery events; re-dispatch native input/change so
    // vanilla listeners (onchange=..., addEventListener) keep working.
    $el.on('select2:select select2:unselect select2:clear', function () {
      this.dispatchEvent(new Event('input', { bubbles: true }));
      this.dispatchEvent(new Event('change', { bubbles: true }));
    });
    // Pages show/hide the native select (d-none, .hide()); the rendered
    // Select2 box must follow, or hidden selects appear as duplicate boxes.
    const container = $el.next('.select2-container');
    const syncVisibility = function () {
      container.toggleClass('d-none',
        el.classList.contains('d-none') || el.style.display === 'none');
    };
    syncVisibility();
    new MutationObserver(syncVisibility)
      .observe(el, { attributes: true, attributeFilter: ['class', 'style'] });
  }
  window.searchableSelect = searchableSelect;

  // Keep the rendered Select2 in sync when code assigns values directly —
  // el.value = x, $el.val(x), form.reset() — none of which fire 'change'.
  // 'change.select2' updates Select2's display without running app handlers.
  const nativeValue = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
  Object.defineProperty(HTMLSelectElement.prototype, 'value', {
    configurable: true,
    get: nativeValue.get,
    set: function (v) {
      nativeValue.set.call(this, v);
      if (this.classList.contains('select2-hidden-accessible')) $(this).trigger('change.select2');
    },
  });
  const jqueryVal = $.fn.val;
  $.fn.val = function () {
    const result = jqueryVal.apply(this, arguments);
    if (arguments.length) this.filter('select.select2-hidden-accessible').trigger('change.select2');
    return result;
  };
  const nativeReset = HTMLFormElement.prototype.reset;
  HTMLFormElement.prototype.reset = function () {
    nativeReset.apply(this, arguments);
    $(this).find('select.select2-hidden-accessible').trigger('change.select2');
  };
  $(document).on('reset', 'form', function (e) {
    setTimeout(function () {
      $(e.target).find('select.select2-hidden-accessible').trigger('change.select2');
    });
  });

  $(function () {
    $('select.form-select').each(function () { searchableSelect(this); });
    new MutationObserver(function (mutations) {
      mutations.forEach(function (m) {
        m.addedNodes.forEach(function (node) {
          if (node.nodeType !== 1) return;
          if (node.matches('select.form-select')) searchableSelect(node);
          node.querySelectorAll('select.form-select').forEach(searchableSelect);
        });
      });
    }).observe(document.body, { childList: true, subtree: true });
  });
})(jQuery);

// ---------------------------------------------------------------------------
// Shared UI helpers (design-system single source of truth). Pages currently
// copy-paste their own showToast()/escapeHtml() locally; those local defs still
// shadow these globals, so adding them here is non-breaking. New/refactored
// pages can drop their duplicates and call window.showToast / window.escapeHtml
// / window.bimsConfirm instead, keeping toast colours and confirm dialogs
// consistent site-wide and sourced from the CSS tokens.
// ---------------------------------------------------------------------------
(function () {
  // Solid token hexes (Toastify needs a colour string, not a CSS var).
  var TOAST_BG = {
    success: '#16a34a',
    danger:  '#dc2626',
    error:   '#dc2626',
    warning: '#d97706',
    info:    '#0891b2',
    primary: '#2563eb'
  };

  window.escapeHtml = window.escapeHtml || function (unsafe) {
    return (unsafe == null ? '' : String(unsafe))
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  };

  window.showToast = window.showToast || function (type, message) {
    if (typeof Toastify === 'undefined') { return; }
    Toastify({
      text: message,
      duration: 3000,
      gravity: 'top',
      position: 'right',
      close: true,
      style: { background: TOAST_BG[type] || TOAST_BG.primary }
    }).showToast();
  };

  // Promise-based, on-brand replacement for native confirm(). Usage:
  //   window.bimsConfirm('Delete this record?').then(function (ok) { ... });
  // Falls back to native confirm() if Bootstrap's modal isn't available.
  window.bimsConfirm = function (message, opts) {
    opts = opts || {};
    var title = opts.title || 'Please confirm';
    var confirmText = opts.confirmText || 'Confirm';
    var cancelText = opts.cancelText || 'Cancel';
    var danger = opts.danger !== false; // default to destructive styling
    if (typeof bootstrap === 'undefined' || !bootstrap.Modal) {
      return Promise.resolve(window.confirm(message));
    }
    return new Promise(function (resolve) {
      var el = document.createElement('div');
      el.className = 'modal fade';
      el.setAttribute('tabindex', '-1');
      el.innerHTML =
        '<div class="modal-dialog modal-dialog-centered">' +
          '<div class="modal-content">' +
            '<div class="modal-header' + (danger ? ' danger-header' : '') + '">' +
              '<h5 class="modal-title"><i class="fas fa-' +
                (danger ? 'triangle-exclamation' : 'circle-question') + ' me-2"></i>' +
                window.escapeHtml(title) + '</h5>' +
              '<button type="button" class="btn-close" data-bs-dismiss="modal"></button>' +
            '</div>' +
            '<div class="modal-body">' + window.escapeHtml(message) + '</div>' +
            '<div class="modal-footer">' +
              '<button type="button" class="btn btn-secondary" data-bs-dismiss="modal">' +
                window.escapeHtml(cancelText) + '</button>' +
              '<button type="button" class="btn btn-' + (danger ? 'danger' : 'primary') +
                '" data-bims-confirm>' + window.escapeHtml(confirmText) + '</button>' +
            '</div>' +
          '</div>' +
        '</div>';
      document.body.appendChild(el);
      var modal = new bootstrap.Modal(el);
      var confirmed = false;
      el.querySelector('[data-bims-confirm]').addEventListener('click', function () {
        confirmed = true;
        modal.hide();
      });
      el.addEventListener('hidden.bs.modal', function () {
        el.remove();
        resolve(confirmed);
      });
      modal.show();
    });
  };
})();

$(document).ready(function () {
  $('#example').DataTable();

  // Initialise Bootstrap dropdowns, but NOT the nested submenu toggles —
  // those are driven manually (hover + tap) in main_top_navbar.html, and a
  // Bootstrap instance on them would fight that handler on touch devices.
  $('.dropdown-toggle').not('.dropdown-submenu > .dropdown-toggle').each(function () {
    new bootstrap.Dropdown(this);
  });

  // Close any open menu when tapping/clicking outside a dropdown.
  // Dropdowns live either in a .dropdown wrapper (navbar) or a .btn-group
  // (split/toolbar buttons) — treat both as "inside".
  $(document).on('click', function (e) {
    if (!$(e.target).closest('.dropdown, .btn-group').length) {
      $('.dropdown-menu').removeClass('show');
    }
  });
});
