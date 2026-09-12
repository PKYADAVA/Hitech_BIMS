// ---------------------------------------------------------------------------
// Open a register on the date a link asked for.
//
// Every transaction register opens on today, or on the last week. A link to a
// particular record - from the Change Requests page, say - would therefore land
// on a list that does not contain it, which reads as the record having been
// deleted rather than as a filter hiding it.
//
// A link may carry ?from_date=&to_date=; if it does, this writes them into the
// page's own date inputs and presses its own filter button, so the register
// loads exactly the way it would if someone had typed the dates in.
//
// It may also carry ?record=, the number of the one row that was asked for.
// That goes into the register's own search box rather than being filtered
// invisibly: the reader can see why a list of one is a list of one, and clear
// it to get the rest of the day back.
//
// Ordering is the whole difficulty. A register sets its defaults inside
// jQuery's ready callback, and when the document is already complete by the
// time that callback is registered - which it is, since these scripts sit at
// the foot of the page - jQuery defers it. So a plain load listener runs first
// and is then overwritten by the very defaults it meant to replace. Waiting a
// turn of the event loop after load puts this behind that queue.
//
// Thirty-two registers share these control ids (#from-date, #to-date and either
// #filter-submit or #search-btn), which is what makes one handler here better
// than thirty-two copies of four lines.
// ---------------------------------------------------------------------------
window.addEventListener('load', function () {
  const params = new URLSearchParams(window.location.search);
  const from = params.get('from_date');
  const to = params.get('to_date');
  if (!from && !to) return;

  setTimeout(function () {
    const fromEl = document.getElementById('from-date');
    const toEl = document.getElementById('to-date');
    if (!fromEl && !toEl) return;            // not a register; nothing to do

    if (fromEl && from) fromEl.value = from;
    if (toEl && to) toEl.value = to;

    // The page's own button, so the register reloads exactly as it would if
    // someone had typed the dates and pressed it.
    const reload = document.getElementById('filter-submit')
                || document.getElementById('search-btn');
    if (reload) reload.click();

    const record = params.get('record');
    if (record) showOnlyRecord(record);
  }, 0);
});

// Put a record number into the register's own DataTables search box.
//
// The wait is the awkward part. Pressing the filter button starts a fetch, and
// these registers destroy and rebuild their table when it returns, which would
// throw away a search applied too early. So this waits until the row is
// actually on screen before typing into the box - at which point the table it
// is typing into is certainly the final one.
//
// If the row never appears the search is left alone: showing the day's list is
// a better answer than an empty table filtered by a number that is not there.
function showOnlyRecord(record) {
  let attempts = 0;
  (function tick() {
    const input = document.querySelector('.dataTables_filter input');
    const body = document.querySelector('table tbody');
    if (input && body && body.textContent.includes(record)) {
      input.value = record;
      // DataTables listens for these rather than for a value assignment.
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('keyup', { bubbles: true }));
      return;
    }
    if (++attempts < 40) setTimeout(tick, 150);   // give up after ~6 seconds
  })();
}

// ---------------------------------------------------------------------------
// The local calendar day as YYYY-MM-DD.
//
// Formatting straight from toISOString gives the UTC day. India runs 5:30
// ahead, so the UTC date does not turn over until 05:30 local: between
// midnight and 05:30 it still names yesterday, and a form opened at 5am on a
// farm prefilled the previous date. Shifting by the zone's own offset first
// keeps the browser's date, which is the one the person is working in.
//
// Exposed globally because ~50 pages need it; `date` is optional and defaults
// to now.
// ---------------------------------------------------------------------------
window.localDay = function (date) {
  const d = date ? new Date(date) : new Date();
  if (isNaN(d.getTime())) return "";
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 10);
};

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
    // Multi-selects are included. Left native they render as a short scrolling
    // box that shows two or three rows of a list that may run to hundreds, with
    // no search and with ctrl-click as the only way to pick a second item —
    // which is not discoverable and is impossible on a touch screen. `size` is
    // still respected on single selects, where it is an explicit ask for a list.
    if (!$el.is('select.form-select')) return;
    if (!el.multiple && el.size > 1) return;
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
      // What an empty box means is the field's business, not this helper's:
      // on some forms nothing selected means "everything", on others it means
      // "none". Whoever knows says so with data-placeholder.
      placeholder: $el.data('placeholder') || null,
      // Picking several is the normal case on a multi-select, and closing the
      // list after each one makes choosing four branches four journeys.
      closeOnSelect: !el.multiple,
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
  const today = window.localDay;

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
    // Some endpoints pick for you - the scheme matching a batch, say - and name
    // the choice in the reply rather than the caller knowing it beforehand.
    // `selectedFrom` reads it from the response; `selected` still takes a value
    // the caller already holds.
    const chosen = options.selectedFrom ? response[options.selectedFrom] : options.selected;
    if (chosen) $select.val(chosen);
    if ($select.hasClass('select2-hidden-accessible')) $select.trigger('change.select2');
  });
};

