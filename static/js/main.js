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

    // Several records at once — the Duplicate Entries page sends the numbers
    // of one finding so the register opens on exactly those rows.
    const records = params.get('records');
    if (records) showOnlyRecords(records.split(',').filter(Boolean));
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

// Show only the records named, however many.
//
// The single-record version above types into the search box, which cannot
// express "this one or that one" — the box searches for one string. So this
// goes through the DataTables API instead, where a search can be a regular
// expression, and asks for the numbers joined by alternation.
//
// The box is filled in afterwards so the page does not look unfiltered, but
// without firing the events that would make DataTables re-read it as a plain
// string and throw the regex away.
//
// Same wait as the single version, and the same reason: a register rebuilds
// its table when its filter returns, and a search applied before that is lost.
function showOnlyRecords(records) {
  if (!records.length) return;
  if (records.length === 1) return showOnlyRecord(records[0]);

  const pattern = records
    .map(function (r) { return r.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); })
    .join('|');
  let attempts = 0;
  (function tick() {
    const body = document.querySelector('table tbody');
    const ready = body && records.some(function (r) { return body.textContent.includes(r); });
    if (ready && $.fn.dataTable) {
      $.fn.dataTable.tables({ api: true }).search(pattern, true, false).draw();
      const input = document.querySelector('.dataTables_filter input');
      if (input) input.value = records.join(' , ');
      return;
    }
    if (++attempts < 40) setTimeout(tick, 150);
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
// ---------------------------------------------------------------------------
// A date as DD-MM-YYYY, which is how this business writes one.
//
// The registers printed whatever the API sent, which is ISO (2026-07-21), so a
// grid disagreed with its own filter boxes and with every server-rendered date
// on the site. One helper rather than twenty copies of the same three lines.
//
// Anything that is not an ISO date comes back unchanged but escaped, since
// these values are dropped straight into a template string.
// ---------------------------------------------------------------------------
window.fmtDate = function (value) {
  if (value === null || value === undefined || value === "") return "";
  const text = String(value);
  const iso = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (iso) return iso[3] + "-" + iso[2] + "-" + iso[1];
  return text.replace(/[&<>"]/g, function (ch) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
  });
};

// ---------------------------------------------------------------------------
// Every register sorts its Date column as plain text by default, and
// fmtDate's own DD-MM-YYYY is exactly the format text-sorting gets wrong —
// "02-10-2026" reads as earlier than "29-09-2026" because "0" < "2". A grid
// with `order: [[0, "desc"]]` on a fmtDate'd column looked "almost sorted"
// (right within a month, wrong across one) rather than obviously broken,
// which is why it went unnoticed on page after page. Registered once, here,
// rather than patched per grid: every table gets correct date ordering for
// free, including ones that never think about sorting at all.
// ---------------------------------------------------------------------------
if (window.jQuery && jQuery.fn.dataTable) {
  jQuery.fn.dataTable.ext.type.detect.unshift(function (data) {
    return (typeof data === "string" && /^\d{2}-\d{2}-\d{4}$/.test(data.trim()))
      ? "date-dd-mm-yyyy" : null;
  });
  jQuery.fn.dataTable.ext.type.order["date-dd-mm-yyyy-pre"] = function (data) {
    if (!data) return 0;
    const parts = String(data).trim().split("-");
    return parseInt(parts[2] + parts[1] + parts[0], 10);
  };
}

window.localDay = function (date) {
  const d = date ? new Date(date) : new Date();
  if (isNaN(d.getTime())) return "";
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 10);
};

// Month / Year shortcuts: a Year select marked data-period-year, naming its
// Month select and the From / To inputs it fills. Year lists the calendar
// years the financial years in Account > Financial Year cover.
//   Year alone  -> that whole year, 1 Jan to 31 Dec.
//   Month + Year -> that month of that year.
//   Month alone -> that month this year.
// Loading is left to the page's Submit, as for the dates themselves. Typing a
// date, or Clear, puts both back to All: they no longer describe the range.
$(function () {
  document.querySelectorAll("select[data-period-year]").forEach(function (year) {
    const month = document.querySelector(year.dataset.periodMonth);
    const from = document.querySelector(year.dataset.periodFrom);
    const to = document.querySelector(year.dataset.periodTo);
    if (!month || !from || !to) return;

    $(month).add(year).on("change", function () {
      const m = parseInt(month.value, 10);
      const picked = parseInt(year.value, 10);
      if (!m && !picked) return;
      const y = picked || new Date().getFullYear();
      from.value = localDay(new Date(y, m ? m - 1 : 0, 1));
      to.value = localDay(m ? new Date(y, m, 0) : new Date(y, 11, 31));
    });
    const reset = function () { $(month).add(year).val("").trigger("change.select2"); };
    $(from).add(to).on("input", reset);
    $("#filter-clear").on("click", reset);
  });
});

// ---------------------------------------------------------------------------
// Register search: spaces mean "and", commas mean "or".
//
// DataTables' own smart search already ands the words you type across the
// row -- "green valley 990" finds the one sale that has both. What it cannot
// do is ask for two records at once: "2399,2398" looks for a row containing
// that whole string and finds nothing.
//
// A comma now separates alternatives. Each alternative keeps the and
// behaviour, so "green valley 990, abhinav" means (green and valley and 990)
// or (abhinav). Without a comma nothing changes: the box hands the term
// straight to DataTables as before.
// ---------------------------------------------------------------------------
(function ($) {
  // The test harness loads this file against a jQuery stub that carries
  // `dataTable.defaults` and nothing else, so every piece used here is
  // checked for rather than assumed.
  if (!$ || !$.fn || !$.fn.dataTable || !$.fn.dataTable.ext
      || !$.fn.dataTable.ext.search || !$.fn.dataTable.Api) return;

  // One filter for every table on the site; it stands aside unless that
  // table's box is holding a comma.
  $.fn.dataTable.ext.search.push(function (settings, searchData) {
    var groups = settings.__anyOf;
    if (!groups || !groups.length) return true;
    var row = searchData.join(" ").toLowerCase();
    return groups.some(function (words) {
      return words.every(function (word) { return row.indexOf(word) !== -1; });
    });
  });

  function parse(value) {
    return value.split(",")
      .map(function (part) { return part.trim().toLowerCase(); })
      .filter(Boolean)
      .map(function (part) { return part.split(/\s+/); });
  }

  $(document).on("init.dt", function (e, settings) {
    if (e.namespace !== "dt") return;
    var api = new $.fn.dataTable.Api(settings);
    var input = $(settings.nTableWrapper).find(".dataTables_filter input");
    if (!input.length) return;

    // Words, not numbers: a placeholder of "2399, 2398" reads as a value
    // somebody already typed rather than as a hint about the box.
    input.attr("placeholder", "comma for either");
    input.attr("title", "Spaces narrow the search; a comma asks for either");

    // DataTables' own handler would search for the comma string itself, so
    // the box is rebound rather than listened to alongside.
    input.off(".DT").on("input.bimsSearch", function () {
      var value = this.value;
      if (value.indexOf(",") === -1) {
        settings.__anyOf = null;
        api.search(value).draw();
        return;
      }
      settings.__anyOf = parse(value);
      // The alternatives are ours to apply; DataTables' own term would fight
      // them, so it is cleared while a comma is in the box.
      api.search("").draw();
    });
  });
})(jQuery);

// ---------------------------------------------------------------------------
// Registers on a phone: the columns stay and the table scrolls sideways.
//
// DataTables Responsive folds the spare columns into a row you open instead.
// On a thirteen-column register that leaves four columns and nine numbers
// behind a chevron -- Farm, Batch, Birds, Net Wt., Avg Wt., Rate, Amount --
// which is most of what a register is read for. Swiping a wide table is the
// gesture the module bar and the page tabs already use on that screen.
//
// `responsive: true` is written into sixty-seven registers one by one, so it
// cannot be turned off from the defaults: this takes it out of the options as
// each table is built, and only where the screen is narrow. Wider screens are
// untouched, and so is every other option the page passed.
// ---------------------------------------------------------------------------
(function ($) {
  if (!$ || !$.fn || !$.fn.dataTable || !window.matchMedia) return;
  var narrow = window.matchMedia("(max-width: 991.98px)");

  ["DataTable", "dataTable"].forEach(function (name) {
    var original = $.fn[name];
    if (typeof original !== "function") return;
    function patched(options) {
      if (narrow.matches && options && options.responsive) {
        options = $.extend({}, options, { responsive: false });
      }
      return original.apply(this, [options].concat(
        Array.prototype.slice.call(arguments, 1)));
    }
    // The constructor carries the API on itself (defaults, ext, Api, version),
    // and the rest of this file and every page reads them from there.
    $.extend(patched, original);
    patched.prototype = original.prototype;
    $.fn[name] = patched;
  });
})(jQuery);

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
// A Select2 panel that would hang past the right edge of the window.
//
// The panel is deliberately wider than its field -- 300px, so a long item
// name sits on one line -- but Select2 pins it to the field's left edge. A
// field near the right of the screen therefore pushes the panel off it, and
// the document grows a sideways scrollbar that has nothing to do with the
// page's own content. Nudged back inside, once, as it opens.
// ---------------------------------------------------------------------------
(function ($) {
  var MARGIN = 8;

  function keepInside() {
    // The panel has the width; its container -- a zero-width wrapper that
    // Select2 appends to the body -- has the `left` that moves it. Measuring
    // the container instead of the panel finds no overflow and does nothing.
    var panel = document.querySelector(".select2-container--open .select2-dropdown");
    if (!panel) return;
    var container = panel.parentElement;
    var over = panel.getBoundingClientRect().right
             - (document.documentElement.clientWidth - MARGIN);
    if (over <= 0) return;
    container.style.left = (parseFloat(container.style.left || "0") - over) + "px";
  }

  $(document).on("select2:open", function () {
    // After Select2 has placed it: it sets left/top itself on open.
    window.requestAnimationFrame(keepInside);
  });
})(jQuery);

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

  /* A list always opens downward, and is always fully on screen.
   *
   * Select2 flips its list above the control when the window has less than
   * the list's height below it. On an entry sheet that is most of the rows:
   * the list covers the lines above the one being filled in, which are the
   * lines somebody is reading to fill it. The browser's own dropdown never
   * does this, which is why the lifting supervisor column opted out of
   * Select2 altogether for a while rather than put up with it.
   *
   * So the placement is taken back. `_positionDropdown` is wrapped rather
   * than replaced: Select2 keeps calling it on scroll and resize, and each
   * time it is allowed to do its own arithmetic before the answer is
   * overruled. Only the direction is changed, and only when it chose above.
   *
   * Forcing it down would push the list off the bottom of a window with no
   * room, so `select2:open` scrolls the page far enough to bring it back —
   * which is the part that makes this an improvement rather than a trade.
   */
  const amd = $.fn.select2 && $.fn.select2.amd;
  if (amd && typeof amd.require === 'function') {
    try {
      const AttachBody = amd.require('select2/dropdown/attachBody');
      const position = AttachBody.prototype._positionDropdown;
      AttachBody.prototype._positionDropdown = function () {
        position.apply(this, arguments);
        // Select2 calls this again on every scroll and resize while a list is
        // open, so a throw in here would break the list mid-use rather than
        // fail once at startup. Whatever goes wrong, Select2's own placement
        // has already been applied above and stands.
        try {
          this._placeBelow();
        } catch (e) { /* leave Select2's answer alone */ }
      };

      AttachBody.prototype._placeBelow = function () {
        if (!this.$container.hasClass('select2-container--above')) return;

        // The same offsets Select2 works in: the dropdown is positioned
        // against its parent, which is the body unless the field is in a
        // modal.
        let $parent = this.$dropdownParent;
        if ($parent.css('position') === 'static') $parent = $parent.offsetParent();
        const parent = $parent.offset() || { top: 0, left: 0 };
        const offset = this.$container.offset();

        this.$dropdown.removeClass('select2-dropdown--above')
                      .addClass('select2-dropdown--below');
        this.$container.removeClass('select2-container--above')
                       .addClass('select2-container--below');
        this.$dropdownContainer.css({
          top: offset.top + this.$container.outerHeight(false) - parent.top,
          left: offset.left - parent.left,
        });
      };
    } catch (e) {
      // Select2 changed its module layout: leave the placement alone rather
      // than half-apply it. The list flips as it used to, which is the
      // behaviour this replaced and not a broken page.
    }
  }

  /* Fit the list into the room below, rather than move the page to make room.
   *
   * Scrolling the page on open was the first attempt and it is not safe:
   * Select2 opens on mousedown, so the page would slide out from under the
   * pointer mid-press, and the mouseup at the end of an ordinary press could
   * land on something else — which Select2 reads as a click outside and
   * closes on. A synthetic click never shows it, because its down and up are
   * in the same tick.
   *
   * Said plainly: that failure was reasoned from how the events are ordered,
   * not observed here. It was reported from a browser and never reproduced
   * in a harness. What is certain is that capping the list needs no page
   * movement at all, so the question cannot arise.
   */
  const LIST_FLOOR = 120;   // below this a list is not worth opening at all
  $(document).on('select2:open', function () {
    const dropdown = document.querySelector('.select2-container--open .select2-dropdown');
    const results = dropdown && dropdown.querySelector('.select2-results__options');
    if (!results) return;
    // Whatever the dropdown spends on the search box and its own padding has
    // to come out of the room before the list gets what is left.
    const chrome = dropdown.offsetHeight - results.offsetHeight;
    const room = document.documentElement.clientHeight
      - dropdown.getBoundingClientRect().top - 8;
    results.style.maxHeight = Math.max(LIST_FLOOR, room - chrome) + 'px';
  });

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

  // How an open flock reads in a Batch dropdown. The number alone was enough
  // while a farm ran one flock at a time; several can now be open at once,
  // sharing a shed, and the placement date is what tells them apart.
  window.batchOptionLabel = window.batchOptionLabel || function (batch) {
    if (!batch || !batch.placed_on) { return (batch && batch.name) || ''; }
    // Split rather than parsed: "2026-09-14" as a Date is midnight UTC, which
    // reads as the day before in any timezone behind it.
    var parts = String(batch.placed_on).split('-');
    var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    var month = months[Number(parts[1]) - 1];
    if (parts.length < 3 || !month) { return batch.name; }
    return batch.name + ' · placed ' + Number(parts[2]) + ' ' + month;
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
            '<div class="modal-body" style="white-space:pre-line">' +
              window.escapeHtml(message) + '</div>' +
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

  // Renders a print/invoice-view element to a PNG (via html2canvas) and either
  // hands it to the OS share sheet (phones — "share as image/PDF" to WhatsApp,
  // email, etc.) or downloads it, when Web Share isn't available (desktop).
  // `format` is "image" or "pdf"; PDF wraps the same canvas in a single-page
  // pdfmake document rather than re-laying the invoice out a second time.
  window.shareElementAsInvoice = function (el, filename, opts) {
    opts = opts || {};
    var format = opts.format || 'image';
    if (typeof html2canvas === 'undefined') {
      window.showToast('danger', 'Could not prepare the file for sharing.');
      return Promise.reject(new Error('html2canvas not loaded'));
    }
    return html2canvas(el, { scale: 2, backgroundColor: '#ffffff', useCORS: true })
      .then(function (canvas) {
        if (format === 'pdf') {
          return canvasToPdfBlob(canvas).then(function (blob) {
            return deliver(blob, filename + '.pdf', 'application/pdf');
          });
        }
        return new Promise(function (resolve) {
          canvas.toBlob(function (blob) {
            resolve(deliver(blob, filename + '.png', 'image/png'));
          }, 'image/png');
        });
      })
      .catch(function (err) {
        window.showToast('danger', 'Could not prepare the file for sharing.');
        throw err;
      });

    function canvasToPdfBlob(canvas) {
      return new Promise(function (resolve) {
        var imgData = canvas.toDataURL('image/png');
        // A4 at 72dpi; the image is scaled to fit the page width, height follows.
        var pageWidth = 595.28;
        var imgHeight = (canvas.height / canvas.width) * pageWidth;
        var doc = {
          pageSize: { width: pageWidth, height: Math.max(imgHeight, 841.89) },
          pageMargins: [0, 0, 0, 0],
          content: [{ image: imgData, width: pageWidth }],
        };
        pdfMake.createPdf(doc).getBlob(function (blob) { resolve(blob); });
      });
    }

    function deliver(blob, name, mime) {
      var file = new File([blob], name, { type: mime });
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        return navigator.share({ files: [file], title: filename })
          .catch(function (err) {
            if (err && err.name === 'AbortError') return; // user cancelled
            downloadBlob(blob, name);
          });
      }
      downloadBlob(blob, name);
      return Promise.resolve();
    }

    function downloadBlob(blob, name) {
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url; a.download = name;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    }
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

   Resolves to {display, state, district, area, postcode}, or null.

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
        postcode: a.postcode || '',
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
  /**
   * Say so when a save did not get through.
   *
   * Only for a write somebody pressed a button to start — a background write
   * failing is not something to interrupt them about, and `el` is what says
   * which of the two this was.
   *
   * The wording for a lost answer is careful on purpose. The save may well
   * have been filed; it is the reply that went missing, and telling somebody
   * it failed would be a guess presented as a fact. What can be promised is
   * the part that is now true: pressing save again cannot file it twice,
   * because the retry carries the same key.
   */
  function saveFailed(entry, status) {
    if (!entry || !entry.el || typeof window.showToast !== 'function') return;
    window.showToast('danger', status >= 500
      ? 'The server could not save that. Press Save to try again.'
      : 'No reply from the server — this may or may not have saved. '
        + 'Press Save again; it will not be filed twice.');
  }

  function settle(entry, status) {
    release(entry && entry.el);
    if (!entry || !entry.holder) return;
    const answered = status >= 200 && status < 500;
    if (answered) {
      keys.delete(entry.holder);
    } else {
      // Nothing came back, or the server broke. The button is already usable
      // again; without a word on screen the person sees a save that simply
      // did nothing, which is what makes them press it a second time.
      saveFailed(entry, status);
    }
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

      // A caller that reads and reports the answer itself says so, and is left
      // alone: otherwise a refusal it already explained -- the WhatsApp
      // provider turning a message down, say -- is followed by a second,
      // generic "the server could not save that".
      const quiet = headers.has('X-Bims-Own-Errors');
      const entry = { el: quiet ? null : hold(lastPressed), holder: k.holder };
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

    // No header can be put on a plain form post, so the key travels as a
    // hidden field instead. Added here rather than at page load so it only
    // ever reaches forms that actually post this way — an AJAX form that
    // serialises itself would otherwise carry a field its view never asked
    // for.
    //
    // The key belongs to the form and is never retired on this path, which
    // is what makes it work: the browser resending a POST after a refresh
    // sends the same field back, and so does a person pressing save again on
    // a page that never got its answer. A save that succeeds redirects, and
    // the next page is a new form with a new key.
    if ((form.method || '').toUpperCase() === 'POST') {
      let field = form.querySelector('input[name="idempotency_key"]');
      if (!field) {
        field = document.createElement('input');
        field.type = 'hidden';
        field.name = 'idempotency_key';
        form.appendChild(field);
      }
      field.value = keyFor(form).key;
    }
    setTimeout(function () {
      form.querySelectorAll(
        'button[type="submit"], button:not([type]), input[type="submit"]'
      ).forEach(hold);
    }, 0);
  });
})();

