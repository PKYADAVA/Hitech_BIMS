/* Send Notification — the live half of the page.
 *
 * Three jobs, and one rule that shapes all of them: **the browser never decides
 * who a message reaches.** Every count on screen comes from
 * /notifications/send/recipients/, which computes it with the same helper the
 * send itself uses. This file asks and renders; it does not calculate an
 * audience, and it does not filter one. That is why the number in the
 * confirmation dialog can be trusted — it is the server's number, not a tally
 * kept here that could drift from it.
 *
 * The jobs:
 *   1. Mirror what is typed into the Preview Message and Summary cards.
 *   2. Re-ask the server for the employee list whenever the hierarchy changes.
 *   3. Keep the hidden <select multiple> fields in step with the chip UI, so a
 *      submit posts what the sender can see.
 *
 * Progressive enhancement is deliberate: the hidden selects are real form
 * fields. If this script fails to load, the page is a plain (ugly) Django form
 * that still sends correctly, rather than one that silently posts nobody.
 *
 * Bump the ?v= in send_notification.html when this changes — WhiteNoise serves
 * the copy in staticfiles/, so an edit here is invisible until collectstatic.
 */
(function () {
  "use strict";

  var form = document.getElementById("sn-form");
  if (!form) return;

  var RECIPIENTS_URL = form.dataset.recipientsUrl;
  var TYPE_DEFAULTS = {};
  try {
    TYPE_DEFAULTS = JSON.parse(form.dataset.typeDefaults || "{}");
  } catch (e) { /* a missing map only costs the category suggestion */ }

  var LEVELS = ["companies", "branches", "farms", "warehouses",
                "departments", "designations"];

  var $ = function (id) { return document.getElementById(id); };
  var usersSelect = form.querySelector('select[name="users"]');
  var groupsSelect = form.querySelector('select[name="groups"]');

  /* Everything the page knows. `chosen` is what the sender picked; `employees`
     and `groups` are what the server last offered. */
  var state = {
    employees: [],
    groups: [],
    chosen: new Set(readSelected(usersSelect)),
    chosenGroups: new Set(readSelected(groupsSelect)),
    search: "",
    selectedOnly: false,
    preview: null
  };

  function readSelected(select) {
    if (!select) return [];
    return Array.prototype.filter.call(select.options, function (o) { return o.selected; })
      .map(function (o) { return parseInt(o.value, 10); });
  }

  /* ------------------------------------------------------ compose mirror */

  function counter(input, label, max) {
    if (!input || !label) return;
    var update = function () {
      var n = (input.value || "").length;
      label.textContent = n + " / " + max;
      label.classList.toggle("over", n > max);
    };
    input.addEventListener("input", update);
    update();
  }

  function selectedLabel(select) {
    if (!select) return "";
    var opt = select.options[select.selectedIndex];
    return opt ? opt.text : "";
  }

  function scheduleMode() {
    var picked = form.querySelector('input[name="schedule"]:checked');
    return picked ? picked.value : "now";
  }

  function scheduleText() {
    if (scheduleMode() !== "later") return "Immediately";
    var when = form.querySelector('[name="send_at"]');
    if (!when || !when.value) return "Scheduled";
    var d = new Date(when.value);
    return isNaN(d) ? "Scheduled" : d.toLocaleString();
  }

  function refreshMessagePreview() {
    var title = form.querySelector('[name="title"]');
    var message = form.querySelector('[name="message"]');
    var priority = form.querySelector('[name="priority"]');
    var category = form.querySelector('[name="category"]');

    $("sn-preview-title").textContent =
      (title && title.value) || "Your title will appear here";
    $("sn-preview-body").textContent =
      (message && message.value) || "And the message underneath it.";

    var tone = priority ? priority.value : "medium";
    var box = $("sn-preview");
    box.className = "sn-preview-msg " + tone;

    var priorityText = selectedLabel(priority);
    var categoryText = selectedLabel(category);
    $("sn-preview-priority").textContent = priorityText;
    $("sn-preview-category").textContent = categoryText;
    $("sn-preview-when").textContent = scheduleText();

    $("sn-sum-priority").textContent = priorityText;
    $("sn-sum-category").textContent = categoryText;
    $("sn-sum-schedule").textContent =
      scheduleMode() === "later" ? scheduleText() : "Send Now";
  }

  /* --------------------------------------------------------- attachment */

  function wireAttachment() {
    var input = form.querySelector('input[type="file"][name="attachment"]');
    if (!input) return;
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      var name = file ? file.name : "No file chosen";
      var size = file
        ? (file.size < 1048576
            ? Math.round(file.size / 1024) + " KB"
            : (file.size / 1048576).toFixed(1) + " MB")
        : "";
      $("sn-file-name").textContent = name;
      $("sn-file-size").textContent = size;
      $("sn-sum-attachment").textContent = file ? name : "None";
      var wrap = $("sn-preview-attach-wrap");
      wrap.classList.toggle("d-none", !file);
      if (file) $("sn-preview-attach").textContent = name;
    });
  }

  /* ---------------------------------------------------------- hierarchy */

  function levelSelect(level) {
    return form.querySelector('select[name="' + level + '"]');
  }

  function checkedIn(level) {
    return readSelected(levelSelect(level));
  }

  function labelsIn(level) {
    var select = levelSelect(level);
    if (!select) return [];
    return Array.prototype.filter
      .call(select.options, function (o) { return o.selected; })
      .map(function (o) { return o.text.trim(); });
  }

  /* Each level is one searchable dropdown rather than a scrolling checkbox
     list. Nothing initialises them here: main.js upgrades every
     `select.form-select` on the site — multi-selects included — honours the
     `data-placeholder` these carry, keeps the list open while several are
     picked, and re-dispatches a native `change` so the cascade below still
     fires. Initialising them a second time here would have given this page its
     own dropdown behaviour and its own bugs.

     The one thing that is this file's job: after the cascade rebuilds a
     level's <option>s, Select2 has to be told to redraw. See replaceCascade. */
  function redraw(select) {
    if (window.jQuery && jQuery(select).hasClass("select2-hidden-accessible")) {
      jQuery(select).trigger("change.select2");
    }
  }

  /* The preview names one selection and counts the rest — "Akbarpur Branch"
     is worth reading, "3 Selected" is worth knowing, and a list of nine
     branch names in a side panel is worth neither. */
  function describeLevel(level, allLabel) {
    var names = labelsIn(level);
    if (!names.length) return allLabel;
    if (names.length === 1) return names[0];
    return names.length + " Selected";
  }

  function refreshLevelCounts() {
    LEVELS.forEach(function (level) {
      var badge = form.querySelector('[data-count-for="' + level + '"]');
      if (!badge) return;
      if (!badge.dataset.allLabel) badge.dataset.allLabel = badge.textContent;
      var n = checkedIn(level).length;
      badge.textContent = n ? "✓ " + n + " selected" : badge.dataset.allLabel;
      badge.classList.toggle("none", n === 0);

      var fact = form.querySelector('[data-fact="' + level + '"]');
      if (fact) fact.textContent = describeLevel(level, badge.dataset.allLabel);
    });
  }

  /* ---------------------------------------------------- server round trip */

  var inFlight = null;
  var pending = null;

  function fetchRecipients() {
    var params = new URLSearchParams();
    LEVELS.forEach(function (level) {
      checkedIn(level).forEach(function (id) { params.append(level, id); });
    });
    // Send what is already chosen so the server keeps those people counted
    // even when a narrowed filter no longer lists them.
    state.chosen.forEach(function (id) { params.append("users", id); });
    state.chosenGroups.forEach(function (id) { params.append("groups", id); });

    if (inFlight) { pending = true; return; }
    inFlight = true;

    fetch(RECIPIENTS_URL + "?" + params.toString(), {
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin"
    })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        state.employees = data.employees || [];
        state.groups = data.groups || [];
        state.preview = data.preview || null;
        replaceCascade("farms", data.farms, function (f) {
          return f.branch ? f.name + " · " + f.branch : f.name;
        });
        replaceCascade("warehouses", data.warehouses, function (w) { return w.name; });
        pruneChosen();
        renderEmployees();
        renderGroups();
        renderPreview();
      })
      .catch(function () {
        var box = $("sn-emp-chips");
        if (box) {
          box.innerHTML =
            '<span class="sn-checks-empty text-danger">' +
            "Couldn't load the employee list. Check your connection and " +
            "change a filter to retry.</span>";
        }
      })
      .then(function () {
        inFlight = null;
        if (pending) { pending = false; fetchRecipients(); }
      });
  }

  /* Farms and warehouses belong to the chosen branches, so their lists are
     rebuilt server-side. Ticks on rows that survive the rebuild are kept —
     re-ticking three farms because a fourth branch was added is the kind of
     small cruelty that makes people stop using a filter. */
  function replaceCascade(level, rows, labelOf) {
    if (!rows) return;
    var select = levelSelect(level);
    if (!select) return;
    var was = new Set(checkedIn(level));

    select.innerHTML = rows.map(function (row) {
      return '<option value="' + row.id + '"' +
        (was.has(row.id) ? " selected" : "") + ">" +
        escapeHtml(labelOf(row)) + "</option>";
    }).join("");

    // Rebuilding the options behind Select2 leaves its rendered chips stale
    // until it is told to redraw.
    redraw(select);
    refreshLevelCounts();
  }

  /* ----------------------------------------------------------- employees */

  function pruneChosen() {
    // Only ever drop people the server no longer offers at all — being
    // filtered out of the current view is not a reason to un-select someone.
    var offered = new Set(state.employees.map(function (e) { return e.id; }));
    var kept = new Set();
    state.chosen.forEach(function (id) { if (offered.has(id)) kept.add(id); });
    state.chosen = kept;
  }

  function visibleEmployees() {
    var q = state.search.trim().toLowerCase();
    return state.employees.filter(function (e) {
      if (state.selectedOnly && !state.chosen.has(e.id)) return false;
      if (!q) return true;
      return e.name.toLowerCase().indexOf(q) !== -1 ||
             (e.code || "").toLowerCase().indexOf(q) !== -1 ||
             (e.role || "").toLowerCase().indexOf(q) !== -1;
    });
  }

  function renderEmployees() {
    var box = $("sn-emp-chips");
    var rows = visibleEmployees();

    if (!state.employees.length) {
      box.innerHTML =
        '<span class="sn-checks-empty">No employees match this organization ' +
        "selection. Employees with no Organization Access recorded are only " +
        "reachable with the hierarchy left open.</span>";
    } else if (!rows.length) {
      box.innerHTML = '<span class="sn-checks-empty">Nobody matches that search.</span>';
    } else {
      box.innerHTML = rows.map(function (e) {
        var on = state.chosen.has(e.id);
        var sub = e.role || e.department || "";
        return '<span class="sn-chip' + (on ? "" : " off") + '" data-emp="' + e.id +
          '" title="' + escapeHtml(e.name + (sub ? " — " + sub : "")) + '">' +
          '<span class="sn-avatar">' + escapeHtml(e.initials) + "</span>" +
          "<span>" + escapeHtml(e.name) + "</span>" +
          '<button type="button" class="sn-chip-x" aria-label="' +
          (on ? "Remove " : "Add ") + escapeHtml(e.name) + '">' +
          (on ? "×" : "+") + "</button></span>";
      }).join("");
    }

    var toggle = $("sn-view-selected");
    toggle.classList.toggle("d-none", state.chosen.size === 0);
    toggle.textContent = state.selectedOnly
      ? "Show all " + state.employees.length
      : "View selected only (" + state.chosen.size + ")";

    syncSelect(usersSelect, state.chosen);
    var badge = form.querySelector('[data-count-for="users"]');
    if (badge) {
      badge.textContent = state.chosen.size + " selected";
      badge.classList.toggle("none", state.chosen.size === 0);
    }
  }

  function renderGroups() {
    var list = $("sn-group-list");
    var rebuild = list.options.length !== state.groups.length;
    if (rebuild) {
      list.innerHTML = state.groups.map(function (g) {
        return '<option value="' + g.id + '"' +
          (state.chosenGroups.has(g.id) ? " selected" : "") + ">" +
          escapeHtml(g.name) + " · " + g.members + " members</option>";
      }).join("");
      redraw(list);
    }
    syncSelect(groupsSelect, state.chosenGroups);
    refreshGroupBadge();
  }

  function refreshGroupBadge() {
    var badge = form.querySelector('[data-count-for="groups"]');
    if (!badge) return;
    badge.textContent = state.chosenGroups.size + " selected";
    badge.classList.toggle("none", state.chosenGroups.size === 0);
  }

  /* The hidden <select multiple> is what actually posts. Keeping it in step
     here — rather than building the payload at submit — means an error page
     redisplays with the right people still selected. */
  function syncSelect(select, chosen) {
    if (!select) return;
    Array.prototype.forEach.call(select.options, function (o) {
      o.selected = chosen.has(parseInt(o.value, 10));
    });
  }

  /* ------------------------------------------------------------ preview */

  function renderPreview() {
    var p = state.preview || { total: 0, employees: 0, groups: 0, excluded: 0,
                               excluded_names: [], push_capable: 0 };

    $("sn-total").textContent = p.total;
    $("sn-sum-recipients").textContent = p.total;
    // The card header answers "how many" without scrolling to the preview,
    // which is the one number people look for while still picking.
    var header = $("sn-sel-count");
    header.textContent = p.total + " selected";
    header.classList.toggle("none", p.total === 0);
    form.querySelector('[data-fact="users"]').textContent = state.chosen.size;
    form.querySelector('[data-fact="groups"]').textContent = state.chosenGroups.size;

    var bars = {
      users: state.chosen.size,
      groups: state.chosenGroups.size,
      roles: checkedIn("designations").length,
      places: checkedIn("farms").length
    };
    var peak = Math.max(1, bars.users, bars.groups, bars.roles, bars.places);
    Object.keys(bars).forEach(function (key) {
      var fill = form.querySelector('[data-bar="' + key + '"]');
      var num = form.querySelector('[data-barn="' + key + '"]');
      if (fill) fill.style.width = Math.round((bars[key] / peak) * 100) + "%";
      if (num) num.textContent = bars[key];
    });

    var status = $("sn-status");
    var text = $("sn-status-text");
    var view = $("sn-view-excluded");
    if (p.excluded > 0) {
      status.className = "sn-status warn";
      text.textContent = p.excluded + " inactive user" +
        (p.excluded === 1 ? "" : "s") + " excluded";
      view.classList.remove("d-none");
      view.onclick = function () {
        window.alert("Excluded (inactive accounts):\n\n" +
          (p.excluded_names || []).join("\n"));
      };
    } else {
      status.className = "sn-status ok";
      text.textContent = "All recipients are active";
      view.classList.add("d-none");
    }

    // Channels are reported, never promised: the push line is a count of
    // registered devices with push left on, not a guess from headcount.
    setChannel("inapp", p.total + " " + plural(p.total, "person", "people") +
      " — in-app notification");
    setChannel("push", p.push_capable + " mobile app " +
      plural(p.push_capable, "user", "users") + " — push notification");
    setChannel("groups", state.chosenGroups.size + " " +
      plural(state.chosenGroups.size, "group", "groups"));
  }

  function setChannel(key, text) {
    var el = form.querySelector('[data-ch="' + key + '"]');
    if (el) el.textContent = text;
  }

  function plural(n, one, many) { return n === 1 ? one : many; }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* -------------------------------------------------------------- events */

  form.addEventListener("change", function (e) {
    var t = e.target;

    if (t.name === "schedule") {
      $("sn-when").classList.toggle("d-none", t.value !== "later");
      refreshMessagePreview();
      return;
    }
    if (t.name === "notification_type") {
      // The category follows the type as a suggestion. Only while the sender
      // has not overruled it — changing a choice they made would be worse than
      // leaving a stale one.
      var wanted = TYPE_DEFAULTS[t.value];
      var category = form.querySelector('[name="category"]');
      if (wanted && category && !category.dataset.touched) {
        category.value = wanted.category;
        if (window.jQuery && jQuery(category).hasClass("select2-hidden-accessible")) {
          jQuery(category).trigger("change.select2");
        }
      }
      refreshMessagePreview();
      return;
    }
    if (t.name === "category") { t.dataset.touched = "1"; }
    if (t.name === "priority" || t.name === "category" || t.name === "send_at") {
      refreshMessagePreview();
      return;
    }
    if (t.id === "sn-group-list") {
      state.chosenGroups = new Set(readSelected(t));
      syncSelect(groupsSelect, state.chosenGroups);
      refreshGroupBadge();
      renderPreview();
      fetchRecipients();
      return;
    }
    if (LEVELS.indexOf(t.name) !== -1) {
      refreshLevelCounts();
      fetchRecipients();
    }
  });

  form.addEventListener("input", function (e) {
    if (e.target.name === "title" || e.target.name === "message") {
      refreshMessagePreview();
    }
  });

  form.addEventListener("click", function (e) {
    var chip = e.target.closest("[data-emp]");
    if (!chip) return;
    var id = parseInt(chip.dataset.emp, 10);
    if (state.chosen.has(id)) state.chosen.delete(id); else state.chosen.add(id);
    renderEmployees();
    fetchRecipients();
  });

  $("sn-emp-search").addEventListener("input", function (e) {
    state.search = e.target.value;
    renderEmployees();
  });

  $("sn-select-all").addEventListener("click", function () {
    visibleEmployees().forEach(function (e) { state.chosen.add(e.id); });
    renderEmployees();
    fetchRecipients();
  });

  $("sn-clear-all").addEventListener("click", function () {
    state.chosen.clear();
    state.selectedOnly = false;
    renderEmployees();
    fetchRecipients();
  });

  $("sn-view-selected").addEventListener("click", function () {
    state.selectedOnly = !state.selectedOnly;
    renderEmployees();
  });

  /* --------------------------------------------------------- submitting */

  var actionField = form.querySelector('[name="action"]');
  var confirmed = false;

  $("sn-draft").addEventListener("click", function () {
    // A draft is allowed to be incomplete, so it skips both the confirmation
    // and the browser's required-field checks.
    actionField.value = "draft";
    confirmed = true;
    form.noValidate = true;
    form.submit();
  });

  form.addEventListener("submit", function (e) {
    if (confirmed) return;
    actionField.value = "send";

    var total = state.preview ? state.preview.total : 0;
    if (!total) {
      e.preventDefault();
      window.alert("No eligible recipients selected.");
      return;
    }

    // Scheduling is its own commitment and the page already states the time;
    // a dialog repeating it would be one click for nothing. The confirmation
    // is for the irreversible case — sending now.
    if (scheduleMode() === "later") return;

    e.preventDefault();
    $("sn-confirm-total").textContent = total;
    $("sn-confirm-priority").textContent =
      selectedLabel(form.querySelector('[name="priority"]'));
    $("sn-confirm-category").textContent =
      selectedLabel(form.querySelector('[name="category"]'));
    $("sn-confirm-schedule").textContent = "Send Now";

    if (window.bootstrap && bootstrap.Modal) {
      bootstrap.Modal.getOrCreateInstance($("sn-confirm")).show();
    } else if (window.confirm("Send this notification to " + total + " recipients?")) {
      confirmed = true;
      form.submit();
    }
  });

  $("sn-confirm-send").addEventListener("click", function () {
    confirmed = true;
    var btn = $("sn-confirm-send");
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin me-1"></i>Sending…';
    form.submit();
  });

  /* ------------------------------------------------------------- startup */

  counter(form.querySelector('[name="title"]'), $("title-count"), 100);
  counter(form.querySelector('[name="message"]'), $("message-count"), 500);
  wireAttachment();
  refreshLevelCounts();
  refreshMessagePreview();

  if (scheduleMode() === "later") $("sn-when").classList.remove("d-none");
  if (form.querySelector('[name="category"]') && form.querySelector('[name="title"]').value) {
    // Reopening a draft: the category on it was a decision, not a default.
    form.querySelector('[name="category"]').dataset.touched = "1";
  }

  fetchRecipients();
})();
