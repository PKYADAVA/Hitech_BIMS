/* Alerts & Notifications — shared browser client.
 *
 * One implementation of "fetch alerts and draw them", used by the navbar bell,
 * the notification centre and the dashboard widget. They previously would have
 * been three copies of the same escaping, time formatting and priority mapping;
 * a card that renders differently in two places is how a priority colour ends
 * up meaning two things.
 *
 * Talks to /api/alerthub/. CSRF_COOKIE_HTTPONLY is on in this project, so the
 * token cannot be read from the cookie and is injected from the template into
 * a data-csrf attribute.
 *
 * Bump the ?v= in the <script> tag when this changes — WhiteNoise serves
 * staticfiles/, so edits here are invisible until collectstatic runs.
 */
(function (window, document) {
  "use strict";

  var API = "/api/alerthub/notifications/";

  /* ------------------------------------------------------------ utilities */

  function esc(value) {
    if (value === null || value === undefined) return "";
    return String(value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function timeAgo(iso) {
    var then = new Date(iso);
    var secs = Math.floor((Date.now() - then.getTime()) / 1000);
    if (secs < 60) return "just now";
    if (secs < 3600) return Math.floor(secs / 60) + " minutes ago";
    if (secs < 86400) return Math.floor(secs / 3600) + " hours ago";
    if (secs < 604800) return Math.floor(secs / 86400) + " days ago";
    return then.toLocaleDateString();
  }

  /* Today / Yesterday / Earlier — compared on local calendar days rather than
     elapsed hours, so something from 11pm last night reads as "Yesterday"
     rather than "Today" at 1am. */
  function dayBucket(iso) {
    var d = new Date(iso);
    var today = new Date();
    var startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    var startOfYesterday = new Date(startOfToday);
    startOfYesterday.setDate(startOfYesterday.getDate() - 1);
    if (d >= startOfToday) return "Today";
    if (d >= startOfYesterday) return "Yesterday";
    return "Earlier";
  }

  function request(url, options) {
    options = options || {};
    options.headers = Object.assign(
      { "X-Requested-With": "XMLHttpRequest" }, options.headers || {}
    );
    return fetch(url, options).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.status === 204 ? null : response.json();
    });
  }

  function post(url, csrf) {
    return request(url, { method: "POST", headers: { "X-CSRFToken": csrf } });
  }

  /* --------------------------------------------------------------- markup */

  /* One card, used everywhere. `compact` drops the message body for the bell's
     narrower dropdown. */
  function itemHTML(n, opts) {
    opts = opts || {};
    var place = n.place ? '<span>' + esc(n.place) + "</span>" : "";
    var voucher = n.voucher_no ? "<span>" + esc(n.voucher_no) + "</span>" : "";
    var message = opts.compact && !n.message
      ? ""
      : '<p class="ah-item-msg">' + esc(n.message) + "</p>";

    return (
      '<a class="ah-item ah-rail ' + esc(n.priority) + (n.is_read ? "" : " unread") +
        '" href="' + esc(n.detail_url) + '" data-id="' + n.id + '">' +
        '<span class="ah-dot"></span>' +
        '<span class="ah-ic ' + esc(n.priority) + '"><i class="' + esc(n.icon) + '"></i></span>' +
        '<span class="ah-item-body">' +
          '<p class="ah-item-title">' + esc(n.title) +
            '<span class="ah-pill ' + esc(n.priority) + '">' + esc(n.priority_label) + "</span>" +
          "</p>" +
          message +
          '<div class="ah-item-meta">' +
            '<span class="ah-chip">' + esc(n.module_label) + "</span>" +
            place + voucher +
            "<span>" + esc(timeAgo(n.created_at)) + "</span>" +
          "</div>" +
        "</span>" +
      "</a>"
    );
  }

  /* Rows grouped under sticky Today / Yesterday / Earlier headings. */
  function groupedHTML(rows, opts) {
    var order = ["Today", "Yesterday", "Earlier"];
    var buckets = { Today: [], Yesterday: [], Earlier: [] };
    rows.forEach(function (row) { buckets[dayBucket(row.created_at)].push(row); });

    return order.filter(function (name) { return buckets[name].length; })
      .map(function (name) {
        return '<div class="ah-group-head">' + name + "</div>" +
          buckets[name].map(function (row) { return itemHTML(row, opts); }).join("");
      }).join("");
  }

  function emptyHTML(text, icon) {
    return '<div class="ah-empty"><i class="' + (icon || "fa-regular fa-bell-slash") +
      '"></i>' + esc(text) + "</div>";
  }

  /* ----------------------------------------------------------- the bell */

  function initBell(root) {
    var csrf = root.dataset.csrf;
    var badge = root.querySelector("#ahBellBadge");
    var list = root.querySelector("#ahBellList");
    var button = root.querySelector("#ahBellBtn");
    var menu = root.querySelector(".ah-bell-menu");
    var markAll = root.querySelector("#ahMarkAll");
    var prefs = { sound: root.dataset.sound === "1", desktop: root.dataset.desktop === "1" };
    var lastCount = null;

    function setBadge(n) {
      if (n > 0) {
        badge.textContent = n > 99 ? "99+" : n;
        badge.classList.remove("d-none");
        // Only react to a genuine increase; re-drawing the same number must
        // not re-fire the animation or the sound on every poll.
        if (lastCount !== null && n > lastCount) {
          badge.classList.remove("ah-bump");
          void badge.offsetWidth;            // restart the CSS animation
          badge.classList.add("ah-bump");
          announce(n - lastCount);
        }
      } else {
        badge.classList.add("d-none");
      }
      lastCount = n;
    }

    function announce(added) {
      if (prefs.sound) beep();
      if (prefs.desktop && window.Notification && Notification.permission === "granted") {
        try {
          new Notification("Hi Tech BIMS", {
            body: added + " new alert" + (added === 1 ? "" : "s"),
            tag: "alerthub",
          });
        } catch (e) { /* some browsers refuse outside a user gesture */ }
      }
    }

    /* A short tone from the Web Audio API rather than an audio file, so the
       module ships no binary asset for a two-note chime. */
    function beep() {
      try {
        var Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return;
        var ctx = new Ctx();
        var osc = ctx.createOscillator();
        var gain = ctx.createGain();
        osc.connect(gain); gain.connect(ctx.destination);
        osc.type = "sine";
        osc.frequency.value = 880;
        gain.gain.setValueAtTime(0.001, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + 0.01);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
        osc.start(); osc.stop(ctx.currentTime + 0.36);
        osc.onended = function () { ctx.close(); };
      } catch (e) { /* audio is a nicety, never an error */ }
    }

    function refreshCount() {
      return request(API + "unread_count/")
        .then(function (data) { setBadge(data.unread || 0); })
        .catch(function () { /* leave the badge as it was on a network hiccup */ });
    }

    function loadList() {
      list.innerHTML = '<div class="ah-empty">Loading…</div>';
      request(API + "recent/")
        .then(function (data) {
          var rows = data.results || [];
          list.innerHTML = rows.length
            ? groupedHTML(rows, { compact: true })
            : emptyHTML("You're all caught up");
          setBadge(data.unread || 0);
          wireRows();
        })
        .catch(function () {
          list.innerHTML = emptyHTML("Could not load notifications",
                                     "fa-solid fa-triangle-exclamation");
        });
    }

    /* Clicking a row marks it read and then follows the link. The mark is
       fired without awaiting it: the navigation is the point, and blocking it
       on a POST would make the bell feel slow. */
    function wireRows() {
      list.querySelectorAll(".ah-item").forEach(function (el) {
        el.addEventListener("click", function () {
          post(API + el.dataset.id + "/mark_read/", csrf).catch(function () {});
          el.classList.remove("unread");
        });
      });
    }

    function positionMenu() {
      menu.style.top = (button.getBoundingClientRect().bottom + 8) + "px";
    }

    button.addEventListener("show.bs.dropdown", function () {
      positionMenu();
      loadList();
    });
    window.addEventListener("resize", function () {
      if (menu.classList.contains("show")) positionMenu();
    });
    markAll.addEventListener("click", function (event) {
      event.stopPropagation();
      event.preventDefault();
      post(API + "mark_all_read/", csrf).then(function () {
        list.querySelectorAll(".ah-item.unread").forEach(function (el) {
          el.classList.remove("unread");
        });
        setBadge(0);
      }).catch(function () {});
    });

    if (prefs.desktop && window.Notification && Notification.permission === "default") {
      Notification.requestPermission();
    }

    refreshCount();
    setInterval(refreshCount, 30000);
  }

  /* ------------------------------------------------------------- exports */

  window.AlertHub = {
    API: API,
    esc: esc,
    request: request,
    post: post,
    timeAgo: timeAgo,
    dayBucket: dayBucket,
    itemHTML: itemHTML,
    groupedHTML: groupedHTML,
    emptyHTML: emptyHTML,
    initBell: initBell,
  };

  document.addEventListener("DOMContentLoaded", function () {
    var bell = document.getElementById("ahBellWrap");
    if (bell) initBell(bell);
  });
})(window, document);