// ---------------------------------------------------------------------------
// Navbar check in/out.
//
// hr/templates/self_attendance.html has the full page with the same camera
// capture flow; this is that same action reachable from every page, for the
// two things most people open the page for — punching in and out — without
// a trip to My Attendance. Reading its own status, so it is correct from the
// very first click even if the page was left open since before midnight.
// ---------------------------------------------------------------------------
(function () {
  const wrap = document.getElementById('navAttendanceWrap');
  if (!wrap) return;

  // CSRF_COOKIE_HTTPONLY is on (settings.py), so the csrftoken cookie is
  // deliberately unreadable from script — same reason the page's own
  // {{ csrf_token }} is read from a data attribute rather than the cookie.
  function getCsrfToken() {
    return wrap.dataset.csrf || '';
  }

  const checkInBtn = document.getElementById('navCheckInBtn');
  const checkOutBtn = document.getElementById('navCheckOutBtn');
  const statusEl = document.getElementById('navAttendanceStatus');
  const modalEl = document.getElementById('navCameraModal');
  const video = document.getElementById('navCameraVideo');
  const canvas = document.getElementById('navCameraCanvas');
  const preview = document.getElementById('navCameraPreview');
  const captureBtn = document.getElementById('navCameraCapture');
  const skipBtn = document.getElementById('navCameraSkip');
  const fallback = document.getElementById('navCameraFallback');

  let checkedIn = wrap.dataset.checkedIn === '1';
  let checkedOut = wrap.dataset.checkedOut === '1';
  const blocked = wrap.dataset.blocked === '1';

  let isCheckIn = true;
  let cameraStream = null, streamWatchdog = null, capturedBlob = null;
  let capturedLat = null, capturedLng = null, capturedAccuracy = null, capturedAddress = '';
  let wizMap = null, wizMarker = null;

  // Check In disables once used (or once a prior day is left open), Check
  // Out disables until checked in (or once used) — both are plain booleans
  // that match server state exactly, so this runs on every load.
  function applyButtons() {
    checkInBtn.disabled = checkedIn || blocked;
    checkOutBtn.disabled = !checkedIn || checkedOut;
  }
  applyButtons();

  // The status badge is left exactly as the server rendered it on page
  // load -- Present/Half Day/Late In only becomes knowable once the day is
  // closed out (hr.views._self_attendance_row), and re-deriving the simpler
  // "Checked Out" here on every load was overwriting that correct label with
  // a wrong one. This only ever runs after a client-side check-in, where
  // "Checked In" is the whole story and there is nothing left to get wrong.
  function applyCheckedInStatus() {
    statusEl.classList.remove('na-checked-in', 'na-blocked');
    statusEl.classList.add('na-checked-in');
    statusEl.textContent = 'Checked In';
  }

  function fmtNow() {
    return new Date().toLocaleString('en-IN', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit', hour12: true,
    });
  }

  function qs(id) { return document.getElementById(id); }

  function goToStep(step) {
    modalEl.querySelectorAll('.sa-wiz-step').forEach(el => el.classList.remove('is-active', 'is-done'));
    modalEl.querySelectorAll('.sa-wiz-pane').forEach(el => el.classList.remove('is-active'));
    const order = ['location', 'selfie', 'confirm', 'success'];
    const idx = order.indexOf(step);
    order.forEach((name, i) => {
      const el = modalEl.querySelector(`.sa-wiz-step[data-step="${name}"]`);
      if (!el) return;
      if (i < idx) el.classList.add('is-done');
      else if (i === idx) el.classList.add('is-active');
    });
    modalEl.querySelector(`.sa-wiz-pane[data-pane="${step}"]`).classList.add('is-active');

    const footerBtns = ['navWizCancel', 'navWizBack', 'navCameraSkip', 'navCameraCapture',
                        'navWizContinue', 'navWizConfirmSubmit', 'navWizClose'];
    footerBtns.forEach(id => qs(id).classList.add('d-none'));

    if (step === 'location') {
      qs('navWizTitle').textContent = isCheckIn ? 'Check In' : 'Check Out';
      qs('navWizCancel').classList.remove('d-none');
      const cont = qs('navWizContinue');
      cont.classList.remove('d-none'); cont.disabled = true;
    } else if (step === 'selfie') {
      qs('navWizTitle').textContent = 'Step 2: Take a Selfie';
      qs('navWizBack').classList.remove('d-none');
      skipBtn.classList.remove('d-none');
      captureBtn.classList.remove('d-none');
    } else if (step === 'confirm') {
      qs('navWizTitle').textContent = 'Step 3: Confirm ' + (isCheckIn ? 'Check In' : 'Check Out');
      qs('navWizBack').classList.remove('d-none');
      const submitBtn = qs('navWizConfirmSubmit');
      submitBtn.classList.remove('d-none');
      submitBtn.textContent = isCheckIn ? 'Confirm Check In' : 'Confirm Check Out';
      qs('navWizConfirmWhen').textContent = fmtNow();
      qs('navWizConfirmLoc').textContent = capturedAddress ||
        (capturedLat != null ? `${capturedLat.toFixed(5)}, ${capturedLng.toFixed(5)}` : '-');
      const photoEl = qs('navWizConfirmPhoto');
      if (capturedBlob) { photoEl.src = preview.src; photoEl.classList.remove('d-none'); }
      else { photoEl.classList.add('d-none'); }
    } else if (step === 'success') {
      qs('navWizClose').classList.remove('d-none');
    }
  }

  function initWizMap(lat, lng) {
    if (typeof L === 'undefined') return;
    if (!wizMap) {
      wizMap = L.map('navWizMap', { zoomControl: false, attributionControl: false }).setView([lat, lng], 16);
      L.tileLayer(BIMS_MAP.url, {
        maxZoom: BIMS_MAP.maxZoom, attribution: BIMS_MAP.attribution,
      }).addTo(wizMap);
      wizMarker = L.marker([lat, lng]).addTo(wizMap);
    } else {
      wizMap.setView([lat, lng], 16);
      wizMarker.setLatLng([lat, lng]);
    }
    setTimeout(() => wizMap.invalidateSize(), 150);
  }

  function captureLocation() {
    const statusEl = qs('navWizLocStatus');
    statusEl.classList.remove('d-none');
    statusEl.innerHTML = '<span class="spinner-border spinner-border-sm text-success"></span><span>Getting your GPS location…</span>';
    qs('navWizLocDetail').classList.add('d-none');
    qs('navWizLocRetry').classList.add('d-none');
    qs('navWizContinue').disabled = true;
    if (!navigator.geolocation) {
      statusEl.innerHTML = '<span class="text-danger">Location is not available in this browser.</span>';
      return;
    }
    navigator.geolocation.getCurrentPosition(
      pos => {
        capturedLat = pos.coords.latitude;
        capturedLng = pos.coords.longitude;
        capturedAccuracy = pos.coords.accuracy;
        initWizMap(capturedLat, capturedLng);
        qs('navWizLocCoords').textContent = `${capturedLat.toFixed(5)}, ${capturedLng.toFixed(5)}`;
        qs('navWizLocAccuracy').textContent = Math.round(capturedAccuracy) + ' meters';
        qs('navWizLocAddress').textContent = 'Looking up address…';
        statusEl.innerHTML = '<span class="text-success"><i class="fas fa-check-circle me-1"></i>Location captured</span>';
        qs('navWizLocDetail').classList.remove('d-none');
        qs('navWizContinue').disabled = false;
        if (window.reverseGeocode) {
          window.reverseGeocode(capturedLat.toFixed(6), capturedLng.toFixed(6)).then(place => {
            capturedAddress = place && place.display ? place.display : '';
            qs('navWizLocAddress').textContent = capturedAddress || '-';
          }).catch(() => { qs('navWizLocAddress').textContent = '-'; });
        } else {
          qs('navWizLocAddress').textContent = '-';
        }
      },
      err => {
        capturedLat = capturedLng = capturedAccuracy = null;
        const msg = err && err.code === err.PERMISSION_DENIED
          ? 'Location access was denied. Allow it in your browser settings and retry.'
          : 'Could not read your location. Check your connection and retry.';
        statusEl.innerHTML = `<span class="text-danger"><i class="fas fa-triangle-exclamation me-1"></i>${msg}</span>`;
        qs('navWizLocRetry').classList.remove('d-none');
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  }

  qs('navWizLocRetry').addEventListener('click', captureLocation);

  function stopCamera() {
    if (cameraStream) { cameraStream.getTracks().forEach(t => t.stop()); cameraStream = null; }
    if (streamWatchdog) { clearTimeout(streamWatchdog); streamWatchdog = null; }
  }

  function resetCameraPane() {
    video.style.display = ''; preview.style.display = 'none'; fallback.classList.add('d-none');
    capturedBlob = null;
    captureBtn.classList.remove('d-none'); captureBtn.disabled = true;
  }

  // A granted permission does not guarantee real frames — a virtual/blocked
  // device can open a stream that never produces a picture, which is the
  // black square a dead camera shows. Capture stays disabled until the video
  // actually reports a size, and a 3s watchdog gives up and offers Skip
  // Photo rather than leave a frozen preview with no way forward.
  function showCameraFallback() {
    if (streamWatchdog) { clearTimeout(streamWatchdog); streamWatchdog = null; }
    video.style.display = 'none';
    fallback.classList.remove('d-none');
    captureBtn.classList.add('d-none');
  }

  video.addEventListener('loadeddata', function () {
    if (streamWatchdog) { clearTimeout(streamWatchdog); streamWatchdog = null; }
    captureBtn.disabled = false;
  });
  // A dead/disconnected device can fire 'error' on the <video> element
  // directly rather than ever resolving loadeddata — no reason to wait
  // out the watchdog when the browser has already said so.
  video.addEventListener('error', showCameraFallback);

  function openCamera() {
    resetCameraPane();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showCameraFallback();
      return;
    }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } })
      .then(stream => {
        cameraStream = stream;
        video.srcObject = stream;
        streamWatchdog = setTimeout(() => {
          if (!video.videoWidth) showCameraFallback();
        }, 3000);
      })
      .catch(showCameraFallback);
  }

  captureBtn.addEventListener('click', function () {
    canvas.width = video.videoWidth; canvas.height = video.videoHeight;
    canvas.getContext('2d').drawImage(video, 0, 0);
    preview.src = canvas.toDataURL('image/jpeg', 0.85);
    video.style.display = 'none'; preview.style.display = '';
    canvas.toBlob(blob => {
      capturedBlob = blob;
      stopCamera();
      goToStep('confirm');
    }, 'image/jpeg', 0.85);
  });

  skipBtn.addEventListener('click', function () {
    stopCamera();
    capturedBlob = null;
    goToStep('confirm');
  });

  qs('navWizContinue').addEventListener('click', function () {
    goToStep('selfie');
    openCamera();
  });

  qs('navWizBack').addEventListener('click', function () {
    const current = modalEl.querySelector('.sa-wiz-pane.is-active').dataset.pane;
    if (current === 'selfie') { stopCamera(); goToStep('location'); }
    else if (current === 'confirm') { goToStep('selfie'); openCamera(); }
  });

  qs('navWizConfirmSubmit').addEventListener('click', function () {
    const btn = qs('navWizConfirmSubmit');
    btn.disabled = true;
    const url = isCheckIn ? wrap.dataset.checkinUrl : wrap.dataset.checkoutUrl;
    const fd = new FormData();
    fd.append('latitude', capturedLat);
    fd.append('longitude', capturedLng);
    if (capturedBlob) fd.append('photo', capturedBlob, 'selfie.jpg');
    fetch(url, { method: 'POST', headers: { 'X-CSRFToken': getCsrfToken() }, body: fd })
      .then(async r => {
        const body = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(body.error || 'Failed.');
        const when = [body.date, body.time].filter(Boolean).join(', ');
        qs('navWizSuccessTitle').textContent = (isCheckIn ? 'Checked In' : 'Checked Out') + ' Successfully!';
        qs('navWizSuccessWhen').textContent = when;
        qs('navWizSuccessLoc').textContent = capturedAddress || '';
        if (isCheckIn) { checkedIn = true; applyCheckedInStatus(); }
        else { checkedOut = true; }
        goToStep('success');
      })
      .catch(err => {
        window.showToast('danger', err.message);
        btn.disabled = false;
      });
  });

  modalEl.addEventListener('hidden.bs.modal', function () {
    stopCamera();
    const succeeded = modalEl.querySelector('.sa-wiz-pane[data-pane="success"]').classList.contains('is-active');
    applyButtons();
    capturedBlob = null;
    capturedLat = capturedLng = capturedAccuracy = null; capturedAddress = '';
    if (succeeded && !isCheckIn) {
      // Present / Half Day / Late In can only be told apart once the day is
      // complete, and that comparison against the shift lives server-side
      // (hr.views._self_attendance_row) — a reload is what lets the real
      // label replace the generic status rather than re-deriving the same
      // rule a second time here.
      setTimeout(() => window.location.reload(), 300);
    }
  });

  function openWizard(checkIn) {
    isCheckIn = checkIn;
    goToStep('location');
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
    captureLocation();
  }

  checkInBtn.addEventListener('click', function () {
    if (blocked) { window.location.href = wrap.dataset.pageUrl; return; }
    checkInBtn.disabled = true;
    openWizard(true);
  });

  checkOutBtn.addEventListener('click', function () {
    checkOutBtn.disabled = true;
    openWizard(false);
  });

  statusEl.addEventListener('click', function () {
    window.location.href = wrap.dataset.pageUrl;
  });
})();

