/**
 * Shared behaviour for the access editors — Web Access, Mobile Access and
 * Dashboard Access.
 *
 * The three pages ask different questions (which ERP tab, which phone screen,
 * which dashboard card) but the *interaction* is one thing three times over:
 * a tree of folders you expand and collapse, checkboxes that cascade down a
 * scope, headers that show a dash when their rows disagree, and rows you
 * reorder. Each page had its own copy, and the copies drifted — the sort
 * column that controlled nothing and the table id with a space in it each
 * existed in exactly one of them and survived because nothing else shared the
 * code.
 *
 * This file is driven entirely by data attributes, so a fourth editor needs
 * markup and no JavaScript.
 *
 * ---------------------------------------------------------------------------
 * Markup contract
 * ---------------------------------------------------------------------------
 * Root            <table data-access-tree>  (or any container)
 *
 * Cell            .at-cell
 *                   data-action="view"          the column it belongs to
 *                   data-scope-<name>="<id>"    any number of nested scopes,
 *                                               e.g. data-scope-mod="broiler"
 *                 A *disabled* cell is never written by a cascade: it is a
 *                 permission the surface cannot grant, and a bulk tick must
 *                 not silently promise it.
 *
 * Control         .at-all
 *                   data-action="view"          optional — omit to mean "every
 *                                               action"
 *                   data-scope-<name>="<id>"    optional filters, same names
 *                   data-at-mode="all" | "any"  how it reflects its cells:
 *                                               "all" (default) ticks when all
 *                                               are on; "any" ticks when any is
 *                                               on, which is what the web
 *                                               matrix's link column means
 *                                               ("this page is reachable").
 *
 * Folder toggle   .at-toggle data-at-folder="<id>"
 * Folder child    class="child-of-<id>"         a row may carry several, one
 *                                               per ancestor; a row is visible
 *                                               only when no ancestor is
 *                                               collapsed, which is the rule
 *                                               the bespoke versions each got
 *                                               subtly wrong when nested.
 *
 * Expand/collapse [data-at-expand] / [data-at-collapse]
 *
 * Ordering        .at-move data-at-dir="up"|"down"   on an orderable row
 *                 .at-pos                            number input on that row
 *                 A row moves together with its folder children.
 */
(function () {
  "use strict";

  function attr(el, name) {
    return el.getAttribute(name);
  }

  /** The data-scope-* filters declared on a control, as [[name, value], …]. */
  function scopesOf(el) {
    var out = [];
    for (var i = 0; i < el.attributes.length; i++) {
      var a = el.attributes[i];
      if (a.name.indexOf("data-scope-") === 0) out.push([a.name, a.value]);
    }
    return out;
  }

  /** Cells a control governs: same action (if it names one) and every scope. */
  function cellsFor(root, control) {
    var selector = ".at-cell";
    var action = attr(control, "data-action");
    if (action) selector += '[data-action="' + action + '"]';
    scopesOf(control).forEach(function (pair) {
      selector += "[" + pair[0] + '="' + pair[1] + '"]';
    });
    return Array.prototype.filter.call(
      root.querySelectorAll(selector),
      function (cell) { return !cell.disabled; }
    );
  }

  function reflect(control, cells) {
    var on = cells.filter(function (c) { return c.checked; }).length;
    var any = attr(control, "data-at-mode") === "any";
    control.checked = any ? on > 0 : cells.length > 0 && on === cells.length;
    control.indeterminate = on > 0 && on < cells.length;
  }

  function init(root) {
    var controls = Array.prototype.slice.call(root.querySelectorAll(".at-all"));

    function sync() {
      controls.forEach(function (control) {
        reflect(control, cellsFor(root, control));
      });
    }

    root.addEventListener("change", function (e) {
      var el = e.target;
      if (el.classList.contains("at-all")) {
        cellsFor(root, el).forEach(function (cell) { cell.checked = el.checked; });
        el.indeterminate = false;
        sync();
      } else if (el.classList.contains("at-cell")) {
        sync();
      }
    });

    /* ---- folders ---------------------------------------------------------- */

    var toggles = Array.prototype.slice.call(root.querySelectorAll(".at-toggle"));

    function collapsed(id) {
      var toggle = root.querySelector('.at-toggle[data-at-folder="' + id + '"]');
      return !!(toggle && toggle.classList.contains("is-collapsed"));
    }

    function icon(toggle) {
      var i = toggle.querySelector("i");
      if (!i) return;
      var shut = toggle.classList.contains("is-collapsed");
      i.classList.toggle("fa-folder", shut);
      i.classList.toggle("fa-folder-open", !shut);
    }

    /**
     * A row is visible when none of its ancestors is collapsed. Deriving it
     * from the row rather than walking down from the toggle is what makes
     * nesting work: re-opening a module cannot resurrect the rows of a section
     * you deliberately shut.
     */
    function apply() {
      Array.prototype.forEach.call(root.querySelectorAll("tr, .at-row"), function (row) {
        var hide = false;
        row.classList.forEach(function (cls) {
          if (cls.indexOf("child-of-") === 0 && collapsed(cls.slice(9))) hide = true;
        });
        row.hidden = hide;
      });
      toggles.forEach(icon);
    }

    toggles.forEach(function (toggle) {
      toggle.addEventListener("click", function (e) {
        e.stopPropagation();
        toggle.classList.toggle("is-collapsed");
        apply();
      });
    });

    function setAll(shut) {
      toggles.forEach(function (t) { t.classList.toggle("is-collapsed", shut); });
      apply();
    }

    document.querySelectorAll("[data-at-expand]").forEach(function (b) {
      b.addEventListener("click", function () { setAll(false); });
    });
    document.querySelectorAll("[data-at-collapse]").forEach(function (b) {
      b.addEventListener("click", function () { setAll(true); });
    });

    /* ---- ordering --------------------------------------------------------- */

    var body = root.querySelector("tbody") || root;

    /** A row plus the rows that belong to it, so a move carries its children. */
    function blockOf(row) {
      var id = null;
      var toggle = row.querySelector(".at-toggle");
      if (toggle) id = attr(toggle, "data-at-folder");
      var block = [row];
      if (!id) return block;
      var next = row.nextElementSibling;
      while (next && next.classList.contains("child-of-" + id)) {
        block.push(next);
        next = next.nextElementSibling;
      }
      return block;
    }

    function renumber() {
      var i = 0;
      Array.prototype.forEach.call(body.querySelectorAll(".at-pos"), function (input) {
        input.value = i++;
      });
    }

    body.addEventListener("click", function (e) {
      var btn = e.target.closest ? e.target.closest(".at-move") : null;
      if (!btn) return;
      var row = btn.closest("tr") || btn.closest(".at-row");
      var block = blockOf(row);

      if (attr(btn, "data-at-dir") === "up") {
        var prev = row.previousElementSibling;
        // Step over another block's children to reach its own first row.
        while (prev && !prev.querySelector(".at-pos")) prev = prev.previousElementSibling;
        if (!prev) return;
        block.forEach(function (n) { body.insertBefore(n, prev); });
      } else {
        var after = block[block.length - 1].nextElementSibling;
        if (!after) return;
        var tail = blockOf(after);
        var anchor = tail[tail.length - 1].nextElementSibling;
        block.forEach(function (n) { body.insertBefore(n, anchor); });
      }
      renumber();
    });

    sync();
    apply();
  }

  function boot() {
    document.querySelectorAll("[data-access-tree]").forEach(init);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
