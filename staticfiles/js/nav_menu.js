/* Module menus, shared by both navigations.
 *
 * The top bar and the sidebar show the same thing in the same two ways:
 * hovering a module opens its menu, clicking it opens every page of that
 * module at once. The panel was written inside the top bar's template, so the
 * sidebar — which does not include it — had neither. It lives here now, and
 * each layout only has to say where its modules are and where a panel should
 * be drawn.
 *
 *   BimsNavMenu.openPanel(spec, box)   every section side by side, with a
 *                                      "Find a page" box and arrow keys
 *   BimsNavMenu.openFlyout(spec, box)  the same pages in one narrow column,
 *                                      or, with { cascade: true }, a row per
 *                                      section that opens its pages beside it
 *   BimsNavMenu.close()                closes whichever is open
 *
 * A menu opened with { hoverClose: ms } closes itself that long after the
 * pointer leaves it, and its own rows, submenus and the rail that opened it
 * hold it open between them: one timer for the lot, since a menu and the
 * submenu it spawned are siblings on the body, not parent and child.
 *
 * A spec is { title, icon, description, sections: [{ title, icon, items: [
 * { href, label, icon, target, current } ] }] }, and a box is the rectangle
 * the menu should sit against: { left, top, right, maxWidth }.
 */
// One line on what each module covers, shown beside its pages. Keyed by the
// module, so both navigations say the same thing.
window.BIMS_MODULE_INTRO = {
  broiler: "Flocks from chick placement to settlement: farms, daily records, feed, lifting and farmer growing charges.",
  hatchery: "Eggs in, chicks out: egg purchase and grading, setting, hatching, delivery and the machines' environment.",
  purchase: "What the business buys: suppliers, general and chicks purchases, payments, debit and credit notes.",
  sales: "What the business sells: customers, sales, receipts and their notes.",
  account: "The books: chart of accounts, vouchers, ledgers and the statements built on them.",
  inventory: "Stock and where it is: items, warehouses, transfers, adjustments and valuation.",
  hr: "People: employees, attendance, leave, payroll and field trips.",
  change_requests: "Edits and deletions waiting for someone to approve them.",
  user: "Who may see and do what: users, groups, access and the dashboards they land on.",
  notifications: "Messages to farmers and staff: templates, sending and delivery history.",
  alerts: "What needs attention: rules, the alert feed and who is told.",
  tracking: "Where the field team went: devices, trips and routes."
};