/* Paste and drag-drop for file inputs.
 *
 * A file input opts in with data-paste-drop. The browse button keeps
 * working exactly as before; this only adds two more ways to put the same
 * files into it:
 *
 *   - paste (Ctrl+V) anywhere on the page while the input's card or modal
 *     is the thing on screen, which is how a screenshot gets attached
 *     without first being saved to disk;
 *   - dropping files onto the input or its drop zone.
 *
 * Both go through the input's own .files via a DataTransfer, so whatever
 * reads the input on submit -- a form post, FormData, a change handler --
 * sees exactly what it would have seen from the file picker, and the
 * input's own accept/multiple attributes still decide what is allowed.
 */
(function () {
  function accepts(input, file) {
    const accept = (input.getAttribute('accept') || '').trim();
    if (!accept) return true;
    const type = (file.type || '').toLowerCase();
    const name = (file.name || '').toLowerCase();
    return accept.split(',').some(function (rule) {
      rule = rule.trim().toLowerCase();
      if (!rule) return false;
      if (rule.endsWith('/*')) return type.startsWith(rule.slice(0, -1));
      if (rule.startsWith('.')) return name.endsWith(rule);
      return type === rule;
    });
  }

  // A pasted screenshot arrives as a blob named "image.png", so several in
  // a row would be indistinguishable in the file list. Stamping the name
  // keeps them apart and makes it obvious where the file came from.
  let pasteSeq = 0;
  function named(file) {
    if (file.name && file.name !== 'image.png' && file.name !== 'blob') return file;
    const ext = (file.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
    const now = new Date();
    const stamp = now.toISOString().slice(0, 19).replace(/[:T]/g, '-');
    // The counter matters: two screenshots pasted inside the same second
    // would otherwise be handed over under one name, and a server that
    // keys on filename would keep only the last.
    pasteSeq += 1;
    return new File([file], 'pasted-' + stamp + '-' + pasteSeq + '.' + ext,
                    { type: file.type });
  }

  function addFiles(input, files) {
    const keep = [];
    const multiple = input.multiple;
    // Adding to what is already there, not replacing it: pasting a second
    // screenshot into a multi-file input should leave the first attached.
    if (multiple) for (let i = 0; i < input.files.length; i++) keep.push(input.files[i]);

    let added = 0;
    for (let i = 0; i < files.length; i++) {
      if (!accepts(input, files[i])) continue;
      keep.push(named(files[i]));
      added++;
      if (!multiple) break;
    }
    if (!added) return 0;

    const dt = new DataTransfer();
    (multiple ? keep : keep.slice(-1)).forEach(function (f) { dt.items.add(f); });
    input.files = dt.files;
    // Anything already listening for a pick hears this the same way.
    input.dispatchEvent(new Event('change', { bubbles: true }));
    return added;
  }

  function flash(input, text) {
    let note = input.parentNode.querySelector('.paste-drop-note');
    if (!note) {
      note = document.createElement('div');
      note.className = 'form-text paste-drop-note';
      input.parentNode.appendChild(note);
    }
    note.textContent = text;
    note.style.color = '#1a7f45';
    clearTimeout(note._t);
    note._t = setTimeout(function () { note.textContent = ''; }, 4000);
  }

  /* Thumbnails of whatever is currently on the input.
   *
   * A file input shows "3 files" and nothing else, which is no use when the
   * files arrived by paste: a screenshot has no meaningful name to check,
   * so the only way to know the right thing is attached is to see it.
   * Rebuilt from input.files on every change, so it is as true for a file
   * picked through Browse as for one pasted or dropped.
   *
   * Each thumbnail carries a remove button. Removing rewrites input.files
   * through a DataTransfer, the same way files are added -- which is the
   * only way to drop one file from a selection, since a file input cannot
   * be edited in place.
   */
  function fileIcon(file) {
    const type = (file.type || '').toLowerCase();
    if (type === 'application/pdf') return 'fa-file-pdf';
    if (type.startsWith('video/')) return 'fa-file-video';
    if (type.startsWith('audio/')) return 'fa-file-audio';
    if (/sheet|excel|csv/.test(type)) return 'fa-file-excel';
    if (/word|document/.test(type)) return 'fa-file-word';
    return 'fa-file';
  }

  function humanSize(n) {
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return Math.round(n / 1024) + ' KB';
    return (n / (1024 * 1024)).toFixed(1) + ' MB';
  }

  function removeAt(input, index) {
    const dt = new DataTransfer();
    for (let i = 0; i < input.files.length; i++) {
      if (i !== index) dt.items.add(input.files[i]);
    }
    input.files = dt.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function clearAll(input) {
    // An empty DataTransfer rather than input.value = '': both empty the
    // input, but this keeps the one path for changing a selection, and the
    // change event below is what redraws the thumbnails.
    input.files = new DataTransfer().files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function renderThumbs(input) {
    let wrap = input.parentNode.querySelector('.paste-drop-thumbs');
    if (!wrap) {
      wrap = document.createElement('div');
      wrap.className = 'paste-drop-thumbs';
      // After the input, but before the hint text and the flash note, so
      // the order reads: control, what is attached, then guidance.
      input.parentNode.insertBefore(wrap, input.nextSibling);
    }
    // Object URLs hold the file in memory until revoked, and this redraws
    // on every change.
    (wrap._urls || []).forEach(function (u) { URL.revokeObjectURL(u); });
    wrap._urls = [];
    wrap.innerHTML = '';
    if (!input.files.length) { wrap.style.display = 'none'; return; }
    wrap.style.display = '';

    Array.prototype.forEach.call(input.files, function (file, i) {
      const cell = document.createElement('div');
      cell.className = 'paste-drop-thumb';
      cell.title = file.name + ' — ' + humanSize(file.size);

      if ((file.type || '').startsWith('image/')) {
        const url = URL.createObjectURL(file);
        wrap._urls.push(url);
        const img = document.createElement('img');
        img.src = url;
        img.alt = file.name;
        cell.appendChild(img);
      } else {
        const ic = document.createElement('i');
        ic.className = 'fas ' + fileIcon(file);
        cell.appendChild(ic);
      }

      const cap = document.createElement('span');
      cap.className = 'paste-drop-thumb-name';
      cap.textContent = file.name;
      cell.appendChild(cap);

      if ((file.type || '').startsWith('image/') && typeof Cropper !== 'undefined') {
        const edit = document.createElement('button');
        edit.type = 'button';
        edit.className = 'paste-drop-thumb-edit';
        edit.setAttribute('aria-label', 'Edit ' + file.name);
        edit.innerHTML = '<i class="fas fa-crop-simple"></i>';
        edit.addEventListener('click', function (e) {
          e.preventDefault();
          e.stopPropagation();
          if (!window.BIMS_ImageEditor) return;
          window.BIMS_ImageEditor.edit(file).then(function (blob) {
            var newName = file.name.replace(/\.[^.]+$/, '') + '-edited.jpg';
            var edited = new File([blob], newName, { type: 'image/jpeg' });
            window.BIMS_ImageEditor.replaceFileAt(input, i, edited);
          }).catch(function () {});
        });
        cell.appendChild(edit);
      }

      const del = document.createElement('button');
      del.type = 'button';           // never submits the form it sits in
      del.className = 'paste-drop-thumb-x';
      del.setAttribute('aria-label', 'Remove ' + file.name);
      del.innerHTML = '&times;';
      del.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        removeAt(input, i);
      });
      cell.appendChild(del);

      wrap.appendChild(cell);
    });

    // Only worth offering once there is more than one file to clear --
    // with a single thumbnail its own x is right there and says the same
    // thing.
    if (input.files.length > 1) {
      const clear = document.createElement('button');
      clear.type = 'button';
      clear.className = 'paste-drop-clear';
      clear.textContent = 'Clear all (' + input.files.length + ')';
      clear.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        clearAll(input);
      });
      wrap.appendChild(clear);
    }
  }

  // The drop target, widest first. closest() with a comma list returns the
  // NEAREST match, which inside a dialog is the <form> -- so a file dropped
  // on the dialog's own padding or header landed nowhere, and the highlight
  // only ever covered the form. A dialog is the thing on screen, so the
  // whole of it takes the drop.
  function zoneFor(input) {
    return input.closest('.modal-content')
        || input.closest('form, .card')
        || input.parentNode;
  }

  /* The visible drop zone.
   *
   * A bare file input reads "Choose Files / No file chosen", which says
   * nothing about dragging or pasting -- the two ways most of these files
   * actually arrive. The input is kept (it is still what carries the files
   * and what the form submits) but moved out of sight behind a panel that
   * states all three routes and is clickable across its whole area.
   *
   * Opt out with data-paste-drop="plain" where the inline control has to
   * stay, such as a toolbar row with no room for a panel.
   */
  function buildZoneUI(input) {
    if (input.dataset.pasteDrop === 'plain') return null;
    const panel = document.createElement('div');
    panel.className = 'paste-drop-panel';
    panel.innerHTML =
      '<i class="fas fa-cloud-arrow-up"></i>' +
      '<span class="paste-drop-panel-main">Drag files here or <u>click to browse</u></span>' +
      '<span class="paste-drop-panel-sub">or paste a screenshot with Ctrl+V</span>';
    input.parentNode.insertBefore(panel, input);
    input.classList.add('paste-drop-hidden-input');
    // Clicking the panel opens the same picker the input would.
    panel.addEventListener('click', function () { input.click(); });
    // Keyboard: the panel stands in for the input, so it has to be reachable
    // and operable without a mouse.
    panel.tabIndex = 0;
    panel.setAttribute('role', 'button');
    panel.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
    });
    return panel;
  }

  function wire(input) {
    if (input._pasteDropWired) return;
    input._pasteDropWired = true;

    input._panel = buildZoneUI(input);

    // One listener covers every route in: Browse fires change natively,
    // and paste/drop fire it through addFiles().
    input.addEventListener('change', function () { renderThumbs(input); });
    renderThumbs(input);
    // A form reset (Bootstrap's modals reset theirs on close) empties the
    // input without firing change, which would leave stale thumbnails
    // behind for the next time the dialog opens.
    const owner = input.form;
    if (owner) {
      owner.addEventListener('reset', function () {
        setTimeout(function () { renderThumbs(input); }, 0);
      });
    }

    const zone = zoneFor(input);

    ['dragenter', 'dragover'].forEach(function (ev) {
      zone.addEventListener(ev, function (e) {
        if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes('Files')) return;
        e.preventDefault();
        zone.classList.add('paste-drop-over');
        if (input._panel) input._panel.classList.add('paste-drop-panel-over');
      });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
      zone.addEventListener(ev, function (e) {
        if (ev === 'dragleave' && zone.contains(e.relatedTarget)) return;
        zone.classList.remove('paste-drop-over');
        if (input._panel) input._panel.classList.remove('paste-drop-panel-over');
      });
    });
    zone.addEventListener('drop', function (e) {
      if (!e.dataTransfer || !e.dataTransfer.files.length) return;
      e.preventDefault();
      const n = addFiles(input, e.dataTransfer.files);
      if (n) flash(input, n + ' file' + (n > 1 ? 's' : '') + ' added.');
    });

    // Paste is a document-level event: it lands wherever the caret is, not
    // on the file input, which cannot hold focus in the usual sense. Only
    // the visible input takes it, so a page with several does not attach
    // the same screenshot to all of them.
    document.addEventListener('paste', function (e) {
      if (!e.clipboardData || !e.clipboardData.files || !e.clipboardData.files.length) return;
      const target = e.target;
      if (target && /^(INPUT|TEXTAREA)$/.test(target.tagName) && target.type !== 'file') return;
      if (!input.offsetParent) return;
      const openModal = document.querySelector('.modal.show');
      if (openModal && !openModal.contains(input)) return;
      if (!openModal && input.closest('.modal')) return;
      const n = addFiles(input, e.clipboardData.files);
      if (n) {
        e.preventDefault();
        flash(input, n + ' file' + (n > 1 ? 's' : '') + ' pasted.');
      }
    });
  }

  function wireAll(root) {
    (root || document).querySelectorAll('input[type="file"][data-paste-drop]').forEach(wire);
  }

  document.addEventListener('DOMContentLoaded', function () {
    wireAll();
    // Modals and rows that arrive after load (the evidence and attachment
    // dialogs are rendered with the page but others are not).
    new MutationObserver(function (muts) {
      muts.forEach(function (m) {
        m.addedNodes.forEach(function (n) {
          if (n.nodeType !== 1) return;
          if (n.matches && n.matches('input[type="file"][data-paste-drop]')) wire(n);
          else if (n.querySelectorAll) wireAll(n);
        });
      });
    }).observe(document.body, { childList: true, subtree: true });
  });
})();

