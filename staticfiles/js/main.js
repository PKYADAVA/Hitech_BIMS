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
// Column alignment, mirrored from the header onto the body.
//
// The design system aligns by data type: quantities, rates and amounts right,
// dates and statuses centred, everything else left. Marking that up per cell is
// impossible for most of these grids because their rows are built in JS — so
// the header carries the intent and this copies it down, once per render.
// ---------------------------------------------------------------------------
(function ($) {
  var ALIGN = ["ds-num", "ds-mid"];

  function mirror(table) {
    var $table = $(table);
    if (!$table.length) return;
    var classes = $table.find("thead th").map(function () {
      var th = this;
      return ALIGN.filter(function (c) { return th.classList.contains(c); }).join(" ");
    }).get();
    if (!classes.some(Boolean)) return;
    $table.find("tbody tr").each(function () {
      $(this).children("td").each(function (i) {
        if (classes[i]) this.className = (this.className + " " + classes[i]).trim();
      });
    });
  }

  $(document).on("init.dt draw.dt", function (e, settings) {
    mirror(settings ? settings.nTable : null);
  });
  $(function () { $("table.ds-grid, table.ds-entry").each(function () { mirror(this); }); });

  // Grids that render their own rows outside DataTables can ask for it.
  window.dsAlignColumns = mirror;
})(jQuery);

// ---------------------------------------------------------------------------
// Landing from the dashboard's global search: a record hit links to its list
// page carrying ?find=<term>. Seed every DataTable on that page with the term
// so the row the user actually picked is filtered to the top on arrival,
// instead of dropping them at the top of an unfiltered list.
//
// Registered as a delegated init.dt here (rather than an initComplete default)
// because $.extend replaces rather than merges functions - a page defining its
// own initComplete would silently drop ours.
// ---------------------------------------------------------------------------
(function ($) {
  var term = new URLSearchParams(window.location.search).get("find");
  if (!term) return;
  $(document).on("init.dt", function (e, settings) {
    var api = new $.fn.dataTable.Api(settings);
    if (api.search()) return;   // the page set its own filter - leave it alone
    var box = $(settings.nTableWrapper).find(".dataTables_filter input");
    if (box.length) box.val(term);
    api.search(term).draw();
  });
})(jQuery);

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
    // Reparent onto .modal-content (not .modal) when inside a modal: Bootstrap
    // gives .modal-content `position: relative`, which is the containing
    // block Select2's offset()-based math expects. .modal itself is
    // `position: fixed` (viewport-anchored), so children absolutely
    // positioned against it land wherever the page happens to be scrolled —
    // the dropdown appears "anywhere" in the modal instead of under the field.
    const $modalContent = $el.closest('.modal-content');
    $el.select2({
      theme: 'bootstrap-5',
      width: el.style.width ? 'style' : '100%',
      selectionCssClass: small ? 'select2--small' : '',
      dropdownCssClass: small ? 'select2--small' : '',
      dropdownParent: $modalContent.length ? $modalContent : $(document.body),
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
// Transaction dates cannot be in the future.
//
// A transaction dated ahead of today corrupts everything read as-of a date —
// age, opening stock, live-bird counts, ledger balances — and there is no
// legitimate reason to file one. Applied here rather than per form so every
// transaction page gets it, including rows built in JavaScript after load.
//
// Scope is deliberately narrow: only a date input whose id/name is exactly
// "date", or that carries a "date" class (this codebase's row convention).
// Scheduling fields have their own names — hatch_date, setting_date,
// transfer_date, effective_from, agreement dates, financial-year bounds — and
// those are legitimately in the future, so they are left alone. Any field can
// opt out with data-allow-future.
// ---------------------------------------------------------------------------
(function () {
  function today() {
    const d = new Date();
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
      .toISOString().slice(0, 10);
  }

  function isTransactionDate(el) {
    if (el.type !== 'date' || el.hasAttribute('data-allow-future')) return false;
    return el.id === 'date' || el.name === 'date' || el.classList.contains('date');
  }

  function guard(el) {
    if (!isTransactionDate(el) || el.dataset.futureGuarded) return;
    el.dataset.futureGuarded = '1';
    const max = today();
    // Only tighten: a page that already set its own max keeps it.
    if (!el.max || el.max > max) el.max = max;
    if (el.value && el.value <= max) el.dataset.lastGood = el.value;
  }

  function check(el) {
    if (!el.dataset.futureGuarded || !el.value) return;
    if (el.value > today()) {
      window.alert('Entry date cannot be later than today.');
      // Reverted, not clamped: clamping would leave a date nobody chose.
      el.value = el.dataset.lastGood || today();
    } else {
      el.dataset.lastGood = el.value;
    }
  }

  function scan(root) {
    if (root.nodeType !== 1) return;
    if (root.matches && root.matches('input[type="date"]')) guard(root);
    if (root.querySelectorAll) root.querySelectorAll('input[type="date"]').forEach(guard);
  }

  document.addEventListener('DOMContentLoaded', function () {
    scan(document.body);
    new MutationObserver(function (mutations) {
      mutations.forEach(function (m) { m.addedNodes.forEach(scan); });
    }).observe(document.body, { childList: true, subtree: true });
  });

  // Delegated so rows added later are covered without rebinding.
  document.addEventListener('change', function (e) {
    if (e.target && e.target.matches && e.target.matches('input[type="date"]')) check(e.target);
  }, true);
})();

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
  // (split/toolbar buttons) — treat both as "inside". DataTables' Buttons
  // collection (e.g. the "Column visibility" list) renders its own
  // .dropdown-menu-styled panel appended straight to <body>, detached from
  // any .dropdown/.btn-group ancestor, so it must be treated as "inside"
  // too — otherwise every checkbox click inside it reads as an outside
  // click and force-closes the list after one toggle.
  $(document).on('click', function (e) {
    if (!$(e.target).closest('.dropdown, .btn-group, .dt-button-collection').length) {
      $('.dropdown-menu').not('.dt-button-collection').removeClass('show');
    }
  });
});