/* ------------------------------------------------------------------ *
 * One save per press
 *
 * On a slow link a save looks like nothing happening, so the button gets
 * pressed again — and the second press files the record a second time. The
 * two copies carry the same details and either the same document number or
 * the next one, depending on whether the two requests read the counter in the
 * same instant or one after the other.
 *
 * Twenty-three of the forty forms already disabled their own button; the rest
 * did not, and none of them agreed on how. This does it once, for every form
 * on the site, the same way the searchable selects are applied globally rather
 * than page by page.
 *
 * It holds the button that started a write until that write comes back, then
 * releases it so a failed save can be retried. It does not make the save
 * idempotent — two presses that both reach the server are still two saves —
 * which is why it is a guard and not the whole answer.
 * ------------------------------------------------------------------ */
(function () {
  const WRITE = /^(POST|PUT|PATCH|DELETE)$/i;
  const inFlight = new WeakMap();
  let lastPressed = null;

  /* --- one save per form, not merely one per press -------------------
   *
   * Holding the button stops the second press. It does nothing about the
   * presses that never reach the button: a refresh and "resend", a second
   * tab, or a save that timed out on this side after the server had already
   * filed it. Those all arrive as a second, genuine request.
   *
   * So each form also carries a key, sent as a header — the same header the
   * phone's outbox uses, answered by the same middleware, so there is one
   * mechanism to understand rather than two. The server performs the first
   * request bearing a key and replays its answer to any other, which is what
   * makes a duplicate harmless rather than merely unlikely.
   *
   * The key belongs to the form, so every copy of one attempt shares it, and
   * is retired as soon as that attempt is answered — the next press is a new
   * intention, not a replay of the last one.
   */
  const keys = new WeakMap();

  function newKey() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return 'k-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12);
  }

  function holderFor(el) {
    // Saves that sit outside a form — a row's delete button, say — share the
    // page's key. They are one-shot actions, and the key is retired as soon
    // as one of them succeeds.
    return (el && el.closest && el.closest('form')) || document.body;
  }

  function keyFor(el) {
    const holder = holderFor(el);
    let key = keys.get(holder);
    if (!key) { key = newKey(); keys.set(holder, key); }
    return { key: key, holder: holder };
  }

  /**
   * `status` is what came back — or 0 when nothing did, because the link
   * dropped or the browser gave up waiting.
   *
   * Retiring the key on *any* outcome was the mistake this replaces, and it
   * defeated the guard in exactly the case it was written for. On a slow link
   * a save reaches the server and is filed, and the answer is lost on the way
   * back. The browser sees a failure, the key is thrown away, the person sees
   * nothing and presses save again — and the second press carries a *new* key,
   * so the server has no way to know it has done this already. Two records.
   *
   * So the key is only retired once an answer has actually arrived:
   *
   *   2xx  the save is known to have landed; the next press is a new
   *        intention and must not be answered from this one.
   *   4xx  the payload was refused. The person will change it and press
   *        again, and that is a different save — holding the key would hand
   *        them back the stored complaint about what they just corrected.
   *   5xx  something broke and the server has already released the key, so
   *        keeping it costs nothing and a retry does the work.
   *   0    nothing came back. The one case where the outcome is genuinely
   *        unknown, and the one where the key has to survive: the retry
   *        carries it, and the server recognises the work it already did.
   */
  function settle(entry, status) {
    release(entry && entry.el);
    if (!entry || !entry.holder) return;
    const answered = status >= 200 && status < 500;
    if (answered) keys.delete(entry.holder);
  }

  // Capture, so the button is known before any handler runs and calls the
  // request that we are about to tie to it.
  document.addEventListener('click', function (event) {
    const el = event.target.closest
      ? event.target.closest('button, input[type="submit"], input[type="button"]')
      : null;
    lastPressed = el && !el.disabled ? el : null;
  }, true);

  function hold(el) {
    if (!el || el.disabled) return null;
    el.disabled = true;
    el.setAttribute('aria-busy', 'true');
    // A cursor rather than a spinner: it needs no markup of its own, so it
    // cannot disturb a layout on four hundred pages.
    el.dataset.bimsCursor = el.style.cursor || '';
    el.style.cursor = 'progress';
    return el;
  }

  function release(el) {
    if (!el) return;
    el.disabled = false;
    el.removeAttribute('aria-busy');
    el.style.cursor = el.dataset.bimsCursor || '';
    delete el.dataset.bimsCursor;
  }

  // Enter in a text box submits the form without anyone clicking anything, so
  // there would be no button to hold and the guard would quietly not apply.
  // `submitter` names the button the browser attributed the submit to; failing
  // that, the form's own submit control is the one to hold. Capture phase, so
  // this lands before the page's handler fires the request.
  document.addEventListener('submit', function (event) {
    const form = event.target;
    if (!form || form.tagName !== 'FORM') return;
    lastPressed = event.submitter || form.querySelector(
      'button[type="submit"], button:not([type]), input[type="submit"]') || lastPressed;
  }, true);

  // jQuery's AJAX, which is how most of the transaction forms save.
  if (window.jQuery) {
    jQuery(document).ajaxSend(function (event, xhr, settings) {
      if (!WRITE.test(settings.type || settings.method || 'GET')) return;
      const pressed = lastPressed;
      const k = keyFor(pressed);
      xhr.setRequestHeader('Idempotency-Key', k.key);
      inFlight.set(xhr, { el: hold(pressed), holder: k.holder });
    });
    jQuery(document).ajaxComplete(function (event, xhr) {
      settle(inFlight.get(xhr), xhr.status || 0);
      inFlight.delete(xhr);
    });
  }

  // fetch(), which the newer forms use.
  const nativeFetch = window.fetch;
  if (typeof nativeFetch === 'function') {
    window.fetch = function (input, init) {
      let method = (init && init.method)
        || (input && typeof input === 'object' && input.method)
        || 'GET';
      if (!WRITE.test(method)) return nativeFetch.apply(this, arguments);

      const k = keyFor(lastPressed);
      // Headers may arrive as a Headers object, an array of pairs or a plain
      // object; normalising is the only way to add to all three. A caller
      // that set the header itself keeps it.
      const opts = Object.assign({}, init);
      const headers = new Headers((init && init.headers)
        || (typeof input === 'object' && input && input.headers) || {});
      if (!headers.has('Idempotency-Key')) headers.set('Idempotency-Key', k.key);
      opts.headers = headers;
      if (init === undefined && typeof input === 'object' && input && input.method) {
        // fetch(new Request(...)) with no init: carry the request's own method
        // through, or the copy would be sent as a GET.
        opts.method = input.method;
      }

      const entry = { el: hold(lastPressed), holder: k.holder };
      let result;
      try {
        result = nativeFetch.call(this, input, opts);
      } catch (e) {
        settle(entry, 0);
        throw e;
      }
      return result.then(
        function (r) { settle(entry, r.status); return r; },
        // No answer at all: the key stays, so the retry is recognised.
        function (e) { settle(entry, 0); throw e; }
      );
    };
  }

  // A form that posts the ordinary way, with no script behind it. Bubble
  // phase and defaultPrevented: a form whose handler called preventDefault is
  // saving over AJAX, and the hooks above already have it. The timeout lets
  // the browser finish serialising the form first — a button disabled any
  // earlier would drop its own name and value from the request.
  document.addEventListener('submit', function (event) {
    if (event.defaultPrevented) return;
    const form = event.target;
    if (!form || form.tagName !== 'FORM') return;
    setTimeout(function () {
      form.querySelectorAll(
        'button[type="submit"], button:not([type]), input[type="submit"]'
      ).forEach(hold);
    }, 0);
  });
})();