/* Image editor: crop + rotate before upload.
 *
 * Any file input with data-paste-drop and data-image-edit (or just
 * data-image-edit on its own) opens an editor modal when an image is
 * picked, pasted, or dropped. The user can crop and rotate; on confirm
 * the cropped blob replaces the original in the input. PDFs and
 * non-images skip the editor.
 *
 * Requires Cropper.js to be loaded before this script.
 */
(function () {
  if (typeof Cropper === 'undefined') return;

  var modal, img, cropper, resolveEdit, rejectEdit;
  // True until the person moves the crop themselves. The box starts a little
  // inside the picture so its handles can be taken hold of, and saving that
  // as it stands trims a strip off every edge -- the edge of a document, the
  // start of each line -- which they never asked for. An untouched crop saves
  // the whole picture instead.
  var cropUntouched = true;
  // Set by "Skip all" while a batch of pictures is being gone through.
  var skipAll = false;

  // Puts the crop just inside the picture. Flush to the edge, the handles sit
  // exactly on the boundary and there is nothing to take hold of.
  function fitCropToCanvas() {
    if (!cropper) return;
    var cv = cropper.getCanvasData();
    var ct = cropper.getContainerData();
    // Where the picture runs wider or taller than the frame, the crop follows
    // the frame rather than the picture: a handle placed on an edge that is
    // off-screen cannot be taken hold of, which is what left the bottom of a
    // tall photo -- and the right of a turned one -- impossible to pull in.
    var left = Math.max(cv.left, 0);
    var top = Math.max(cv.top, 0);
    var right = Math.min(cv.left + cv.width, ct.width);
    var bottom = Math.min(cv.top + cv.height, ct.height);
    var w = Math.max(right - left, 10);
    var h = Math.max(bottom - top, 10);
    // A fixed margin as well as a proportional one: a handle is about 10px
    // across and is drawn centred on the crop's edge, so an edge sitting
    // right on the boundary puts half the handle beyond it, where the frame
    // clips it and the backdrop takes the click instead.
    var pad = 14;
    var mx = Math.min(w * 0.04, 40) + pad;
    var my = Math.min(h * 0.04, 40) + pad;
    cropper.setCropBoxData({
      left: left + mx,
      top: top + my,
      width: Math.max(w - mx * 2, 20),
      height: Math.max(h - my * 2, 20),
    });
  }

  // Brings the whole picture back inside the frame after it has been turned.
  // Cropper turns the canvas about its centre but keeps its width and height
  // swapped rather than refitted, so a landscape photo stood on its end comes
  // out taller than the frame and the top and bottom of it are cut off.
  function fitCanvasToFrame() {
    if (!cropper) return;
    var cv = cropper.getCanvasData();
    var ct = cropper.getContainerData();
    var room = 12;
    var ratio = Math.min((ct.width - room * 2) / cv.width, (ct.height - room * 2) / cv.height);
    var w = cv.width * ratio;
    var h = cv.height * ratio;
    // In this view mode the picture may not be made smaller than the crop
    // box standing on it, so a tall crop left over from before the turn holds
    // the picture at its old size. Shrink the box first; it is refitted after.
    // Parked at the middle of the frame, where the picture is about to be put:
    // the picture must also keep covering the box, so one left at the old edge
    // drags the picture off-centre with it.
    cropper.setCropBoxData({
      left: ct.width / 2 - 10, top: ct.height / 2 - 10, width: 20, height: 20,
    });
    cropper.setCanvasData({
      left: (ct.width - w) / 2,
      top: (ct.height - h) / 2,
      width: w,
      height: h,
    });
  }

  function buildModal() {
    // The picture is bounded on both axes, not stretched to the width. A tall
    // photo told to fill the width grows taller than the frame, and its lower
    // edge -- carrying the crop handles -- is clipped away by the frame's own
    // overflow, so the bottom of the crop cannot be pulled up at all.
    var div = document.createElement('div');
    div.innerHTML =
      '<div class="modal fade" id="bimsImageEditor" tabindex="-1" aria-hidden="true" data-bs-backdrop="static">' +
        '<div class="modal-dialog modal-lg modal-dialog-centered">' +
          '<div class="modal-content">' +
            '<div class="modal-header py-2">' +
              '<h6 class="modal-title"><i class="fas fa-crop-simple me-1"></i><span class="bims-ed-title">Edit Image</span></h6>' +
              '<button type="button" class="btn-close" data-bs-dismiss="modal"></button>' +
            '</div>' +
            '<div class="modal-body d-flex align-items-center justify-content-center" style="background:#1a1a2e;height:70vh;overflow:hidden;padding:0">' +
              // Cropper measures the element the picture sits in, padding and
              // all, and lays itself out that wide -- so with padding on the
              // body it ran past the padded edge and was clipped. A plain stage
              // of the body's own size gives it the room it believes it has.
              '<div id="bimsEditorStage" style="width:100%;height:100%;overflow:hidden">' +
                '<img id="bimsEditorImg" style="display:block;max-width:100%;max-height:100%">' +
              '</div>' +
            '</div>' +
            '<div class="modal-footer py-2 justify-content-between">' +
              '<div class="d-flex gap-2">' +
                '<button type="button" class="btn btn-sm btn-outline-secondary bims-ed-rotate" data-deg="-90" title="Rotate left"><i class="fas fa-rotate-left"></i></button>' +
                '<button type="button" class="btn btn-sm btn-outline-secondary bims-ed-rotate" data-deg="90" title="Rotate right"><i class="fas fa-rotate-right"></i></button>' +
                '<button type="button" class="btn btn-sm btn-outline-secondary bims-ed-flip-h" title="Flip horizontal"><i class="fas fa-arrows-left-right"></i></button>' +
                '<button type="button" class="btn btn-sm btn-outline-secondary bims-ed-flip-v" title="Flip vertical"><i class="fas fa-arrows-up-down"></i></button>' +
                '<button type="button" class="btn btn-sm btn-outline-secondary bims-ed-reset" title="Reset"><i class="fas fa-undo"></i></button>' +
              '</div>' +
              '<div class="d-flex gap-2">' +
                '<button type="button" class="btn btn-sm btn-outline-secondary bims-ed-skipall d-none">Skip all</button>' +
                '<button type="button" class="btn btn-sm btn-secondary" data-bs-dismiss="modal">Skip</button>' +
                '<button type="button" class="btn btn-sm btn-primary bims-ed-apply"><i class="fas fa-check me-1"></i>Apply</button>' +
              '</div>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(div.firstChild);
    modal = document.getElementById('bimsImageEditor');
    img = document.getElementById('bimsEditorImg');

    modal.querySelectorAll('.bims-ed-rotate').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (!cropper) return;
        cropper.rotate(parseInt(this.dataset.deg));
        // A turned picture is a different shape, and Cropper keeps the
        // container it measured before the turn -- so a portrait photo turned
        // on its side came out wider than the frame and its right-hand
        // handles ended up beyond the edge, unreachable. Asking Cropper to
        // measure again refits the picture to the frame as it now stands.
        cropper.resize();
        fitCanvasToFrame();
        // The turn moves the canvas, and the first one moves it furthest --
        // fitting the crop before it has come to rest leaves the handles on
        // the edge the picture has already left, where they cannot be taken
        // hold of. Fitted on the next few frames, so it follows the picture
        // wherever it settles.
        cropUntouched = true;
        fitCropToCanvas();
        [0, 60, 180, 360].forEach(function (ms) {
          setTimeout(function () { fitCanvasToFrame(); fitCropToCanvas(); }, ms);
        });
      });
    });

    modal.querySelector('.bims-ed-flip-h').addEventListener('click', function () {
      if (cropper) {
        var d = cropper.getData();
        cropper.scaleX(d.scaleX === -1 ? 1 : -1);
      }
    });
    modal.querySelector('.bims-ed-flip-v').addEventListener('click', function () {
      if (cropper) {
        var d = cropper.getData();
        cropper.scaleY(d.scaleY === -1 ? 1 : -1);
      }
    });
    modal.querySelector('.bims-ed-skipall').addEventListener('click', function () {
      skipAll = true;
      bootstrap.Modal.getInstance(modal).hide();
    });
    modal.querySelector('.bims-ed-reset').addEventListener('click', function () {
      if (cropper) { cropper.reset(); cropUntouched = true; }
    });
    modal.querySelector('.bims-ed-apply').addEventListener('click', function () {
      if (!cropper) return;
      if (cropUntouched) {
        var whole = cropper.getCanvasData();
        cropper.setCropBoxData({
          left: whole.left, top: whole.top, width: whole.width, height: whole.height,
        });
      }
      var canvas = cropper.getCroppedCanvas({ maxWidth: 4096, maxHeight: 4096 });
      canvas.toBlob(function (blob) {
        if (resolveEdit) resolveEdit(blob);
        bootstrap.Modal.getInstance(modal).hide();
      }, 'image/jpeg', 0.92);
    });
    modal.addEventListener('hidden.bs.modal', function () {
      if (cropper) { cropper.destroy(); cropper = null; }
      if (rejectEdit) { rejectEdit('skip'); rejectEdit = null; }
    });
  }

  function editImage(file, opts) {
    opts = opts || {};
    return new Promise(function (resolve, reject) {
      if (!modal) buildModal();
      modal.querySelector('.bims-ed-title').textContent = opts.total > 1
        ? 'Edit Image ' + opts.index + ' of ' + opts.total : 'Edit Image';
      modal.querySelector('.bims-ed-skipall').classList.toggle('d-none',
        !(opts.total > 1 && opts.index < opts.total));
      resolveEdit = function (blob) {
        resolveEdit = null; rejectEdit = null;
        resolve(blob);
      };
      rejectEdit = function (reason) {
        rejectEdit = null; resolveEdit = null;
        reject(reason);
      };
      var url = URL.createObjectURL(file);
      var imgReady = false;
      img.onload = function () {
        imgReady = true;
        maybeInit();
      };
      img.src = url;
      var modalReady = false;
      var bsModal = new bootstrap.Modal(modal);
      function onShown(e) {
        if (e.target !== modal) return;
        modal.removeEventListener('shown.bs.modal', onShown);
        modalReady = true;
        maybeInit();
      }
      modal.addEventListener('shown.bs.modal', onShown);
      setTimeout(function () {
        if (!modalReady) { modalReady = true; maybeInit(); }
      }, 600);
      bsModal.show();
      function maybeInit() {
        if (!imgReady || !modalReady) return;
        if (cropper) { cropper.destroy(); cropper = null; }
        cropUntouched = true;
        cropper = new Cropper(img, {
          // Keeps the crop box inside the picture. At viewMode 0 it may be
          // dragged off the canvas, which puts its handles somewhere the
          // frame does not show and leaves them unreachable.
          viewMode: 1,
          // Just inside the picture rather than flush to its edge: at 1 the
          // top and bottom handles land exactly on the frame's boundary and
          // there is nothing to take hold of.
          autoCropArea: 0.92,
          responsive: true,
          restore: false,
          background: true,
          guides: true,
          center: true,
          highlight: true,
          cropBoxMovable: true,
          cropBoxResizable: true,
          toggleDragModeOnDblclick: true,
          cropend: function () { cropUntouched = false; },
          ready: function () { URL.revokeObjectURL(url); },
        });
      }
    });
  }

  function replaceFileAt(input, index, newFile) {
    var dt = new DataTransfer();
    for (var i = 0; i < input.files.length; i++) {
      dt.items.add(i === index ? newFile : input.files[i]);
    }
    input.files = dt.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function isEditable(file) {
    // Photographs and scans. A GIF or SVG would be flattened to a still JPEG.
    return /^image\/(jpeg|png|webp|bmp)$/i.test(file.type || '');
  }

  // Takes a list of files and gives back the list to use: each picture is put
  // in front of the person to crop or turn, and kept as it was if they skip it.
  // Anything that is not a picture goes through untouched.
  async function editFiles(files) {
    var list = Array.prototype.slice.call(files);
    var total = list.filter(isEditable).length;
    var index = 0;
    var out = [];
    skipAll = false;
    for (var i = 0; i < list.length; i++) {
      var f = list[i];
      if (skipAll || !isEditable(f)) { out.push(f); continue; }
      index++;
      try {
        var blob = await editImage(f, { index: index, total: total });
        out.push(new File([blob], f.name.replace(/\.[^.]+$/, '') + '-edited.jpg',
                          { type: 'image/jpeg' }));
      } catch (e) {
        out.push(f);
      }
      // The next picture opens the same dialog, which cannot be shown again
      // until it has finished closing.
      await new Promise(function (res) {
        if (!modal || modal.style.display !== 'block') return res();
        modal.addEventListener('hidden.bs.modal', function h() {
          modal.removeEventListener('hidden.bs.modal', h); res();
        });
        setTimeout(res, 1500);
      });
    }
    return out;
  }

  // Any file input marked data-image-edit offers the editor as pictures are
  // chosen, without changing how the page looks. The page's own change handler
  // is held back until the editing is over, so it only ever sees the pictures
  // as they are to be kept -- not an original followed by its edited copy.
  document.addEventListener('change', function (e) {
    var input = e.target;
    if (!input || input.type !== 'file' || !input.hasAttribute('data-image-edit')) return;
    if (input._bimsEditPass) { input._bimsEditPass = false; return; }
    var chosen = Array.prototype.slice.call(input.files || []);
    if (!chosen.some(isEditable)) return;
    e.stopImmediatePropagation();
    editFiles(chosen).then(function (result) {
      var dt = new DataTransfer();
      result.forEach(function (f) { dt.items.add(f); });
      input.files = dt.files;
      input._bimsEditPass = true;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }, true);

  window.BIMS_ImageEditor = {
    edit: editImage,
    editFiles: editFiles,
    replaceFileAt: replaceFileAt,
  };
})();

/* Mobile paste zone.
 *
 * On mobile browsers, pasting an image into a file input is not possible.
 * A contenteditable div accepts long-press → Paste on both Android and
 * iOS, and the pasted image can be extracted from the paste event's
 * clipboardData and fed into the nearest file input.
 *
 * Injected into every upload modal that has a data-paste-drop file input,
 * only on touch devices.
 */
(function () {
  var isTouch = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
  if (!isTouch) return;

  function buildPasteZone(input) {
    if (input._mobilePasteZone) return;
    var zone = document.createElement('div');
    zone.className = 'mobile-paste-zone';
    zone.contentEditable = 'true';
    zone.setAttribute('role', 'textbox');
    zone.setAttribute('aria-label', 'Long-press here to paste an image');
    zone.innerHTML = '<i class="fas fa-paste"></i> Long-press here to paste an image';

    zone.addEventListener('paste', function (e) {
      e.preventDefault();
      var items = (e.clipboardData || {}).items;
      if (!items) return;
      var files = [];
      for (var i = 0; i < items.length; i++) {
        if (items[i].kind === 'file') {
          var f = items[i].getAsFile();
          if (f) files.push(f);
        }
      }
      zone.innerHTML = '<i class="fas fa-paste"></i> Long-press here to paste an image';
      if (!files.length) return;

      var dt = new DataTransfer();
      if (input.multiple) {
        for (var j = 0; j < input.files.length; j++) dt.items.add(input.files[j]);
      }
      files.forEach(function (f) {
        var ext = (f.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
        var stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
        var named = new File([f], 'pasted-' + stamp + '.' + ext, { type: f.type });
        dt.items.add(named);
      });
      input.files = dt.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));

      var note = input.parentNode.querySelector('.paste-drop-note');
      if (!note) {
        note = document.createElement('div');
        note.className = 'form-text paste-drop-note';
        input.parentNode.appendChild(note);
      }
      note.textContent = files.length + ' file' + (files.length > 1 ? 's' : '') + ' pasted.';
      note.style.color = '#1a7f45';
      clearTimeout(note._t);
      note._t = setTimeout(function () { note.textContent = ''; }, 4000);
    });

    zone.addEventListener('input', function () {
      var imgs = zone.querySelectorAll('img');
      if (imgs.length) {
        imgs.forEach(function (i) { i.remove(); });
      }
      if (zone.textContent.trim() !== '') {
        zone.innerHTML = '<i class="fas fa-paste"></i> Long-press here to paste an image';
      }
    });

    input.parentNode.insertBefore(zone, input.nextSibling);
    input._mobilePasteZone = zone;
  }

  function wireAll(root) {
    (root || document).querySelectorAll('input[type="file"][data-paste-drop]').forEach(buildPasteZone);
  }

  document.addEventListener('DOMContentLoaded', function () {
    wireAll();
    new MutationObserver(function (muts) {
      muts.forEach(function (m) {
        m.addedNodes.forEach(function (n) {
          if (n.nodeType !== 1) return;
          if (n.matches && n.matches('input[type="file"][data-paste-drop]')) buildPasteZone(n);
          else if (n.querySelectorAll) wireAll(n);
        });
      });
    }).observe(document.body, { childList: true, subtree: true });
  });
})();

