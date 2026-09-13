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
    return levels.filter(function (level) { return summary[level[0]] > 0; })
      .map(function (level) {
        return '<a class="ar-sum ' + level[0] + '" href="' +
          centreLink(centre, { priority: level[0] }) + '"><b>' +
          summary[level[0]] + "</b> " + level[1] + "</a>";
      }).join("");
  }

  function metaHTML(alert, centre) {
    var bits = [];
    if (alert.place) bits.push(esc(alert.place));
    if (alert.object_display) bits.push(esc(alert.object_display));
    bits.push(esc(timeAgo(alert.created_at)));
    // Who has it, when somebody has. The status chip says an alert was picked
    // up; without a name beside it, nobody knows whether to pick it up too.
    if (alert.status_changed_by_name && alert.status !== "open") {
      bits.push(esc(alert.status_label) + " by " + esc(alert.status_changed_by_name));
    }
    // The rest of this rule, which the per-rule cap kept off the card. The
    // link goes to the centre filtered to that rule, so "+16 more" leads
    // somewhere that shows the sixteen rather than the whole feed.
    if (alert.more_like_this > 0) {
      bits.push('<a class="ar-more" href="' +
        centreLink(centre, { rule_key: alert.rule_key }) + '">+' +
        alert.more_like_this + " more like this</a>");
    }
    return bits.join(' <span class="ar-sep">·</span> ');
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
    (alert.available_actions || []).forEach(function (move) {
      html += '<button type="button" class="ar-btn' +
        (move.key === "dismiss" ? " danger" : "") +
        '" data-move="' + esc(move.key) + '">' + esc(move.label) + "</button>";
    });
    html += '<button type="button" class="ar-btn" data-move="notify">' +
      '<i class="fa-solid fa-user-tie"></i>Notify Supervisor</button>';
    return html;
  }

  function rowHTML(alert, centre) {
    var sev = esc(alert.priority);
    return '<div class="ar-row ' + sev + '" data-id="' + alert.id + '">' +
      '<span class="ar-ic ' + sev + '"><i class="' + esc(alert.icon) + '"></i></span>' +
      '<div class="ar-body">' +
        '<div class="ar-line1">' +
          '<span class="ar-sev ' + sev + '">' + esc(alert.severity_label) + "</span>" +
          '<span class="ar-state ' + esc(alert.status_tone) + '">' +
            esc(alert.status_label) + "</span>" +
          '<h3 class="ar-name">' + esc(alert.title) + "</h3>" +
        "</div>" +
        (alert.message ? '<p class="ar-msg">' + esc(alert.message) + "</p>" : "") +
        '<div class="ar-meta">' + metaHTML(alert, centre) + "</div>" +
      "</div>" +
      (alert.reading
        ? '<div class="ar-metric"><b>' + esc(alert.reading) +
          "</b><span>measured / limit</span></div>"
        : '<div class="ar-metric"></div>') +
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
    var bs = window.bootstrap;
    var notifyBs = notifyModal && bs ? new bs.Modal(notifyModal) : null;
    var dismissBs = dismissModal && bs ? new bs.Modal(dismissModal) : null;
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
    list.addEventListener("click", function (event) {
      var button = event.target.closest("[data-move]");
      if (!button) return;
      var row = button.closest(".ar-row");
      var alert = row && loaded[row.dataset.id];
      if (!alert) return;

      var what = button.dataset.move;
      if (what === "dismiss") return openDismiss(alert, button);
      if (what === "notify") return openNotify(alert, button);
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
