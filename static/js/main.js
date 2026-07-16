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