// ---------------------------------------------------------------------------
// List filters survive a reload.
//
// A list page's filter bar is plain inputs read by the page's own loadRows()
// at Submit time, so the filters live nowhere but the DOM. Refreshing, or
// coming back from an Add / Edit form, re-renders the bar empty and the page
// loads unfiltered — a supervisor who had narrowed to one branch and one month
// gets the whole register back every time they save a row.
//
// Each page's filters are remembered under its own path, so Bird Sale and
// Chicks Placement do not share a memory, and restored on the next visit to
// that same path. sessionStorage rather than localStorage: a filter is how you
// are working right now, not a preference, and it should not still be there
// tomorrow. Clear empties the memory as well as the controls.
//
// Restoring sets the controls and then asks the page to reload its rows the
// only way it can be asked from here — the Submit the page already binds — so
// nothing needs changing in the ten templates that include these filters.
// ---------------------------------------------------------------------------
(function () {
  "use strict";

  // The shared filter bar's controls. Ids rather than a class because that is
  // what _list_period_filter.html and _list_place_filter.html already emit,
  // and what each page's loadRows() reads.
  // Every control that sits in one of these filter bars. The shared partials
  // emit the f-* ids; the rest are a page's own, named without a prefix long
  // before the partials existed. Listing a selector a page does not have costs
  // nothing — it is simply never found.
  var FIELDS = [
    // shared partials (_list_period_filter / _list_place_filter)
    "#from-date", "#to-date", "#f-month", "#f-year", "#f-branch",
    "#f-warehouse", "#f-user",
    // broiler
    "#status", "#farm", "#farm-filter",
    // inventory
    "#category", "#item", "#warehouse", "#from-location", "#to-location",
    "#branch", "#charge-type", "#charge-scope"
  ];

  // How long a remembered filter stays good for. A filter is a view of a
  // moment's work, not a setting: coming back to a list after a long break
  // should show the list, not a range chosen before lunch that now hides
  // everything entered since. Thirty minutes of not touching the page is the
  // same idle window the rest of the ERP treats as "stepped away".
  var MAX_IDLE_MS = 30 * 60 * 1000;

  var KEY_PREFIX = "listfilter:";
  var DEFAULTS_PREFIX = "listfilterdef:";

  function key() { return KEY_PREFIX + window.location.pathname; }

  // Whether this browser will let us keep anything at all. Edge's Tracking
  // Prevention, Safari's partitioning and every private-browsing mode can
  // refuse sessionStorage outright -- the read throws, or returns nothing that
  // was just written. A filter bar that silently forgets is the result, and it
  // looks exactly like a bug in the page: the person picks a branch, refreshes
  // and the branch is gone, with nothing in the console to explain it.
  //
  // So storage is never assumed. It is tested once, and when it is unavailable
  // the filter is carried in the address bar instead, which no privacy setting
  // can take away and which survives a refresh, a bookmark and a link sent to
  // someone else.
  var storageWorks = (function () {
    try {
      var probe = "listfilter:probe";
      sessionStorage.setItem(probe, "1");
      var ok = sessionStorage.getItem(probe) === "1";
      sessionStorage.removeItem(probe);
      return ok;
    } catch (e) { return false; }
  })();

  // The filter as it travels in the query string. Only the controls that are
  // set are written, under their own ids, so the URL stays readable.
  function urlValues() {
    var out = null;
    try {
      var params = new URLSearchParams(window.location.search);
      // Coming back from a form: the filter travelled as _lf so it would not
      // be mistaken for one of the form's own fields. Unpack it once, then
      // put it in the address bar properly so a refresh from here works too.
      if (params.has("_lf")) {
        var carried = new URLSearchParams(params.get("_lf"));
        var recovered = {};
        FIELDS.forEach(function (sel) {
          var n = sel.replace(/^#/, "");
          if (carried.has(n)) recovered[sel] = carried.get(n);
        });
        if (Object.keys(recovered).length) {
          writeUrl(recovered);
          return recovered;
        }
      }
      FIELDS.forEach(function (sel) {
        var name = sel.replace(/^#/, "");
        if (params.has(name)) {
          out = out || {};
          out[sel] = params.get(name);
        }
      });
    } catch (e) { return null; }
    return out;
  }

  function writeUrl(values) {
    try {
      var params = new URLSearchParams(window.location.search);
      FIELDS.forEach(function (sel) { params.delete(sel.replace(/^#/, "")); });
      Object.keys(values || {}).forEach(function (sel) {
        if (values[sel]) params.set(sel.replace(/^#/, ""), values[sel]);
      });
      var qs = params.toString();
      // replaceState, not pushState: refining a filter is not a new page, and
      // Back should leave the list rather than walk every filter that was
      // tried on the way to this one.
      window.history.replaceState(null, "",
        window.location.pathname + (qs ? "?" + qs : "") + window.location.hash);
    } catch (e) { /* older browser: the filter simply is not carried */ }
  }

  // Who the page says is signed in, stamped on <body> by base.html. Blank on a
  // login or other anonymous page.
  function sessionUser() {
    return (document.body && document.body.getAttribute("data-session-user")) || "";
  }

  // The page's own defaults, kept apart from the filter. Needed because the
  // only moment the controls are reliably at their defaults is the first visit
  // in a tab: after that a plain reload may have refilled them from session
  // history, so the live values cannot be trusted to define "unfiltered".
  function defaultsKey() { return DEFAULTS_PREFIX + window.location.pathname; }

  // The values of the record as it stands, or null when nothing is stored.
  function storedValues() {
    try {
      var rec = JSON.parse(sessionStorage.getItem(key()) || "null");
      return (rec && rec.v === 1 && rec.values) ? rec.values : null;
    } catch (e) { return null; }
  }

  function storedDefaults() {
    try {
      var raw = sessionStorage.getItem(defaultsKey());
      if (!raw) return null;
      var d = JSON.parse(raw);
      return (d && typeof d === "object" && d.values) ? d.values : null;
    } catch (e) { return null; }
  }

  function rememberDefaults(values) {
    try {
      if (!values) return;
      sessionStorage.setItem(defaultsKey(), JSON.stringify({ v: 1, values: values }));
    } catch (e) { /* blocked storage: fall back to the live snapshot */ }
  }

  // Drop every remembered filter, across all pages, not just this one. Used
  // when the session owner changes and when the tab lands on an anonymous
  // page -- the logged-out case -- because what is stale then is the whole
  // set, and the next sign-in will not visit each page to find out.
  function forgetAll() {
    try {
      var doomed = [];
      for (var i = 0; i < sessionStorage.length; i++) {
        var k = sessionStorage.key(i);
        if (k && (k.indexOf(KEY_PREFIX) === 0 ||
                  k.indexOf(DEFAULTS_PREFIX) === 0)) doomed.push(k);
      }
      doomed.forEach(function (k) { sessionStorage.removeItem(k); });
    } catch (e) { /* blocked storage: nothing was stored to begin with */ }
  }


  // The date inputs are special: every one of these pages rewrites them to its
  // own range on load, so yesterday's stored dates are never equal to today's
  // defaults. Judging "is this filtered" on them alone meant that the morning
  // after a filter was set -- or any time the page's range moved -- a branch
  // or status the person had chosen was read as the page's own view and
  // dropped. The dates are still remembered and restored; they just do not get
  // a vote on whether a filter exists.
  var DATE_FIELDS = ["#from-date", "#to-date"];

  function isDateField(sel) {
    return DATE_FIELDS.indexOf(sel) !== -1;
  }

  function store() {
    try {
      // Nothing to remember when the controls are the page's own defaults:
      // writing them back would mean Clear appears not to have taken (the key
      // is there again the moment Submit runs), and would pin today's default
      // range into a session that should pick up tomorrow's.
      var values = {};
      FIELDS.forEach(function (sel) {
        var el = document.querySelector(sel);
        if (el && el.value) values[sel] = el.value;
      });
      if (defaults && !isFiltered(values)) {
        if (!storageWorks) writeUrl({});
        sessionStorage.removeItem(key());
        return;
      }
      // Without storage the address bar is the only place left to keep this.
      if (!storageWorks) writeUrl(values);
      if (Object.keys(values).length) {
        // Stamped with who stored it and when, so restore() can refuse a
        // record belonging to a previous sign-in or to a sitting long enough
        // ago that the person has moved on. Older records are a bare map of
        // selectors and read as neither; restore() discards those.
        sessionStorage.setItem(key(), JSON.stringify({
          v: 1,
          user: sessionUser(),
          at: Date.now(),
          values: values
        }));
      } else {
        sessionStorage.removeItem(key());
      }
    } catch (e) { /* private mode, blocked storage: filters just do not persist */ }
  }

  // Put a set of remembered values back into the controls. Shared by both
  // sources, because a filter read from the address bar deserves the same
  // care as one read from storage.
  function apply(data) {
    var applied = false;
    Object.keys(data || {}).forEach(function (sel) {
      var el = document.querySelector(sel);
      if (!el) return;
      // Only restore a value the control still offers: a branch that has since
      // been removed, or a year no longer in the financial-year list, would
      // otherwise leave the select showing nothing while the page filtered by
      // it invisibly.
      if (el.tagName === "SELECT") {
        var ok = Array.prototype.some.call(el.options, function (o) {
          return o.value === data[sel];
        });
        if (!ok) return;
      }
      el.value = data[sel];
      applied = true;
      // Select2 mirrors the native select, so it has to be told.
      if (window.jQuery && window.jQuery(el).data("select2")) {
        window.jQuery(el).trigger("change.select2");
      }
    });
    return applied;
  }

  function restore() {
    // The address bar first when storage is unavailable: it is the only copy
    // there is, and it is as trustworthy as the person's own URL.
    if (!storageWorks) {
      var fromUrl = urlValues();
      return fromUrl ? apply(fromUrl) : false;
    }

    var rec;
    try {
      rec = JSON.parse(sessionStorage.getItem(key()) || "null");
    } catch (e) { return false; }
    if (!rec || typeof rec !== "object") return false;

    // Anything without the stamp is from before filters were dated -- a
    // record whose age and owner cannot be checked, so it is not trusted.
    if (rec.v !== 1 || !rec.values) {
      try { sessionStorage.removeItem(key()); } catch (e) { /* ignore */ }
      return false;
    }

    // A different signed-in user, or none at all: not this session's filter.
    if ((rec.user || "") !== sessionUser()) {
      forgetAll();
      return false;
    }

    // Too long since it was last used. Expiring on idle rather than on a
    // fixed lifetime means a filter survives as long as it is being worked
    // with and lapses once it is not.
    if (!rec.at || (Date.now() - rec.at) > MAX_IDLE_MS) {
      try { sessionStorage.removeItem(key()); } catch (e) { /* ignore */ }
      return false;
    }

    return apply(rec.values);
  }

  // What the page itself loads with, captured before anything is restored, so
  // "filtered" can mean "not what this page would show on its own" rather than
  // "some control has a value" — every one of these pages defaults to the last
  // seven days, and calling that a filter would mark every page all the time.
  var defaults = null;

  function snapshot() {
    var out = {};
    FIELDS.forEach(function (sel) {
      var el = document.querySelector(sel);
      if (el) out[sel] = el.value;
    });
    return out;
  }

  // A filter the person set, as opposed to the view the page opens with. The
  // question is asked against the stored record where there is one, not only
  // against the live controls: the page rewrites its date range whenever it
  // reloads, so by the time this runs the dates may be the page's newest
  // default rather than anything that was chosen, and comparing those would
  // call a real filter "no filter" and throw it away.
  // `record`, when given, is the set of values being judged -- what store() is
  // about to write, or what was read back. Otherwise the live controls are
  // read, which is what the mark on the bar is about.
  //
  // `settled` says the page has finished loading and the date inputs can be
  // believed. During a restore they cannot: the page rewrites its own range on
  // load, so a date that differs then says nothing about what the person
  // chose. Sixteen of these pages offer a date range and nothing else, so
  // discounting dates everywhere would mean they could never be filtered at
  // all -- the dates have to count, just not while they are still moving.
  function isFiltered(record, settled) {
    if (!defaults) return false;
    var anyValue = false;
    var differs = false;
    FIELDS.forEach(function (sel) {
      var el = document.querySelector(sel);
      if (!el) return;
      var value = (record && Object.prototype.hasOwnProperty.call(record, sel))
        ? record[sel] : el.value;
      if (value) anyValue = true;
      if (value !== (defaults[sel] || "")) {
        if (!isDateField(sel) || settled !== false) differs = true;
      }
    });
    // Everything blank is the widest view there is, whatever the page happened
    // to load with: GC Payment's own Clear empties the dates rather than
    // restoring its default range, and that is not a filter either.
    return anyValue && differs;
  }

  // The bar carries the mark, not each control: the point is "this list is not
  // the whole list", which is one fact about the page.
  function filterBar() {
    // Most of these pages mark the bar .list-filter-row, but not all: Sales
    // Invoice and General Purchase just use a plain .row, so the mark has to
    // be hung on whatever row actually holds Submit rather than on a class
    // that may not be there.
    var submit = document.querySelector("#filter-submit");
    if (!submit) return null;
    return document.querySelector(".list-filter-row")
        || submit.closest(".row")
        || submit.parentElement;
  }

  function paint() {
    var bar = filterBar();
    if (!bar) return;
    // Judged against what is stored, so the mark agrees with what will still
    // be there after a reload rather than with a date range the page has just
    // rewritten underneath it.
    var on = isFiltered(storageWorks ? storedValues() : urlValues());
    // Both classes: .lf-active styles a .list-filter-row bar, and .lf-marked
    // carries the same look on a page whose bar is a plain row.
    bar.classList.toggle("lf-active", on);
    var clear = document.querySelector("#filter-clear");
    if (clear) {
      clear.classList.toggle("btn-warning", on);
      clear.classList.toggle("btn-outline-secondary", !on);
      clear.title = on ? "Filters are applied — clear them" : "Clear filters";
    }
  }

  // The page asks for its rows as soon as it loads, using the default range.
  // When a filter is about to be restored that request is already wrong, and
  // it is in flight before this file gets a turn -- so the restored filter
  // fires a second one and the two race. Whichever answers last paints the
  // table, and when the unfiltered reply came second it overwrote the filtered
  // rows: the bar showed one branch while the table listed every branch, a
  // screen that lies about what it is showing.
  //
  // So the losing reply is never delivered. jQuery's getJSON is wrapped for
  // the moment between the page starting up and the restore being applied: a
  // request sent in that window still goes out, but its success handler is
  // dropped if a filter was restored, because it describes a view the person
  // did not ask for. Nothing is cancelled and no page is modified -- the
  // answer is simply not painted.
  function holdFirstFetch() {
    var $ = window.jQuery;
    if (!$ || !$.getJSON) return function () {};
    var original = $.getJSON;
    var suppress = false;
    var done = false;

    // The held reply, kept rather than thrown away: see settle() below for
    // why a dropped reply is only safe when another one is coming.
    var held = null;

    $.getJSON = function (url, data, success) {
      if (typeof data === "function") { success = data; data = undefined; }
      var wrapped = typeof success === "function"
        ? function () {
            // Dropped only while the restore is still pending and a filter
            // turned out to be stored; everything after is the page's own.
            if (suppress) {
              var self = this, args = arguments;
              held = function () { return success.apply(self, args); };
              return;
            }
            return success.apply(this, arguments);
          }
        : success;
      return original.call($, url, data, wrapped);
    };

    return function settle(filterRestored) {
      if (done) return;
      done = true;
      suppress = !!filterRestored;
      // Restore jQuery before the filtered request is sent, so only the
      // page's own start-up reply is ever held back.
      $.getJSON = original;
      if (suppress) {
        // Dropping the start-up reply is only safe where the page answers
        // Submit with a fresh request. Some lists fetch once and then filter
        // the rows they already hold -- their Submit sends nothing, so the
        // reply dropped here was the only one coming and the table was left
        // permanently empty: not a lost filter but a lost list.
        //
        // So the reply is held rather than discarded. If a later request
        // arrives it was the refetch, and the held one is genuinely stale.
        // If none does, the page does not refetch, and the held reply is
        // delivered after all -- late, but the rows are there.
        var sawRefetch = false;
        $.getJSON = function () {
          sawRefetch = true;
          $.getJSON = original;
          return original.apply($, arguments);
        };
        setTimeout(function () {
          suppress = false;
          if ($.getJSON !== original) { $.getJSON = original; }
          if (!sawRefetch && held) { try { held(); } catch (e) { /* page's own */ } }
          held = null;
        }, 1200);
      }
    };
  }

  // A plain reload (Ctrl+R, F5) is not a fresh load: Chrome and Firefox refill
  // form controls from session history before any script runs, which is good
  // for a half-typed form and wrong for a filter bar. It left the restored
  // filter sitting in the controls at the moment snapshot() ran, so the page's
  // own defaults were recorded as the filter itself -- isFiltered() then saw
  // nothing out of the ordinary, store() dropped the memory as redundant, and
  // the list came back unfiltered. A hard reload skips that refill, which is
  // exactly why Ctrl+Shift+R held the filter while Ctrl+R lost it.
  //
  // Turning the refill off hands the page back its own defaults and leaves
  // this file as the single thing that decides what a filter bar shows.
  // Append the current filter to the links that leave this list page, so the
  // round trip through a form comes back to the same view. Same-origin links
  // to this page or its sub-paths only, and never a download, an anchor or
  // anything the person opens in a new tab deliberately.
  function keepFilterOnLinks() {
    document.addEventListener("click", function (ev) {
      var a = ev.target && ev.target.closest ? ev.target.closest("a[href]") : null;
      if (!a) return;
      if (a.target && a.target !== "_self") return;
      if (a.hasAttribute("download")) return;
      var href = a.getAttribute("href") || "";
      if (!href || href.charAt(0) === "#" || /^[a-z]+:/i.test(href)) return;

      var current = urlValues();
      if (!current) return;
      try {
        var url = new URL(a.href, window.location.href);
        if (url.origin !== window.location.origin) return;
        // Carry it as the return address, not as a filter on the form itself:
        // the form has no filter bar, and a stray f-branch in its query string
        // would mean nothing there.
        url.searchParams.set("_lf", window.location.search.replace(/^\?/, ""));
        a.href = url.toString();
      } catch (e) { /* leave the link alone */ }
    }, true);
  }

  // On a form reached from a filtered list, rewrite the links that lead back
  // to that list -- Cancel, breadcrumbs -- so they return to the filtered view
  // rather than to the bare list. The filter rides in _lf, put there by
  // keepFilterOnLinks when the person left the list.
  function restoreReturnLinks() {
    var carried;
    try {
      carried = new URLSearchParams(window.location.search).get("_lf");
    } catch (e) { return; }
    if (!carried) return;

    Array.prototype.forEach.call(document.querySelectorAll("a[href]"), function (a) {
      var href = a.getAttribute("href") || "";
      if (!href || href.charAt(0) === "#" || /^[a-z]+:/i.test(href)) return;
      try {
        var url = new URL(a.href, window.location.href);
        if (url.origin !== window.location.origin) return;
        // Only the list this form belongs to: its path is a prefix of ours.
        var here = window.location.pathname.replace(/[^/]*\/?$/, "");
        if (url.pathname === window.location.pathname) return;
        if (here.indexOf(url.pathname) !== 0) return;
        if (url.search) return;
        a.href = url.pathname + "?" + carried + url.hash;
      } catch (e) { /* leave it */ }
    });
  }

  function disableFormRestore() {
    FIELDS.forEach(function (sel) {
      var el = document.querySelector(sel);
      if (el) el.setAttribute("autocomplete", "off");
    });
  }

  // Installed at once, not on DOMContentLoaded: the page's start-up request
  // goes out from its own jQuery ready handler, which runs first.
  var settleFirstFetch = holdFirstFetch();

  document.addEventListener("DOMContentLoaded", function () {
    // Landing on a page with nobody signed in means the session has ended --
    // logged out, or expired and bounced to the login form. Every remembered
    // filter goes, here rather than on the next list page, because the login
    // form is the one page the person is guaranteed to pass through and it has
    // no filter bar of its own to run this check later.
    if (!sessionUser()) {
      forgetAll();
      settleFirstFetch(false);
      return;
    }

    var submit = document.querySelector("#filter-submit");
    // Not a list page. It may still be the form a list page sent us to, in
    // which case the way back carries the filter that was in force.
    if (!submit) {
      restoreReturnLinks();
      settleFirstFetch(false);
      return;
    }

    disableFormRestore();

    // Leaving the list for a form and coming back loses the query string: the
    // Cancel link on each form points at the bare list URL, so a filter held
    // only in the address bar would not survive Add -> Cancel. Rather than
    // edit every form template, the links that lead off this page carry the
    // filter with them, and the form's own Cancel then returns to a URL that
    // still has it. Only matters where storage is blocked; where it works the
    // filter is remembered anyway.
    if (!storageWorks) keepFilterOnLinks();

    // Deferred, and not only so the page's own Submit handler is bound: most
    // of these pages set a default range (the last seven days) on load, and
    // doing that *after* a restore would quietly overwrite the dates the
    // person had chosen while leaving the other filters alone. Running last
    // means the remembered values win, which is the whole point.
    setTimeout(function () {
      // The page has now set its own defaults. Remembered ones win when they
      // exist, because on a plain reload the live controls may still hold the
      // previous filter and would otherwise be mistaken for defaults; the
      // snapshot is the fallback on a first visit, when there is nothing
      // stored yet and the controls are genuinely untouched.
      defaults = storedDefaults() || snapshot();
      rememberDefaults(defaults);

      // Re-asking for the rows is a second request, and the page has already
      // sent its own for the default range. Two requests are a race: whichever
      // answers last paints the table, so when the page's unfiltered reply
      // arrived second it overwrote the filtered rows -- leaving the filter
      // bar showing a branch while the table showed every branch, which is
      // worse than not restoring at all, because the screen then lies about
      // what it is listing.
      //
      // Asking again is still the only way in (these pages expose no hook to
      // amend a request in flight), so the second answer is made the one that
      // counts: the table is repainted when this reply lands, whatever order
      // the two arrive in.
      var restored = restore();
      // Release the wrapper before asking again, so the filtered reply is
      // delivered normally and only the stale one is dropped.
      settleFirstFetch(restored);
      if (restored) submit.click();
      paint();
    }, 0);

    submit.addEventListener("click", function () { store(); paint(); });

    // Re-stamp the record whenever the person comes back to this tab with the
    // filter still applied, so "idle" measures time away rather than time
    // since the filter was first set. Without this, a filter being used for
    // over half an hour would lapse mid-work on the next refresh.
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden && isFiltered()) store();
    });
    // Typing in a date or picking a branch re-marks the bar straight away,
    // without waiting for Submit, so the mark always describes the controls.
    FIELDS.forEach(function (sel) {
      var el = document.querySelector(sel);
      if (el) { el.addEventListener("change", paint); el.addEventListener("input", paint); }
    });

    // Clearing has to exist wherever filters are remembered, or a range chosen
    // once is the range you get for the rest of the session with no way back
    // but retyping it. Seven of these pages ship a Clear button; the rest get
    // one here, beside their Submit, rather than editing a template apiece.
    var clear = document.querySelector("#filter-clear");
    if (!clear) {
      clear = document.createElement("button");
      clear.type = "button";
      clear.id = "filter-clear";
      clear.className = "btn btn-outline-secondary";
      clear.textContent = "Clear";
      submit.insertAdjacentElement("afterend", clear);
      // The page has no handler of its own for a button it never had, so this
      // one empties the controls and asks for the unfiltered list. The dates
      // are left to the page's own default by reloading without a memory.
      clear.addEventListener("click", function () {
        try { sessionStorage.removeItem(key()); } catch (e) { /* ignore */ }
        if (!storageWorks) writeUrl({});
        // Put the controls back to what the page loaded with and ask it to
        // reload its own rows, rather than reloading the browser: a round trip
        // makes Clear feel like it did not take until the page comes back.
        if (defaults) {
          FIELDS.forEach(function (sel) {
            var el = document.querySelector(sel);
            if (!el) return;
            el.value = defaults[sel] || "";
            if (window.jQuery && window.jQuery(el).data("select2")) {
              window.jQuery(el).trigger("change.select2");
            }
          });
        }
        paint();
        submit.click();
      });
    } else {
      // The page clears its own controls; this only drops the memory, so the
      // next visit starts from the page's defaults rather than the old filter.
      clear.addEventListener("click", function () {
        try { sessionStorage.removeItem(key()); } catch (e) { /* ignore */ }
        if (!storageWorks) writeUrl({});
        // The page's own handler resets its controls in the same click, and
        // may touch ones this file does not track. Repainting after it has run
        // keeps the mark honest rather than leaving it set on a cleared bar.
        setTimeout(paint, 0);
      });
    }
  });
})();


/* Send WhatsApp from a document's own page.
 *
 *   BIMS_WhatsApp.open({ module: 'bird_sale', docId: 12, csrf: token, onSent: fn, onFailed: fn })
 *   BIMS_WhatsApp.openMany({ module, docIds: [..], csrf, onSent: fn(docId), onFailed: fn(docId) })
 *
 * open() is a dialog for one document: who it goes to, which approved template,
 * the finished message (when the template has its wording on file) or the
 * values that go into it, and what has already been sent. openMany() sends one
 * template to the customers on several documents, one after the other, with a
 * preview of the message each of them would get.
 *
 * Both send through the endpoint the Messaging > Transaction screen uses, so the
 * permission check, the duplicate guard and the WhatsApp History log are the
 * ones already there. Meta owns the text of an approved template; what is shown
 * as the message is the wording pasted into the template record, filled with
 * this document's values -- a preview, not what Meta renders.
 */
(function () {
  function esc(v) { return window.escapeHtml ? window.escapeHtml(String(v == null ? '' : v)) : String(v); }

  // ---- shared: styles and the message preview ---------------------------
  function ensureStyles() {
    if (document.getElementById('bimsWaStyle')) return;
    var st = document.createElement('style');
    st.id = 'bimsWaStyle';
    st.textContent =
      '.wa-bubble{background:#dcf8c6;border-radius:10px 10px 10px 2px;padding:.6rem .75rem;font-size:.9rem;' +
        'line-height:1.4;color:#1f2d23;box-shadow:0 1px 1px rgba(0,0,0,.12);word-break:break-word}' +
      '.wa-bubble-wrap{background:#efe7dd;border-radius:8px;padding:.75rem}' +
      '.wa-val{font-weight:600}' +
      '.wa-miss{background:#f8d7da;color:#842029;border-radius:4px;padding:0 4px;font-weight:600}' +
      '.wa-fields td{vertical-align:middle}' +
      '#bimsWaManyTable tr[data-i]{cursor:pointer}' +
      '#bimsWaManyTable tr.wam-focus>td{background:rgba(31,168,85,.09)}' +
      '#bimsWaMany thead th{position:sticky;top:0;background:var(--bs-body-bg,#fff);z-index:1}';
    document.head.appendChild(st);
  }

  // The wording with each numbered placeholder replaced by its value. A blank
  // value is shown as a red [FieldName] marker and reported back, because a
  // message with an empty field is one WhatsApp will not accept.
  function fill(body, names, get) {
    var missing = [];
    var html = esc(body)
      .replace(/\*([^*\n]+)\*/g, '<b>$1</b>')
      .replace(/(^|[\s(])_([^_\n]+)_(?=[\s).,!?]|$)/g, '$1<i>$2</i>')
      .replace(/\{\{\s*(\d+)\s*\}\}/g, function (m, n) {
        var name = names[Number(n) - 1];
        var v = name == null ? '' : get(name);
        if (v === '' || v == null) {
          if (name != null && missing.indexOf(name) < 0) missing.push(name);
          return '<span class="wa-miss">[' + esc(name == null ? '{{' + n + '}}' : name) + ']</span>';
        }
        return '<span class="wa-val">' + esc(v) + '</span>';
      })
      .replace(/\n/g, '<br>');
    return { html: html, missing: missing };
  }
  function blanks(names, get) {
    var out = [];
    names.forEach(function (n) { var v = get(n); if ((v === '' || v == null) && out.indexOf(n) < 0) out.push(n); });
    return out;
  }
  function bubble(html) { return '<div class="wa-bubble-wrap"><div class="wa-bubble">' + html + '</div></div>'; }
  function plain(err, t) {
    if (/template/i.test(err) && /(not found|approved)/i.test(err)) {
      return 'WhatsApp does not have an approved template named "' + t.template_name +
             '" right now. Check its status in the LemIn AI dashboard, then fix the name or language under ' +
             'Messaging > WhatsApp Templates.';
    }
    return err;
  }
  function fetchJson(url, opts) {
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (b) { return { status: r.status, body: b, ok: r.ok }; });
    });
  }
  function sendOne(csrf, module, docId, templateId, force) {
    return fetchJson('/whatsapp-transaction/send/', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf || '', 'X-Bims-Own-Errors': '1' },
      body: JSON.stringify({ module: module, doc_id: docId, template_id: templateId, force: !!force }),
    });
  }
  var OK = /^(sent|delivered|read|mocked)$/;

  // ======================================================================
  // One document
  // ======================================================================
  var modal, state = {};

  function build() {
    if (modal) return;
    ensureStyles();
    var div = document.createElement('div');
    div.innerHTML =
      '<div class="modal fade" id="bimsWaSend" tabindex="-1" aria-hidden="true">' +
        // Scrollable: a customer with a long send history, or a short window,
        // would otherwise push the Send button off the bottom of the screen.
        '<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable">' +
          '<div class="modal-content">' +
            '<div class="modal-header py-2">' +
              '<h6 class="modal-title"><i class="fab fa-whatsapp text-success me-1"></i>Send WhatsApp</h6>' +
              '<button type="button" class="btn-close" data-bs-dismiss="modal"></button>' +
            '</div>' +
            '<div class="modal-body" id="bimsWaBody"></div>' +
            '<div class="modal-footer py-2">' +
              '<button type="button" class="btn btn-sm btn-light" data-bs-dismiss="modal">Close</button>' +
              '<button type="button" class="btn btn-sm btn-success" id="bimsWaGo" disabled>' +
                '<i class="fab fa-whatsapp me-1"></i>Send</button>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(div.firstChild);
    modal = document.getElementById('bimsWaSend');
    document.getElementById('bimsWaGo').addEventListener('click', function () { send(false); });
    modal.addEventListener('change', function (e) { if (e.target.id === 'bimsWaTemplate') paintMessage(); });
  }

  function selectedTemplate() {
    var sel = document.getElementById('bimsWaTemplate');
    if (!sel || !state.data) return null;
    return state.data.templates.filter(function (t) { return String(t.id) === sel.value; })[0] || null;
  }
  function paramGetter(t) {
    var map = {};
    t.params.forEach(function (p) { map[p.name] = p.value; });
    return function (name) { return map[name]; };
  }
  function canSend(d) { return !!(d && d.mobile_ok && d.templates.length); }

  function paintMessage() {
    var t = selectedTemplate();
    var box = document.getElementById('bimsWaMessage');
    if (!box) return;
    if (!t) { box.innerHTML = ''; state.missing = []; return; }
    var get = paramGetter(t);
    var names = t.params.map(function (p) { return p.name; });
    var html = '', missing;
    if (t.body_preview) {
      var f = fill(t.body_preview, names, get);
      missing = f.missing;
      html += bubble(f.html);
    } else {
      missing = blanks(names, get);
      html += t.params.length
        ? '<div class="small text-muted mb-1">Values going into the message</div>' +
          '<table class="table table-sm table-bordered mb-0 small wa-fields"><tbody>' +
          t.params.map(function (p, i) {
            return '<tr><td class="text-muted" style="width:40%">{{' + (i + 1) + '}} ' + esc(p.name) + '</td><td>' +
                   (p.value ? esc(p.value) : '<span class="wa-miss">empty</span>') + '</td></tr>';
          }).join('') + '</tbody></table>' +
          '<div class="form-text">Paste this template\'s approved wording under Messaging &rsaquo; WhatsApp Templates to see the whole message here.</div>'
        : '<div class="small text-muted">This template has no fields to fill.</div>';
    }
    if (missing.length) {
      html += '<div class="alert alert-warning small py-2 mt-2 mb-0"><i class="fas fa-triangle-exclamation me-1"></i>' +
        missing.length + (missing.length === 1 ? ' field is' : ' fields are') + ' empty: <b>' +
        missing.map(esc).join(', ') + '</b>. WhatsApp usually refuses a message with a blank field.</div>';
    }
    // The values, for checking, once the message itself is on screen.
    if (t.body_preview && t.params.length) {
      html += '<details class="mt-2"><summary class="small text-muted">Fields</summary>' +
        '<table class="table table-sm table-bordered mt-1 mb-0 small wa-fields"><tbody>' +
        t.params.map(function (p, i) {
          return '<tr><td class="text-muted" style="width:40%">{{' + (i + 1) + '}} ' + esc(p.name) + '</td><td>' +
                 (p.value ? esc(p.value) : '<span class="wa-miss">empty</span>') + '</td></tr>';
        }).join('') + '</tbody></table></details>';
    }
    box.innerHTML = html;
    state.missing = missing;
  }

  function render(d) {
    state.data = d;
    var doc = d.document;
    var html =
      '<div class="d-flex justify-content-between align-items-start mb-2">' +
        '<div><div class="fw-semibold">' + esc(doc.party_name) + '</div>' +
        (d.mobile
          ? '<div class="small ' + (d.mobile_ok ? 'text-muted' : 'text-danger') + '"><i class="fab fa-whatsapp me-1"></i>' + esc(d.mobile) +
            (d.mobile_ok ? '' : ' &mdash; not a valid mobile number') + '</div>'
          : '<div class="small text-danger">No mobile number on this customer. Add one on the customer record first.</div>') +
        '</div>' +
        '<div class="text-end small text-muted">' + esc(doc.label) + '<br><b>' + esc(doc.doc_no || '-') + '</b> &middot; ' +
        esc(doc.date) + '<br>' + esc(doc.amount) + '</div>' +
      '</div>';
    if (!d.templates.length) {
      html += '<div class="alert alert-warning small py-2 mb-2">No active WhatsApp template is set up for this ' +
              'document. Add one under Messaging &rsaquo; WhatsApp Templates.</div>';
    } else {
      html += '<label class="form-label small mb-1" for="bimsWaTemplate">Template</label>' +
        '<select id="bimsWaTemplate" class="form-select form-select-sm mb-2">' +
        d.templates.map(function (t) {
          return '<option value="' + t.id + '"' + (String(t.id) === String(state.keep) ? ' selected' : '') + '>' + esc(t.name) + '</option>';
        }).join('') + '</select><div id="bimsWaMessage" class="mb-2"></div>';
    }
    if (d.history.length) {
      var nOk = d.history.filter(function (h) { return OK.test(h.status); }).length;
      var nBad = d.history.length - nOk;
      html += '<details' + (nBad && !nOk ? ' open' : '') + '><summary class="small text-muted">History &middot; ' +
        '<span class="text-success">' + nOk + ' sent</span>' +
        (nBad ? ' &middot; <span class="text-danger">' + nBad + ' failed</span>' : '') + '</summary>' +
        '<ul class="list-unstyled small mb-0 mt-1">' +
        d.history.map(function (h) {
          return '<li><i class="fas fa-' + (OK.test(h.status) ? 'check text-success' : 'xmark text-danger') + ' me-1"></i>' +
                 esc(h.sent_at) + ' &middot; ' + esc(h.template_name) + ' &middot; ' + esc(h.status) +
                 (h.sent_by ? ' &middot; ' + esc(h.sent_by) : '') + '</li>';
        }).join('') + '</ul></details>';
    }
    document.getElementById('bimsWaBody').innerHTML = html;
    paintMessage();
    document.getElementById('bimsWaGo').disabled = !canSend(d);
  }

  function load() {
    return fetchJson('/whatsapp-transaction/document/?module=' + encodeURIComponent(state.module) +
                     '&doc_id=' + encodeURIComponent(state.docId), { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error(r.body.error || 'Could not load this document.');
        return r.body;
      });
  }

  async function send(force) {
    var t = selectedTemplate();
    var go = document.getElementById('bimsWaGo');
    if (!t || !state.data) return;
    if (!force) {
      if (state.missing && state.missing.length &&
          !(await window.bimsConfirm('These fields are empty: ' + state.missing.join(', ') +
            '.\n\nWhatsApp usually refuses a message with a blank field. Send anyway?',
            { title: 'Empty fields', confirmText: 'Send anyway', danger: false }))) return;
      var before = state.data.history.some(function (h) {
        return h.template_name === t.template_name && /^(sent|delivered|read)$/.test(h.status);
      });
      if (before && !(await window.bimsConfirm(
        'This document has already been sent with "' + t.name + '". Send it again?',
        { title: 'Already sent', confirmText: 'Send again', danger: false }))) return;
    }
    go.disabled = true;
    state.keep = t.id;
    try {
      var res = await sendOne(state.csrf, state.module, state.docId, t.id, force);
      if (res.status === 409 && res.body.duplicate) {
        if (await window.bimsConfirm(res.body.error,
            { title: 'Sent just now', confirmText: 'Send again', danger: false })) {
          return send(true);
        }
        return;
      }
      if (res.body.success) {
        window.showToast('success', 'WhatsApp message sent.');
        if (state.onSent) state.onSent(res.body);
      } else {
        window.showToast('danger', plain(res.body.error || 'The message could not be sent.', t));
        if (state.onFailed) state.onFailed(res.body);
      }
      render(await load());
    } catch (e) {
      window.showToast('danger', e.message || 'The message could not be sent.');
    } finally {
      go.disabled = !canSend(state.data);
    }
  }

  // ======================================================================
  // Several documents
  // ======================================================================
  var many, st = {};

  function buildMany() {
    if (many) return;
    ensureStyles();
    var div = document.createElement('div');
    div.innerHTML =
      '<div class="modal fade" id="bimsWaMany" tabindex="-1" aria-hidden="true" data-bs-backdrop="static">' +
        '<div class="modal-dialog modal-xl modal-dialog-centered modal-dialog-scrollable">' +
          '<div class="modal-content">' +
            '<div class="modal-header py-2">' +
              '<h6 class="modal-title"><i class="fab fa-whatsapp text-success me-1"></i>Send WhatsApp to <span id="bimsWaManyN"></span></h6>' +
              '<button type="button" class="btn-close" data-bs-dismiss="modal"></button>' +
            '</div>' +
            '<div class="modal-body" id="bimsWaManyBody"></div>' +
            '<div class="modal-footer py-2 justify-content-between">' +
              '<span class="small text-muted" id="bimsWaManyCount"></span>' +
              '<div class="d-flex gap-2">' +
                '<button type="button" class="btn btn-sm btn-outline-danger d-none" id="bimsWaManyRetry">' +
                  '<i class="fas fa-rotate-right me-1"></i>Retry failed</button>' +
                '<button type="button" class="btn btn-sm btn-light" data-bs-dismiss="modal" id="bimsWaManyClose">Close</button>' +
                '<button type="button" class="btn btn-sm btn-success" id="bimsWaManyGo" disabled>' +
                  '<i class="fab fa-whatsapp me-1"></i>Send</button>' +
              '</div>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(div.firstChild);
    many = document.getElementById('bimsWaMany');
    document.getElementById('bimsWaManyGo').addEventListener('click', function () { run(false); });
    document.getElementById('bimsWaManyRetry').addEventListener('click', retryFailed);
    many.addEventListener('change', function (e) {
      if (e.target.id === 'bimsWaManyTpl') { defaults(); paint(); }
      else if (e.target.classList.contains('wam-pick')) { st.docs[e.target.dataset.i].on = e.target.checked; count(); }
      else if (e.target.id === 'bimsWaManyAll') {
        st.docs.forEach(function (d) { if (usable(d)) d.on = e.target.checked; }); paint();
      }
    });
    many.addEventListener('click', function (e) {
      var pick = e.target.closest('[data-pick]');
      if (pick && !st.running) { quickPick(pick.dataset.pick); return; }
      if (e.target.closest('input,button,a,label')) return;
      var tr = e.target.closest('tr[data-i]');
      if (tr) { st.focus = Number(tr.dataset.i); paint(); }
    });
  }

  function tpl() {
    var sel = document.getElementById('bimsWaManyTpl');
    return sel ? st.data.templates.filter(function (t) { return String(t.id) === sel.value; })[0] : null;
  }
  function usable(d) { return d.mobile_ok && !st.running; }
  function sentWith(d, t) {
    var all = t ? d.sent.filter(function (s) { return s.template_name === t.template_name; }) : [];
    return all.length ? all[all.length - 1] : null;
  }
  function gone(d) { return function (name) { return d.vars ? d.vars[name] : ''; }; }
  function blankFields(d, t) { return t ? blanks(t.parameter_map || [], gone(d)) : []; }

  // Ticked to begin with: every document that can be sent to, has not already
  // gone out under this template, and has every field the template needs.
  function defaults() {
    var t = tpl();
    st.docs.forEach(function (d) {
      d.on = d.mobile_ok && !sentWith(d, t) && !blankFields(d, t).length;
      d.note = ''; d.state = '';
    });
    document.getElementById('bimsWaManyRetry').classList.add('d-none');
  }

  function quickPick(kind) {
    var t = tpl();
    st.docs.forEach(function (d) {
      if (!d.mobile_ok) { d.on = false; return; }
      if (kind === 'none') d.on = false;
      else if (kind === 'ready') d.on = true;
      else d.on = !sentWith(d, t) && !blankFields(d, t).length;
    });
    paint();
  }

  function statusCell(d, t) {
    if (d.state === 'sending') return '<span class="text-muted"><i class="fas fa-spinner fa-spin me-1"></i>Sending</span>';
    if (d.state === 'ok') return '<span class="text-success"><i class="fas fa-check me-1"></i>Sent</span>';
    if (d.state === 'skip') return '<span class="text-warning">' + esc(d.note) + '</span>';
    if (d.state === 'fail') return '<span class="text-danger"><i class="fas fa-xmark me-1"></i>' + esc(d.note) + '</span>';
    if (!d.mobile) return '<span class="text-danger">No mobile number</span>';
    if (!d.mobile_ok) return '<span class="text-danger">Invalid number</span>';
    var gaps = blankFields(d, t);
    if (gaps.length) return '<span class="text-warning"><i class="fas fa-triangle-exclamation me-1"></i>Missing ' + esc(gaps.join(', ')) + '</span>';
    var s = sentWith(d, t);
    if (s) {
      var n = d.sent.filter(function (x) { return x.template_name === t.template_name; }).length;
      return '<span class="text-muted">Already sent' + (n > 1 ? ' &times;' + n : '') + ', last ' + esc(s.sent_at) + '</span>';
    }
    return d.sent.length ? '<span class="text-muted">Sent earlier, other template</span>' : 'Ready';
  }

  function count() {
    var n = st.docs.filter(function (d) { return d.on && d.mobile_ok; }).length;
    document.getElementById('bimsWaManyCount').textContent = st.running ? '' : (n + ' will be sent');
    document.getElementById('bimsWaManyGo').disabled = st.running || !n || !tpl();
  }

  // The message the focused customer would get.
  function paintPreview() {
    var box = document.getElementById('bimsWaManyPreview');
    if (!box) return;
    var t = tpl(), d = st.docs[st.focus];
    if (!t || !d) { box.innerHTML = ''; return; }
    var get = gone(d);
    var head = '<div class="small text-muted mb-1">Preview &middot; <b>' + esc(d.party_name) + '</b>, ' + esc(d.doc_no || '') + '</div>';
    if (!t.body_preview) {
      box.innerHTML = head + '<div class="small text-muted">' +
        'Paste this template\'s approved wording under Messaging &rsaquo; WhatsApp Templates to see the whole message here.</div>' +
        '<table class="table table-sm table-bordered mt-2 mb-0 small wa-fields"><tbody>' +
        (t.parameter_map || []).map(function (n, i) {
          var v = get(n);
          return '<tr><td class="text-muted" style="width:42%">{{' + (i + 1) + '}} ' + esc(n) + '</td><td>' +
                 (v ? esc(v) : '<span class="wa-miss">empty</span>') + '</td></tr>';
        }).join('') + '</tbody></table>';
      return;
    }
    var f = fill(t.body_preview, t.parameter_map || [], get);
    box.innerHTML = head + bubble(f.html) +
      (f.missing.length ? '<div class="alert alert-warning small py-2 mt-2 mb-0">Empty: <b>' + f.missing.map(esc).join(', ') + '</b></div>' : '');
  }

  function paint() {
    var t = tpl();
    var rows = st.docs.map(function (d, i) {
      return '<tr data-i="' + i + '"' + (i === st.focus ? ' class="wam-focus"' : '') + '>' +
        '<td class="text-center"><input type="checkbox" class="form-check-input wam-pick" data-i="' + i + '"' +
        (d.on ? ' checked' : '') + (usable(d) ? '' : ' disabled') + '></td>' +
        '<td class="text-nowrap">' + esc(d.doc_no || '-') + '<div class="text-muted small">' + esc(d.date) + '</div></td>' +
        '<td>' + esc(d.party_name) + '</td><td class="text-nowrap">' + esc(d.mobile || '-') + '</td>' +
        '<td class="text-end text-nowrap">' + esc(d.amount) + '</td><td>' + statusCell(d, t) + '</td></tr>';
    }).join('');
    document.getElementById('bimsWaManyTable').innerHTML = rows;
    // The header box says what the rows say: all, some or none ticked.
    var all = document.getElementById('bimsWaManyAll');
    if (all) {
      var able = st.docs.filter(function (d) { return d.mobile_ok; });
      var on = able.filter(function (d) { return d.on; }).length;
      all.checked = !!able.length && on === able.length;
      all.indeterminate = on > 0 && on < able.length;
    }
    paintPreview();
    count();
  }

  function renderMany() {
    var d = st.data;
    st.docs = d.documents;
    st.focus = 0;
    document.getElementById('bimsWaManyN').textContent =
      d.documents.length + ' ' + (d.documents.length === 1 ? 'customer' : 'customers');
    if (!d.documents.length) {
      document.getElementById('bimsWaManyBody').innerHTML =
        '<div class="text-muted">Nothing here can be messaged. Only documents with a customer have someone to send to.</div>';
      return;
    }
    var html = '';
    if (d.skipped) {
      html += '<div class="alert alert-secondary small py-2">' + d.skipped + ' of the picked ' +
        (d.skipped === 1 ? 'document has' : 'documents have') + ' no customer to message and ' +
        (d.skipped === 1 ? 'is' : 'are') + ' left out.</div>';
    }
    if (!d.templates.length) {
      html += '<div class="alert alert-warning small py-2">No active WhatsApp template is set up for ' +
        esc(d.label) + '. Add one under Messaging &rsaquo; WhatsApp Templates.</div>';
    } else {
      html += '<div class="row g-2 align-items-end mb-2"><div class="col-md-6">' +
        '<label class="form-label small mb-1" for="bimsWaManyTpl">Template</label>' +
        '<select id="bimsWaManyTpl" class="form-select form-select-sm">' +
        d.templates.map(function (t) { return '<option value="' + t.id + '">' + esc(t.name) + '</option>'; }).join('') +
        '</select></div><div class="col-md-6 text-md-end">' +
        '<div class="btn-group btn-group-sm" role="group" aria-label="Quick pick">' +
          '<button type="button" class="btn btn-outline-secondary" data-pick="unsent">Not sent only</button>' +
          '<button type="button" class="btn btn-outline-secondary" data-pick="ready">All ready</button>' +
          '<button type="button" class="btn btn-outline-secondary" data-pick="none">None</button>' +
        '</div></div></div>';
    }
    html += '<div class="row g-3"><div class="col-lg-8"><div class="table-responsive" style="max-height:52vh">' +
      '<table class="table table-sm align-middle small mb-0"><thead><tr>' +
      '<th class="text-center" style="width:36px"><input type="checkbox" class="form-check-input" id="bimsWaManyAll" checked></th>' +
      '<th>' + esc(d.label) + '</th><th>Customer</th><th>Mobile</th><th class="text-end">Amount</th><th>Status</th></tr></thead>' +
      '<tbody id="bimsWaManyTable"></tbody></table></div>' +
      '<div class="form-text">Click a row to preview its message.</div></div>' +
      '<div class="col-lg-4"><div id="bimsWaManyPreview"></div></div></div>';
    document.getElementById('bimsWaManyBody').innerHTML = html;
    defaults();
    paint();
  }

  async function run(retrying) {
    var t = tpl();
    var todo = st.docs.filter(function (d) { return d.on && d.mobile_ok; });
    if (!t || !todo.length) return;
    if (!(await window.bimsConfirm('Send "' + t.name + '" to ' + todo.length +
        (todo.length === 1 ? ' customer' : ' customers') + ' now?',
        { title: retrying ? 'Retry failed' : 'Send WhatsApp', confirmText: 'Send', danger: false }))) return;
    st.running = true;
    document.getElementById('bimsWaManyClose').disabled = true;
    document.getElementById('bimsWaManyRetry').classList.add('d-none');
    st.docs.forEach(function (d) { if (!d.on) d.state = ''; });
    document.getElementById('bimsWaManyTpl').disabled = true;
    var ok = 0, bad = 0, skipped = 0;
    // One at a time: the provider is rate-limited, and a failure on one
    // number should not be mistaken for a failure of the batch.
    for (var i = 0; i < todo.length; i++) {
      var d = todo[i];
      d.state = 'sending'; st.focus = st.docs.indexOf(d); paint();
      try {
        var res = await sendOne(st.csrf, st.module, d.doc_id, t.id, false);
        if (res.status === 409 && res.body.duplicate) { d.state = 'skip'; d.note = 'Sent moments ago - skipped'; skipped++; }
        else if (res.body.success) {
          d.state = 'ok'; ok++; d.sent.push({ template_name: t.template_name, sent_at: 'just now' });
          if (st.onSent) st.onSent(d.doc_id);
        } else {
          d.state = 'fail';
          d.note = /template/i.test(res.body.error || '') && /(not found|approved)/i.test(res.body.error || '')
            ? 'No approved template "' + t.template_name + '" on WhatsApp' : (res.body.error || 'Could not be sent');
          bad++;
          if (st.onFailed) st.onFailed(d.doc_id);
        }
      } catch (e) { d.state = 'fail'; d.note = 'Network error'; bad++; }
      paint();
    }
    st.running = false;
    document.getElementById('bimsWaManyClose').disabled = false;
    document.getElementById('bimsWaManyTpl').disabled = false;
    document.getElementById('bimsWaManyRetry').classList.toggle('d-none', !bad);
    paint();
    window.showToast(bad ? 'warning' : 'success',
      ok + ' sent' + (bad ? ', ' + bad + ' failed' : '') + (skipped ? ', ' + skipped + ' skipped' : '') + '.');
  }

  // The ones that failed, and only those, ticked again and sent.
  function retryFailed() {
    st.docs.forEach(function (d) {
      var failed = d.state === 'fail';
      d.on = failed && d.mobile_ok; if (failed) { d.state = ''; d.note = ''; }
    });
    paint();
    run(true);
  }

  // ======================================================================
  // The sent status on a register's rows
  // ======================================================================
  // One per register. It remembers, for each row, how many messages went out
  // and how many failed; draws the Send button with that on it -- green once
  // sent, red outline if only failures, the detail on hover -- and keeps the
  // button right as the dialogs report results.
  function tracker() {
    ensureStyles();
    var by = {};
    function cls(wa) {
      if (wa && wa.sent) return 'btn-success';
      return wa && wa.failed ? 'btn-outline-danger' : 'btn-outline-success';
    }
    function title(wa) {
      if (!wa) return 'Send WhatsApp';
      var bits = [];
      if (wa.sent) bits.push('Sent ' + wa.sent + 'x, last ' + wa.sent_at);
      if (wa.failed) bits.push(wa.failed + ' failed');
      return bits.join(' - ') + ' - send again';
    }
    function paint(id) {
      var btn = document.querySelector('.wa-send-button[data-id="' + id + '"]');
      if (!btn) return;
      ['btn-success', 'btn-outline-success', 'btn-outline-danger'].forEach(function (c) { btn.classList.remove(c); });
      btn.classList.add(cls(by[id]));
      btn.title = title(by[id]);
    }
    function stamp() {
      var n = new Date();
      function p(x) { return String(x).padStart(2, '0'); }
      return p(n.getDate()) + '-' + p(n.getMonth() + 1) + '-' + n.getFullYear() + ' ' + p(n.getHours()) + ':' + p(n.getMinutes());
    }
    return {
      // The rows as the register's API returned them (each may carry .wa).
      load: function (rows) { by = {}; rows.forEach(function (r) { by[r.id] = r.wa || null; }); },
      button: function (id) {
        return '<button type="button" class="btn btn-sm wa-send-button ' + cls(by[id]) +
               '" data-id="' + id + '" title="' + esc(title(by[id])) + '"><i class="fab fa-whatsapp"></i></button>';
      },
      // A dialog reports one message: update the count and the button now; the
      // register reloads with the same facts from the server next time.
      outcome: function (id, ok) {
        var w = by[id] || (by[id] = { sent: 0, failed: 0, status: '', sent_at: '', last_at: '' });
        w.last_at = stamp();
        if (ok) { w.sent += 1; w.status = 'sent'; w.sent_at = w.last_at; } else { w.failed += 1; }
        paint(id);
      },
    };
  }

  window.BIMS_WhatsApp = {
    tracker: tracker,
    open: function (opts) {
      build();
      state = { module: opts.module, docId: opts.docId, csrf: opts.csrf, onSent: opts.onSent, onFailed: opts.onFailed };
      document.getElementById('bimsWaBody').innerHTML = '<div class="text-muted small">Loading&hellip;</div>';
      document.getElementById('bimsWaGo').disabled = true;
      bootstrap.Modal.getOrCreateInstance(modal).show();
      load().then(render).catch(function (e) {
        document.getElementById('bimsWaBody').innerHTML = '<div class="text-danger small">' + esc(e.message) + '</div>';
      });
    },
    openMany: function (opts) {
      buildMany();
      st = { module: opts.module, csrf: opts.csrf, onSent: opts.onSent, onFailed: opts.onFailed, running: false, docs: [], focus: 0 };
      document.getElementById('bimsWaManyBody').innerHTML = '<div class="text-muted small">Loading&hellip;</div>';
      document.getElementById('bimsWaManyN').textContent = '';
      document.getElementById('bimsWaManyCount').textContent = '';
      document.getElementById('bimsWaManyGo').disabled = true;
      document.getElementById('bimsWaManyRetry').classList.add('d-none');
      bootstrap.Modal.getOrCreateInstance(many).show();
      fetchJson('/whatsapp-transaction/documents/?module=' + encodeURIComponent(opts.module) +
                '&doc_ids=' + encodeURIComponent(opts.docIds.join(',')), { credentials: 'same-origin' })
        .then(function (r) {
          if (!r.ok) throw new Error(r.body.error || 'Could not load these documents.');
          st.data = r.body; renderMany();
        })
        .catch(function (e) {
          document.getElementById('bimsWaManyBody').innerHTML = '<div class="text-danger small">' + esc(e.message) + '</div>';
        });
    },
  };
})();

