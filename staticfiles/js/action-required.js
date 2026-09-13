/* Action Required — the dashboard's worklist of open exceptions.
 *
 * Separate from alerthub.js, which draws the bell and the notification centre.
 * Those render a feed; this one runs a small workflow, and mixing the two
 * would put state transitions into the file every page on the site loads.
 *
 * The division of labour with the server is deliberate and worth keeping:
 *
 *   the server decides  — which alerts are open, how urgent each is, what its
 *                         reading means, and WHICH MOVES ARE AVAILABLE on it;
 *   this file decides   — nothing. It draws what came back and posts what was
 *                         pressed.
 *
 * That is why there is no transition table in here. There is one, in
 * alerthub/workflow.py, and the buttons are built from the copy the API sends
 * with each alert. A second copy on the client would drift from it, and the
 * visible copy is the one that would be wrong.
 *
 * Talks to /api/alerthub/action-required/. CSRF_COOKIE_HTTPONLY is on in this
 * project, so the token is injected into data-csrf by the template.
 *
 * Bump the ?v= in the <script> tag when this changes — WhiteNoise serves
 * staticfiles/, so edits here are invisible until collectstatic runs.
 */
(function (window, document) {
  "use strict";

  var API = "/api/alerthub/action-required/";
  var esc = window.AlertHub ? window.AlertHub.esc : String;
  var timeAgo = window.AlertHub ? window.AlertHub.timeAgo : function (v) { return v; };

  /* ------------------------------------------------------------ transport */

  function send(url, csrf, body) {
    return fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrf,
        "X-Requested-With": "XMLHttpRequest"
      },
      body: JSON.stringify(body || {})
    }).then(function (response) {
      return response.json().catch(function () { return {}; })
        .then(function (data) {
          // A refused move comes back as 400 with a sentence in it — the
          // state machine explaining itself. That sentence is the whole
          // value of the response, so it is carried on the error rather
          // than replaced with "HTTP 400".
          if (!response.ok || data.ok === false) {
            throw new Error(data.error || ("HTTP " + response.status));
          }
          return data;
        });
    });
  }

  function say(kind, message) {
    if (typeof window.showToast === "function") return window.showToast(kind, message);
    if (kind === "danger") window.alert(message);
  }

  /* --------------------------------------------------------------- markup */

  /* A link into the notification centre, showing what this card counts.
   *
   * The centre opens on "Unread only". This card counts what is *open*, which
   * is a different question — an alert somebody read on Monday and did nothing
   * about is still open on Friday. So "22 more open" led to a page that said
   * nothing matched, which reads as a broken link rather than as two filters
   * disagreeing. Every link out of here clears the read filter, so the page it
   * opens holds the rows this card was counting.
   */
  function centreLink(centre, params) {
    var query = new URLSearchParams(params || {});
    query.set("is_read", "");            // read and unread alike
    return centre + "?" + query.toString();
  }

  /* Severity chips, zeroes omitted. A row of "Critical 0 · High 0 · Warning 0"
     is three pieces of furniture that say nothing and push the alerts down. */
  function summaryHTML(summary, centre) {
    // The same four words the row badges use — they come from SEVERITY_LABEL
    // in alerthub/constants.py, and a chip reading "Warning" above a badge
    // reading "Medium" would be two names for one thing on one card.
    var levels = [
      ["critical", "Critical"], ["high", "High"],
      ["medium", "Warning"], ["low", "Information"]
    ];
    // Zeroes are shown, not dropped. Four chips in a fixed order read as a
    // severity scale somebody can scan; chips that come and go with the counts
    // change width and position between refreshes, and "no Information items"
    // is itself worth seeing. A zero is drawn quietly — see .ar-sum.is-zero.
    var ICON = {
      critical: "fa-solid fa-circle-exclamation",
      high: "fa-solid fa-circle-exclamation",
      medium: "fa-solid fa-triangle-exclamation",
      low: "fa-solid fa-circle-info"
    };
    return levels.map(function (level) {
        var n = summary[level[0]] || 0;
        return '<a class="ar-sum ' + level[0] + (n ? "" : " is-zero") + '" href="' +
          centreLink(centre, { priority: level[0] }) + '">' +
          '<i class="' + ICON[level[0]] + '"></i><b>' +
          n + "</b> " + level[1] + "</a>";
      }).join("");
  }

  /* The facts under the message, as chips: where it is and what it is about.
   *
   * A row reads problem -> location -> reading -> age -> action. The first
   * two are here; the reading and the age are the column to the right, where
   * the number can be set large enough to scan a list by. Chips rather than a
   * run of text separated by middots because the three are different kinds of
   * thing - a module, a record, a place - and a reader picking out "Shed 1"
   * should not have to read the other two first.
   */
  function metaHTML(alert, centre) {
    var chips = [];
    if (alert.module_label) chips.push(esc(alert.module_label));
    if (alert.object_display) chips.push(esc(alert.object_display));
    if (alert.place) chips.push(esc(alert.place));

    var html = chips.map(function (text) {
      return '<span class="ar-chip">' + text + "</span>";
    }).join("");

    // Whose job it is, when it is somebody's. A name on the row is the
    // difference between a list everybody scrolls past and a list with an
    // owner against each line.
    if (alert.assigned_to_name) {
      html += '<span class="ar-chip owner">' +
        '<i class="fa-solid fa-user-check"></i>' +
        esc(alert.assigned_to_name) + "</span>";
    }

    // Who has it, when somebody has. The status chip says an alert was picked
    // up; without a name beside it, nobody knows whether to pick it up too.
    if (alert.status_changed_by_name && alert.status !== "open") {
      html += '<span class="ar-by">' + esc(alert.status_label) + " by " +
        esc(alert.status_changed_by_name) + "</span>";
    }
    // The rest of this rule, which the per-rule cap kept off the card. The
    // link goes to the centre filtered to that rule, so "+16 more" leads
    // somewhere that shows the sixteen rather than the whole feed.
    if (alert.more_like_this > 0) {
      html += '<a class="ar-more" href="' +
        centreLink(centre, { rule_key: alert.rule_key }) + '">+' +
        alert.more_like_this + " more like this</a>";
    }
    return html;
  }

  /* The reading and the age, down the right-hand edge.
   *
   * The number is the thing the rule fired on, so it is the largest thing on
   * the row and it is the severity's colour. The caption under it says what
   * the figure is, and says it truthfully: only the rules with a threshold
   * are comparing two numbers, and "measured / limit" over a lone reading
   * promised a limit that does not exist.
   */
  function metricHTML(alert) {
    if (!alert.reading_value) {
      return '<div class="ar-metric"><span class="ar-when">' +
        esc(timeAgo(alert.created_at)) + "</span></div>";
    }
    return '<div class="ar-metric ' + esc(alert.priority) + '">' +
      "<b>" + esc(alert.reading_value) +
        (alert.reading_limit ? " / " + esc(alert.reading_limit) : "") + "</b>" +
      "<span>" + (alert.reading_limit ? "measured / limit" : "measured") + "</span>" +
      '<span class="ar-when">' + esc(timeAgo(alert.created_at)) + "</span>" +
      "</div>";
  }

  function actionsHTML(alert) {
    var html = "";
    // The deep link first and styled as the primary move: the quickest way to
    // deal with most alerts is to open the record they are about. Absent when
    // the alert has no specific record — a button that goes nowhere in
    // particular is worse than no button.
    if (alert.action_url) {
      html += '<a class="ar-btn primary" href="' + esc(alert.action_url) + '">' +
        '<i class="fa-solid fa-arrow-up-right-from-square"></i>' +
        (alert.object_display ? "Open " + esc(alert.object_display) : "Open record") +
        "</a>";
    }
    // The moves that carry the alert forward stay on the row; the rest go
    // behind the kebab. Six buttons of equal weight is not a hierarchy — it
    // asks the reader to pick, when what is wanted is the next step. Dismiss
    // in particular is not a peer of Resolve: one answers the problem, the
    // other waves it off, and they should not sit side by side in the same
    // size inviting the same click.
    var ONWARD = { acknowledge: 1, start: 1, resolve: 1 };
    // Icons for the menu only, where every item has one and a bare label
    // would sit out of line with the rest. The row's own buttons stay words.
    var MENU_ICON = { dismiss: "fa-solid fa-ban",
                      reopen: "fa-solid fa-rotate-left" };
    var onward = [], behind = [];
    (alert.available_actions || []).forEach(function (move) {
      if (ONWARD[move.key]) return onward.push(move);
      behind.push({ key: move.key, label: move.label,
                    icon: MENU_ICON[move.key] });
    });
    // Putting it in front of the supervisor who can go and look is a move on
    // the alert like any other; it is not in the transition table because it
    // changes no status, so it is added here rather than by the server.
    behind.unshift({ key: "notify", label: "Notify Supervisor",
                     icon: "fa-solid fa-user-tie" });
    // Whose job this is. A separate question from how far along it is, which
    // is why it is a menu item rather than another status button.
    behind.unshift({
      key: "assign", icon: "fa-solid fa-user-check",
      label: alert.assigned_to_name ? "Reassign…" : "Assign…"
    });
    // Everything that has already been done about it — acknowledged by whom,
    // notified to whom, dismissed with what reason. Reading, not a move, so
    // it is a link rather than a button.
    if (alert.detail_url) {
      behind.push({
        href: alert.detail_url, icon: "fa-solid fa-clock-rotate-left",
        label: alert.action_count
          ? "History (" + alert.action_count + ")"
          : "History"
      });
    }

    // Dismiss last, whatever order it arrived in. It is the one move that
    // closes an alert without anything being done about it, and it should be
    // the furthest thing from the pointer when the menu opens.
    behind.sort(function (a, b) {
      return (a.key === "dismiss" ? 1 : 0) - (b.key === "dismiss" ? 1 : 0);
    });

    onward.forEach(function (move) {
      // Resolve is the outcome the card exists to produce, and the only one
      // of the three that is good news, so it is the only one with any
      // colour on it. Acknowledge and Start are steps on the way.
      html += '<button type="button" class="ar-btn' +
        (move.key === "resolve" ? " ok" : "") + '" data-move="' +
        esc(move.key) + '">' + esc(move.label) + "</button>";
    });

    if (behind.length) {
      html += '<div class="ar-kebab-wrap">' +
        '<button type="button" class="ar-btn ar-kebab" aria-haspopup="true"' +
        ' aria-expanded="false" aria-label="More actions" title="More actions">' +
        '<i class="fa-solid fa-ellipsis-vertical"></i></button>' +
        '<div class="ar-menu" hidden>' +
        behind.map(function (move) {
          var inside = (move.icon ? '<i class="' + esc(move.icon) + '"></i>' : "") +
            esc(move.label);
          if (move.href) {
            return '<a class="ar-menu-item" href="' + esc(move.href) + '">' +
              inside + "</a>";
          }
          return '<button type="button" class="ar-menu-item' +
            (move.key === "dismiss" ? " danger" : "") +
            '" data-move="' + esc(move.key) + '">' + inside + "</button>";
        }).join("") +
        "</div></div>";
    }
    return html;
  }

  function rowHTML(alert, centre) {
    var sev = esc(alert.priority);
    return '<div class="ar-row ' + sev + '" data-id="' + alert.id + '">' +
      '<span class="ar-ic ' + sev + '"><i class="' + esc(alert.icon) + '"></i></span>' +
      '<div class="ar-body">' +
        '<div class="ar-line1">' +
          '<span class="ar-sev ' + sev + '">' + esc(alert.severity_label) + "</span>" +
          '<h3 class="ar-name">' + esc(alert.title) + "</h3>" +
          '<span class="ar-state ' + esc(alert.status_tone) + '">' +
            esc(alert.status_label) + "</span>" +
        "</div>" +
        (alert.message ? '<p class="ar-msg">' + esc(alert.message) + "</p>" : "") +
        '<div class="ar-meta">' + metaHTML(alert, centre) + "</div>" +
      "</div>" +
      metricHTML(alert) +
      '<div class="ar-actions">' + actionsHTML(alert) + "</div>" +
    "</div>";
  }

  function emptyHTML() {
    return '<div class="ar-empty">' +
      '<i class="fa-solid fa-circle-check"></i>' +
      "<p>All caught up</p>" +
      "<span>Nothing on your farms needs attention right now.</span>" +
      "</div>";
  }

  /* ------------------------------------------------------------ the widget */

  function init(root, options) {
    options = options || {};
    var centre = options.centre || "/notifications/";
    var csrf = root.dataset.csrf;

    var list = root.querySelector("#arList");
    var summaryEl = root.querySelector("#arSummary");
    var totalEl = root.querySelector("#arTotal");
    var foot = root.querySelector("#arFoot");
    var moreEl = root.querySelector("#arMore");
    var resolvedEl = root.querySelector("#arResolved");

    // The alerts currently drawn, by id, so a dialog can name the one it is
    // about without re-reading it out of the DOM.
    var loaded = {};

    function draw(data) {
      var rows = data.results || [];
      var summary = data.summary || {};

      loaded = {};
      rows.forEach(function (alert) { loaded[alert.id] = alert; });

      list.innerHTML = rows.length
        ? rows.map(function (alert) { return rowHTML(alert, centre); }).join("")
        : emptyHTML();
      summaryEl.innerHTML = summaryHTML(summary, centre);

      totalEl.textContent = summary.total || 0;
      totalEl.hidden = !summary.total;
      totalEl.classList.toggle("has-critical", summary.critical > 0);

      var hidden = (summary.total || 0) - (summary.shown || 0);
      moreEl.innerHTML = hidden > 0
        ? '<a href="' + centreLink(centre) + '">' + hidden + " more open</a>"
        : (summary.total ? summary.total + " open" : "");
      resolvedEl.innerHTML = summary.resolved_today
        ? '<span class="ar-done"><i class="fa-solid fa-check me-1"></i>' +
          summary.resolved_today + " resolved today</span>"
        : "";
      foot.hidden = false;
    }

    function load() {
      return fetch(API, { headers: { "X-Requested-With": "XMLHttpRequest" } })
        .then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then(draw)
        .catch(function () {
          list.innerHTML = '<div class="ar-empty">' +
            '<i class="fa-solid fa-triangle-exclamation text-muted"></i>' +
            "<p>Could not load alerts</p>" +
            "<span>The list will refresh on its own shortly.</span></div>";
        });
    }

    /* A move, from press to redraw. The button is held for the round trip —
       acknowledging twice is not harmful, but a button that does nothing
       visible is what makes people press it again. */
    function move(button, url, body) {
      var row = button.closest(".ar-row");
      var original = button.innerHTML;
      button.disabled = true;
      button.innerHTML = '<i class="fa-solid fa-spinner"></i>';
      if (row) row.classList.add("is-busy");

      return send(url, csrf, body).then(function (data) {
        var alert = data.alert || {};
        // A row that is no longer open is about to leave the list. It is shown
        // as done for a moment first: a row that simply vanishes leaves the
        // reader unsure which one they just closed.
        if (row && alert.status && alert.status !== "open" &&
            alert.status !== "acknowledged" && alert.status !== "in_progress") {
          row.classList.remove("is-busy");
          row.classList.add("is-done");
          return new Promise(function (resolve) {
            window.setTimeout(function () { load().then(resolve); }, 500);
          });
        }
        return load();
      }).catch(function (error) {
        button.disabled = false;
        button.innerHTML = original;
        if (row) row.classList.remove("is-busy");
        say("danger", error.message || "That did not go through. Try again.");
        throw error;
      });
    }

    /* ----------------------------------------------------------- dialogs */

    var notifyModal = document.getElementById("arNotifyModal");
    var dismissModal = document.getElementById("arDismissModal");
    var assignModal = document.getElementById("arAssignModal");
    var bs = window.bootstrap;
    var notifyBs = notifyModal && bs ? new bs.Modal(notifyModal) : null;
    var dismissBs = dismissModal && bs ? new bs.Modal(dismissModal) : null;
    var assignBs = assignModal && bs ? new bs.Modal(assignModal) : null;
    var pending = null;          // the alert a dialog is currently about

    function describe(alert) {
      return "<b>" + esc(alert.title) + "</b>" +
        (alert.place ? esc(alert.place) + " · " : "") +
        esc(alert.object_display || "");
    }

    function openDismiss(alert, button) {
      if (!dismissBs) return;
      pending = { alert: alert, button: button };
      document.getElementById("arDismissAlert").innerHTML = describe(alert);
      var box = document.getElementById("arDismissReason");
      box.value = "";
      box.classList.remove("is-invalid");
      dismissBs.show();
      window.setTimeout(function () { box.focus(); }, 300);
    }

    /* Who this alert could be handed to. The same list the escalation
       dialog offers — the people near enough to go and look at it — and one
       choice rather than several, because an alert with two owners has
       none. */
    function openAssign(alert, button) {
      if (!assignBs) return;
      pending = { alert: alert, button: button };
      document.getElementById("arAssignAlert").innerHTML = describe(alert);
      document.getElementById("arAssignNote").value = "";
      var people = document.getElementById("arAssignPeople");
      people.innerHTML = '<div class="text-muted small p-2">Loading…</div>';
      assignBs.show();

      fetch(API + alert.id + "/supervisors/",
            { headers: { "X-Requested-With": "XMLHttpRequest" } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var rows = data.results || [];
          if (!rows.length) {
            people.innerHTML = '<div class="text-muted small p-2">' +
              "No supervisor on this branch has a login, so there is nobody " +
              "this can be handed to.</div>";
            return;
          }
          // Pre-selected: whoever has it, or — when nobody does — the farm's
          // own supervisor, who is the answer often enough that the dialog
          // should be one click. Same default as Notify Supervisor.
          var already = rows.some(function (person) {
            return person.id === alert.assigned_to;
          });
          var html = rows.map(function (person) {
            var mine = already ? person.id === alert.assigned_to
                               : person.is_owner;
            return '<label class="ar-person">' +
              '<input type="radio" name="arAssignee" class="form-check-input"' +
                ' value="' + person.id + '"' + (mine ? " checked" : "") + ">" +
              "<span>" +
                '<span class="ar-person-name d-block">' + esc(person.name) + "</span>" +
                '<span class="ar-person-sub">' + esc(person.role) +
                  (person.branch ? " · " + esc(person.branch) : "") + "</span>" +
              "</span>" +
              (person.is_owner ? '<span class="ar-owner">This farm</span>' : "") +
              "</label>";
          }).join("");
          // Undoing a hand-off is its own choice, and it only exists once
          // somebody's name is on the alert.
          if (alert.assigned_to_name) {
            html += '<label class="ar-person">' +
              '<input type="radio" name="arAssignee" class="form-check-input" value="">' +
              "<span><span class=\"ar-person-name d-block\">Nobody</span>" +
              '<span class="ar-person-sub">Take ' +
                esc(alert.assigned_to_name) + "'s name off it</span></span></label>";
          }
          people.innerHTML = html;
        })
        .catch(function () {
          people.innerHTML = '<div class="text-muted small p-2">' +
            "Could not load the list of people.</div>";
        });
    }

    function openNotify(alert, button) {
      if (!notifyBs) return;
      pending = { alert: alert, button: button };
      document.getElementById("arNotifyAlert").innerHTML = describe(alert);
      document.getElementById("arNotifyNote").value = "";
      var people = document.getElementById("arNotifyPeople");
      people.innerHTML = '<div class="text-muted small p-2">Loading…</div>';
      notifyBs.show();

      fetch(API + alert.id + "/supervisors/",
            { headers: { "X-Requested-With": "XMLHttpRequest" } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var rows = data.results || [];
          if (!rows.length) {
            people.innerHTML = '<div class="text-muted small p-2">' +
              "No supervisor on this branch has a login, so there is nobody " +
              "this can be sent to." + "</div>";
            return;
          }
          people.innerHTML = rows.map(function (person) {
            return '<label class="ar-person">' +
              '<input type="checkbox" class="form-check-input" value="' +
                person.id + '"' + (person.is_owner ? " checked" : "") + ">" +
              "<span>" +
                '<span class="ar-person-name d-block">' + esc(person.name) + "</span>" +
                '<span class="ar-person-sub">' + esc(person.role) +
                  (person.branch ? " · " + esc(person.branch) : "") + "</span>" +
              "</span>" +
              (person.is_owner ? '<span class="ar-owner">This farm</span>' : "") +
              "</label>";
          }).join("");
        })
        .catch(function () {
          people.innerHTML = '<div class="text-muted small p-2">' +
            "Could not load the supervisor list.</div>";
        });
    }

    if (dismissModal) {
      document.getElementById("arDismissConfirm").addEventListener("click", function () {
        if (!pending) return;
        var box = document.getElementById("arDismissReason");
        var reason = box.value.trim();
        // Checked here as well as on the server, so the person is told before
        // the round trip rather than after it. The server's check is the one
        // that counts; this one is a courtesy.
        if (!reason) {
          box.classList.add("is-invalid");
          box.focus();
          return;
        }
        var self = this;
        self.disabled = true;
        move(pending.button, API + pending.alert.id + "/dismiss/", { reason: reason })
          .then(function () { dismissBs.hide(); })
          .catch(function () {})
          .then(function () { self.disabled = false; });
      });
    }

    if (assignModal) {
      document.getElementById("arAssignConfirm").addEventListener("click", function () {
        if (!pending) return;
        var picked = document.querySelector("#arAssignPeople input:checked");
        if (!picked) {
          say("danger", "Choose who this is for.");
          return;
        }
        var self = this;
        self.disabled = true;
        move(pending.button, API + pending.alert.id + "/assign/", {
          user_id: picked.value || null,
          note: document.getElementById("arAssignNote").value
        }).then(function () {
          assignBs.hide();
          say("success", picked.value
            ? "Assigned. It is on their dashboard now."
            : "Assignment cleared.");
        }).catch(function () {})
          .then(function () { self.disabled = false; });
      });
    }

    if (notifyModal) {
      document.getElementById("arNotifySend").addEventListener("click", function () {
        if (!pending) return;
        var ids = Array.prototype.slice.call(
          document.querySelectorAll("#arNotifyPeople input:checked")
        ).map(function (box) { return Number(box.value); });
        if (!ids.length) {
          say("danger", "Choose at least one person to notify.");
          return;
        }
        var self = this;
        self.disabled = true;
        move(pending.button, API + pending.alert.id + "/notify/", {
          user_ids: ids,
          note: document.getElementById("arNotifyNote").value
        }).then(function () {
          notifyBs.hide();
          say("success", ids.length === 1
            ? "Sent. It is on their dashboard now."
            : "Sent to " + ids.length + " people.");
        }).catch(function () {})
          .then(function () { self.disabled = false; });
      });
    }

    /* --------------------------------------------------------- the wiring */

    // One listener on the list rather than one per button: the rows are
    // replaced wholesale after every move, and handlers bound to the old ones
    // would go with them.
    // The kebab. Closes any other open one first, so two menus are never up at
    // once, and closes on a click anywhere else.
    list.addEventListener("click", function (event) {
      var kebab = event.target.closest(".ar-kebab");
      if (kebab) {
        event.preventDefault();
        var menu = kebab.nextElementSibling;
        var opening = menu.hidden;
        list.querySelectorAll(".ar-menu").forEach(function (m) { m.hidden = true; });
        list.querySelectorAll(".ar-kebab").forEach(function (k) {
          k.setAttribute("aria-expanded", "false");
        });
        menu.hidden = !opening;
        kebab.setAttribute("aria-expanded", opening ? "true" : "false");
        return;
      }
    });
    document.addEventListener("click", function (event) {
      if (event.target.closest(".ar-kebab-wrap")) return;
      list.querySelectorAll(".ar-menu").forEach(function (m) { m.hidden = true; });
      list.querySelectorAll(".ar-kebab").forEach(function (k) {
        k.setAttribute("aria-expanded", "false");
      });
    });

    list.addEventListener("click", function (event) {
      var button = event.target.closest("[data-move]");
      if (!button) return;
      var row = button.closest(".ar-row");
      var alert = row && loaded[row.dataset.id];
      if (!alert) return;

      var what = button.dataset.move;
      if (what === "dismiss") return openDismiss(alert, button);
      if (what === "notify") return openNotify(alert, button);
      if (what === "assign") return openAssign(alert, button);
      move(button, API + alert.id + "/" + what + "/", {}).catch(function () {});
    });

    load();
    // Slower than the bell's thirty seconds. This list is worked through by
    // hand, and redrawing it under somebody halfway through reading a row is
    // its own kind of failure.
    window.setInterval(load, 120000);
  }

  window.ActionRequired = { init: init, API: API };
})(window, document);