/* ---------------------------------------------------------------------------
   Reverse geocoding — turn a GPS reading into a readable address.
   ---------------------------------------------------------------------------
   Used by Broiler > Transactions > Farm Location & Photos, so capturing a
   farm's pin also records where it is in words.

   Resolves to {display, state, district, area}, or null.

   OpenStreetMap's Nominatim needs no API key. It is best-effort by design: it
   is rate-limited and can be blocked or offline, so every caller must keep
   working when this resolves to null rather than treating a lookup failure as
   a failure to capture the location. The coordinates are the record; the
   address is a convenience on top.
   --------------------------------------------------------------------------- */
window.reverseGeocode = function (latitude, longitude) {
  const url = 'https://nominatim.openstreetmap.org/reverse?format=jsonv2'
            + '&lat=' + encodeURIComponent(latitude)
            + '&lon=' + encodeURIComponent(longitude)
            + '&zoom=18&addressdetails=1';
  const timeout = new Promise(function (resolve) { setTimeout(() => resolve(null), 8000); });
  const lookup = fetch(url, { headers: { 'Accept': 'application/json' } })
    .then(function (resp) { return resp.ok ? resp.json() : null; })
    .then(function (data) {
      if (!data || !data.display_name) return null;
      const a = data.address || {};
      // Nominatim names the same level differently by country and by how built
      // up the place is, so each part takes the first key that answers.
      return {
        display: data.display_name,
        state: a.state || '',
        district: a.state_district || a.county || a.district || '',
        area: a.suburb || a.village || a.town || a.city_district
              || a.neighbourhood || a.hamlet || a.city || '',
      };
    })
    .catch(function () { return null; });
  // Whichever settles first: a slow lookup must never hold up the form.
  return Promise.race([lookup, timeout]);
};


/* ---------------------------------------------------------------------------
   Dependent dropdowns — load one select's options from an endpoint.
   ---------------------------------------------------------------------------
   Replaces the hand-rolled "empty the select, then append in the AJAX
   callback" pattern, which double-fills whenever its change handler runs more
   than once: the empty happens straight away but both replies append later, so
   the list arrives twice. Select2 makes that routine — it raises its own
   jQuery change and the bridge above re-dispatches a native one, so a handler
   bound with .change() sees both.

   Two things make a repeated call harmless here: the list is rebuilt inside
   the reply rather than appended to, and each call takes a token so only the
   newest reply is allowed to render.

     loadOptions('#branch', url, {region_id: 3}, {list: 'branches', label: 'branch_name'})
   --------------------------------------------------------------------------- */
window.loadOptions = function (select, url, data, options) {
  options = options || {};
  const $select = window.jQuery(select);
  if (!$select.length) return window.jQuery.Deferred().resolve().promise();

  const token = ($select.data('optionsToken') || 0) + 1;
  $select.data('optionsToken', token);

  const placeholder = options.placeholder === undefined ? 'select' : options.placeholder;
  const valueKey = options.value || 'id';
  const labelKey = options.label || 'name';

  return window.jQuery.getJSON(url, data).then(function (response) {
    if ($select.data('optionsToken') !== token) return;   // a newer call won
    const rows = options.list ? (response[options.list] || []) : (response || []);

    $select.empty();
    if (placeholder !== null) {
      const first = document.createElement('option');
      first.value = '';
      first.textContent = placeholder;
      first.selected = true;
      if (options.placeholderDisabled !== false) first.disabled = true;
      $select.append(first);
    }
    rows.forEach(function (row) {
      const opt = document.createElement('option');
      opt.value = row[valueKey];
      // textContent, so a name with < or & cannot inject markup.
      opt.textContent = row[labelKey];
      $select.append(opt);
    });
    if (options.selected) $select.val(options.selected);
    if ($select.hasClass('select2-hidden-accessible')) $select.trigger('change.select2');
  });
};