/* Show N entries on every register.
 *
 * Most list screens build their table with the "Bfrtip" layout, which leaves
 * out DataTables' page-size chooser, so a register showed ten rows with no way
 * to see more. Any table that has a search box but no chooser gets one here,
 * with 10 / 25 / 50 / 100 / All and 10 as the default -- no page needs editing.
 *
 * The layout has to be changed before the table is built (DataTables draws its
 * controls once, from the options it is handed), so this wraps the constructor
 * and adjusts the options on their way in.
 *
 * The size picked is remembered per table for the sitting, because a register
 * rebuilds its table every time its rows are reloaded (a filter, a send) and
 * would otherwise snap back to ten. A page that sets its own length menu, turns
 * paging off, or already has the chooser is left alone.
 */
(function () {
  var $ = window.jQuery;
  if (!$ || !$.fn || !$.fn.dataTable || $.fn.dataTable.__bimsLength) return;
  // The lower-case dataTable() is the constructor; DataTable() calls it and
  // hands back the API, so wrapping this one covers both.
  var original = $.fn.dataTable;
  function storageKey(table) {
    return table && table.id ? 'bims.dtlen.' + location.pathname + '.' + table.id : '';
  }
  function read(k) {
    try { return Number(window.sessionStorage.getItem(k)); } catch (e) { return 0; }
  }
  function write(k, v) {
    try { window.sessionStorage.setItem(k, String(v)); } catch (e) { /* not remembered */ }
  }

  function wanted(opts) {
    return opts && typeof opts === 'object' && !Array.isArray(opts) &&
      typeof opts.dom === 'string' && opts.dom.indexOf('l') < 0 && opts.dom.indexOf('f') >= 0 &&
      opts.paging !== false && !opts.aLengthMenu;
  }

  var wrapped = function (opts) {
    var args = Array.prototype.slice.call(arguments);
    if (this.length === 1 && wanted(opts)) {
      // A page with a menu of its own keeps it; it only lacked the control.
      var next = $.extend({}, opts, { dom: opts.dom.replace('f', 'lf') });
      if (!opts.lengthMenu) next.lengthMenu = [[10, 25, 50, 100, -1], [10, 25, 50, 100, 'All']];
      var k = storageKey(this[0]);
      var saved = k ? read(k) : 0;
      var menu = next.lengthMenu;
      var allowed = Array.isArray(menu[0]) ? menu[0] : menu;
      if (saved && allowed.indexOf(saved) >= 0) next.pageLength = saved;
      if (k) {
        $(this[0]).off('length.dt.bimsLength').on('length.dt.bimsLength', function (e, settings, len) {
          write(k, len);
        });
      }
      args[0] = next;
    }
    return original.apply(this, args);
  };
  // Everything hung off the constructor (ext, defaults, Api, ...) must stay reachable.
  $.extend(wrapped, original);
  wrapped.__bimsLength = true;
  $.fn.dataTable = wrapped;
})();