(function () {
  var panel = null, flyout = null, sub = null, onClose = null;
  var hoverTimer = null, hoverMs = 0, subRow = null;

  function cancelClose() { clearTimeout(hoverTimer); }

  function armClose(ms) {
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(closeAll, ms || hoverMs || 180);
  }

  // Everything the pointer may rest on without the menu closing: the menu, a
  // submenu it opened, and the module or section row it belongs to.
  function holdsOpen(node) {
    node.addEventListener("mouseenter", cancelClose);
    node.addEventListener("mouseleave", function () { if (hoverMs) armClose(hoverMs); });
  }

  function el(tag, cls) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    return node;
  }

  function linkNode(item) {
    var a = el("a", "dropdown-item");
    a.href = item.href;
    if (item.target) a.target = item.target;
    if (item.rel) a.rel = item.rel;
    if (item.icon) {
      var i = el("i");
      i.className = item.icon;
      if (item.colour) i.style.color = item.colour;
      a.appendChild(i);
    }
    a.appendChild(document.createTextNode(item.label));
    if (item.current) a.classList.add("is-current");
    return a;
  }

  function heading(section) {
    var head = el("div", "bims-mega-head");
    var tile = el("span", "bims-mega-hi");
    if (section.icon) {
      var i = el("i");
      i.className = section.icon;
      if (section.colour) { i.style.color = section.colour; tile.style.setProperty("--hi", section.colour); }
      tile.appendChild(i);
    }
    head.appendChild(tile);
    head.appendChild(document.createTextNode(section.title));
    return head;
  }

  function visibleLinks(scope) {
    return Array.prototype.filter.call(scope.querySelectorAll("a.dropdown-item"),
      function (a) { return a.offsetParent !== null; });
  }

  function buildPanel(spec) {
    var root = el("div", "bims-mega");
    root.setAttribute("role", "menu");
    root.setAttribute("aria-label", spec.title + " menu");

    var intro = el("div", "bims-mega-intro");
    var icon = el("div", "bims-mega-icon");
    if (spec.icon) { var bi = el("i"); bi.className = spec.icon; icon.appendChild(bi); }
    var name = el("div", "bims-mega-name"); name.textContent = spec.title;
    var desc = el("div", "bims-mega-desc"); desc.textContent = spec.description || "";
    var count = el("div", "bims-mega-count");
    intro.appendChild(icon); intro.appendChild(name); intro.appendChild(desc); intro.appendChild(count);

    var cols = el("div", "bims-mega-cols");
    var pages = 0;
    spec.sections.forEach(function (section) {
      var col = el("div", "bims-mega-col");
      col.appendChild(heading(section));
      var list = el("div", "bims-mega-list");
      col.list = list;
      section.items.forEach(function (item) {
        if (item.subheading) {
          var sub = el("div", "bims-mega-sub");
          sub.textContent = item.subheading;
          list.appendChild(sub);
          return;
        }
        list.appendChild(linkNode(item)); pages++;
      });
      col.appendChild(list);
      cols.appendChild(col);
    });
    cols.style.gridTemplateColumns = "repeat(" + Math.max(spec.sections.length, 1) + ", minmax(150px, 1fr))";
    count.textContent = pages + " page" + (pages === 1 ? "" : "s") + " in "
      + spec.sections.length + " section" + (spec.sections.length === 1 ? "" : "s");

    // Find a page: typing narrows every column at once.
    var find = el("div", "bims-mega-search");
    find.innerHTML = '<i class="fas fa-magnifying-glass"></i>'
      + '<input type="search" placeholder="Find a page..." aria-label="Find a page">';
    intro.appendChild(find);
    var none = el("div", "bims-mega-none is-hidden");
    none.textContent = "No page matches.";
    cols.appendChild(none);
    var input = find.querySelector("input");
    input.addEventListener("input", function () {
      var q = input.value.trim().toLowerCase(), any = false;
      cols.querySelectorAll(".bims-mega-col").forEach(function (col) {
        var shown = 0, sub = null, subShown = 0;
        Array.prototype.forEach.call(col.list.children, function (node) {
          if (node.classList.contains("bims-mega-sub")) {
            if (sub) sub.classList.toggle("is-hidden", !subShown);
            sub = node; subShown = 0; return;
          }
          var hit = !q || node.textContent.toLowerCase().indexOf(q) !== -1;
          node.classList.toggle("is-hidden", !hit);
          if (hit) { shown++; if (sub) subShown++; }
        });
        if (sub) sub.classList.toggle("is-hidden", !subShown);
        col.classList.toggle("is-hidden", !shown);
        if (shown) any = true;
      });
      none.classList.toggle("is-hidden", any);
      var showing = cols.querySelectorAll(".bims-mega-col:not(.is-hidden)").length;
      cols.style.gridTemplateColumns = q
        ? "repeat(" + Math.max(showing, 1) + ", minmax(150px, 300px))"
        : "repeat(" + Math.max(spec.sections.length, 1) + ", minmax(150px, 1fr))";
    });
    input.addEventListener("keydown", function (e) {
      var first = visibleLinks(cols)[0];
      if (e.key === "Enter" && first) { e.preventDefault(); first.click(); }
      if (e.key === "ArrowDown" && first) { e.preventDefault(); first.focus(); }
    });

    var close = el("button", "bims-mega-close");
    close.type = "button";
    close.setAttribute("aria-label", "Close menu");
    close.title = "Close (Esc)";
    close.innerHTML = '<i class="fas fa-xmark"></i>';
    close.addEventListener("click", function (e) { e.stopPropagation(); closeAll(); });

    root.appendChild(intro); root.appendChild(cols); root.appendChild(close);
    root.addEventListener("keydown", arrowKeys);
    return root;
  }

  // Arrow keys: up and down a column, left and right between columns.
  function arrowKeys(e) {
    var a = e.target.closest && e.target.closest("a.dropdown-item");
    if (!a || !panel || !panel.contains(a)) return;
    var col = a.closest(".bims-mega-col");
    var here = visibleLinks(col), i = here.indexOf(a);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      var next = here[i + (e.key === "ArrowDown" ? 1 : -1)];
      if (next) { e.preventDefault(); next.focus(); }
      else if (e.key === "ArrowUp") {
        e.preventDefault();
        panel.querySelector(".bims-mega-search input").focus();
      }
    } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      var all = Array.prototype.filter.call(panel.querySelectorAll(".bims-mega-col"),
        function (c) { return !c.classList.contains("is-hidden"); });
      var to = all[all.indexOf(col) + (e.key === "ArrowRight" ? 1 : -1)];
      if (!to) return;
      var there = visibleLinks(to);
      var target = there[Math.min(i, there.length - 1)];
      if (target) { e.preventDefault(); target.focus(); }
    }
  }

  // One row per section, each opening its own pages beside it -- what a
  // module's menu does in the top bar, for the rail's menus too.
  function buildCascade(spec) {
    var root = el("div", "bims-fly bims-fly-rows");
    root.setAttribute("role", "menu");
    root.setAttribute("aria-label", spec.title + " menu");
    spec.sections.forEach(function (section) {
      var row = el("button", "bims-fly-row");
      row.type = "button";
      row.setAttribute("aria-haspopup", "true");
      if (section.icon) {
        var i = el("i");
        i.className = section.icon;
        if (section.colour) i.style.color = section.colour;
        row.appendChild(i);
      }
      var label = el("span");
      label.textContent = section.title;
      row.appendChild(label);
      var count = el("small");
      count.textContent = section.items.filter(function (it) { return !it.subheading; }).length;
      row.appendChild(count);
      var caret = el("i", "bims-fly-caret");
      caret.className = "fas fa-chevron-right bims-fly-caret";
      row.appendChild(caret);
      row.addEventListener("mouseenter", function () { openSub(section, row); });
      row.addEventListener("focus", function () { openSub(section, row); });
      row.addEventListener("click", function (e) { e.preventDefault(); openSub(section, row); });
      root.appendChild(row);
    });
    return root;
  }

  // The pages of one section, drawn beside the row that asked for them. It is
  // its own element on the body rather than a child of the menu: the menu
  // scrolls when it is tall, and a child would be clipped at its edge.
  function openSub(section, row) {
    if (subRow === row && sub) return;
    if (sub) { sub.remove(); sub = null; }
    subRow = row;
    if (flyout) {
      flyout.querySelectorAll(".bims-fly-row.is-open").forEach(function (r) {
        r.classList.remove("is-open");
      });
    }
    row.classList.add("is-open");
    sub = buildFlyout({ title: section.title, sections: [section] });
    sub.classList.add("bims-fly-child");
    document.body.appendChild(sub);
    var from = (flyout || row).getBoundingClientRect(), here = row.getBoundingClientRect();
    place(sub, { left: Math.round(from.right + 6), top: Math.round(here.top - 8), share: 0.8, lift: true });
    holdsOpen(sub);
    cancelClose();
  }

  function buildFlyout(spec) {
    var root = el("div", "bims-fly");
    root.setAttribute("role", "menu");
    root.setAttribute("aria-label", spec.title + " menu");
    spec.sections.forEach(function (section) {
      var head = el("div", "bims-fly-head");
      if (section.icon) { var i = el("i"); i.className = section.icon; head.appendChild(i); }
      head.appendChild(document.createTextNode(section.title));
      root.appendChild(head);
      section.items.forEach(function (item) {
        if (item.subheading) {
          var sub = el("div", "bims-fly-sub");
          sub.textContent = item.subheading;
          root.appendChild(sub);
          return;
        }
        root.appendChild(linkNode(item));
      });
    });
    return root;
  }

  // Against the box it was given, kept on screen: a menu that would run past
  // the bottom stops short of it and its own content scrolls.
  function place(node, box) {
    node.style.position = "fixed";
    node.style.left = box.left + "px";
    node.style.top = box.top + "px";
    if (box.right != null) node.style.right = box.right + "px";
    if (box.width != null) node.style.width = box.width + "px";
    var top = box.top;
    if (box.lift) {
      // Tall enough to matter: lift it so it ends on screen, never above 8px.
      var wanted = Math.min(node.scrollHeight + 4, Math.round(window.innerHeight * 0.8));
      top = Math.max(8, Math.min(top, window.innerHeight - wanted - 12));
      node.style.top = top + "px";
    }
    var room = Math.max(220, Math.min(window.innerHeight - top - 12,
                                      Math.round(window.innerHeight * (box.share || 0.6))));
    if (node.classList.contains("bims-mega")) {
      node.querySelectorAll(".bims-mega-col").forEach(function (col) {
        var head = col.querySelector(".bims-mega-head");
        col.list.style.maxHeight = Math.max(120, room - 32 - head.offsetHeight) + "px";
      });
    } else {
      node.style.maxHeight = room + "px";
    }
  }

  function closeAll() {
    clearTimeout(hoverTimer);
    hoverMs = 0;
    subRow = null;
    [panel, flyout, sub].forEach(function (node) { if (node) node.remove(); });
    panel = flyout = sub = null;
    if (onClose) { var fn = onClose; onClose = null; fn(); }
  }

  function openPanel(spec, box, opts) {
    closeAll();
    panel = buildPanel(spec);
    document.body.appendChild(panel);
    place(panel, box);
    onClose = (opts || {}).onClose || null;
    var find = panel.querySelector(".bims-mega-search input");
    if (find) find.focus({ preventScroll: true });
    return panel;
  }

  function openFlyout(spec, box, opts) {
    opts = opts || {};
    closeAll();
    flyout = opts.cascade && spec.sections.length > 1 ? buildCascade(spec) : buildFlyout(spec);
    document.body.appendChild(flyout);
    place(flyout, box);
    onClose = opts.onClose || null;
    hoverMs = opts.hoverClose || 0;
    if (hoverMs) holdsOpen(flyout);
    return flyout;
  }

  document.addEventListener("click", function (e) {
    var open = panel || flyout;
    if (!open) return;
    if (open.contains(e.target)) {
      if (e.target.closest("a.dropdown-item")) closeAll();   // opens in a new tab
      return;
    }
    if (e.target.closest("[data-nav-menu-anchor]")) return;   // its own module
    closeAll();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeAll();
  });
  window.addEventListener("resize", closeAll);

  window.BimsNavMenu = {
    openPanel: openPanel,
    openFlyout: openFlyout,
    close: closeAll,
    holdOpen: cancelClose,
    closeSoon: armClose,
    isOpen: function () { return !!(panel || flyout); },
    panelOpen: function () { return !!panel; },
  };
})();
