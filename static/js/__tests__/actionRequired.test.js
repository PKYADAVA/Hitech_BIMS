/**
 * The Action Required card, and the links out of it.
 *
 * The bug these exist for: "22 more open" opened the notification centre on an
 * empty page. Nothing errored. The card counts alerts that are *open* and the
 * centre opens on *unread only*, which are different questions — an alert
 * somebody read on Monday and did nothing about is still open on Friday — so
 * following the link showed "Nothing matches these filters" and read as a dead
 * link rather than as two filters disagreeing.
 *
 * Every link out of this card therefore clears the read filter, and that is
 * worth pinning: it is invisible in the markup, costs nothing to drop in a
 * later edit, and the symptom is a blank page rather than a failure.
 *
 * The other half is that the card renders what the server decided. There is no
 * transition table here on purpose, so the test that matters is that the
 * buttons come from `available_actions` and nowhere else.
 */
const fs = require("fs");
const path = require("path");

const SCRIPT = path.join(__dirname, "..", "action-required.js");
const CENTRE = "/notifications/";

/** Just enough of alerthub.js for the widget to render. */
function alertHubStub(win) {
  win.AlertHub = {
    esc: (value) =>
      value === null || value === undefined
        ? ""
        : String(value).replace(/[&<>"']/g, (c) =>
            ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])),
    timeAgo: () => "just now",
  };
}

function anAlert(over) {
  return Object.assign(
    {
      id: 1,
      rule_key: "inventory.negative_stock",
      priority: "critical",
      severity_label: "Critical",
      status: "open",
      status_label: "Open",
      status_tone: "open",
      status_changed_by_name: "",
      icon: "fa-solid fa-boxes-stacked",
      title: "Negative Stock",
      message: "Starter Feed at Test Farm shows -60.",
      place: "Test Farm",
      object_display: "Starter Feed",
      action_url: "/stock-report/?item=4",
      reading: "-60",
      created_at: "2026-09-13T00:00:00Z",
      more_like_this: 0,
      available_actions: [
        { key: "acknowledge", label: "Acknowledge", needs_reason: false },
        { key: "dismiss", label: "Dismiss", needs_reason: true },
      ],
    },
    over || {}
  );
}

function payload(rows, summary) {
  return {
    results: rows,
    summary: Object.assign(
      { total: rows.length, shown: rows.length, critical: 0, high: 0,
        medium: 0, low: 0, resolved_today: 0 },
      summary || {}
    ),
  };
}

describe("the Action Required card", () => {
  let root;

  /** Render the card once against a canned API response. */
  async function render(data) {
    document.body.innerHTML = `
      <div class="ar-card" id="arWidget" data-csrf="tok">
        <div class="ar-head">
          <span class="ar-total" id="arTotal" hidden>0</span>
          <div class="ar-summary" id="arSummary"></div>
        </div>
        <div class="ar-list" id="arList"></div>
        <div class="ar-foot" id="arFoot" hidden>
          <span id="arMore"></span><span id="arResolved"></span>
        </div>
      </div>`;
    window.fetch = jest.fn(() =>
      Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data) })
    );
    alertHubStub(window);
    window.eval(fs.readFileSync(SCRIPT, "utf8"));
    root = document.getElementById("arWidget");
    window.ActionRequired.init(root, { centre: CENTRE });
    // One turn for the fetch promise, one for the .then that draws.
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  }

  function hrefs() {
    return Array.from(root.querySelectorAll("a[href]")).map((a) => a.getAttribute("href"));
  }

  describe("every link into the notification centre", () => {
    it("clears the read filter, so the page it opens is not empty", async () => {
      await render(
        payload([anAlert({ more_like_this: 16 })], { total: 23, shown: 1, critical: 23 })
      );
      const centreLinks = hrefs().filter((h) => h.startsWith(CENTRE));
      expect(centreLinks.length).toBeGreaterThan(0);
      centreLinks.forEach((href) => expect(href).toContain("is_read="));
    });

    it("sends the footer count to the whole open list", async () => {
      await render(payload([anAlert()], { total: 23, shown: 1 }));
      const more = document.getElementById("arMore").querySelector("a");
      expect(more.textContent).toBe("22 more open");
      expect(more.getAttribute("href")).toBe("/notifications/?is_read=");
    });

    it("sends a severity chip to that severity", async () => {
      await render(payload([anAlert()], { critical: 18, high: 3 }));
      const chip = document.querySelector("#arSummary .ar-sum.critical");
      expect(chip.getAttribute("href")).toContain("priority=critical");
      expect(chip.getAttribute("href")).toContain("is_read=");
    });

    it("sends a capped row to the rest of its own rule, not to the whole feed", async () => {
      await render(payload([anAlert({ more_like_this: 16 })]));
      const more = document.querySelector(".ar-more");
      expect(more.textContent).toBe("+16 more like this");
      expect(more.getAttribute("href")).toContain("rule_key=inventory.negative_stock");
    });
  });

  describe("the severity chips", () => {
    it("show all four levels, in a fixed order", async () => {
      // They read as one scale somebody can scan. Chips that came and went
      // with the counts changed width and position between refreshes, and
      // "nothing at Information" is itself worth seeing.
      await render(payload([anAlert()], { critical: 2, high: 0, medium: 0, low: 0 }));
      const chips = Array.from(document.querySelectorAll("#arSummary .ar-sum"));
      expect(chips.map((c) => c.textContent.replace(/\s+/g, " ").trim())).toEqual([
        "2 Critical", "0 High", "0 Warning", "0 Information",
      ]);
    });

    it("mark an empty level so a zero is not read as a count", async () => {
      await render(payload([anAlert()], { critical: 2, high: 0, medium: 0, low: 0 }));
      const chips = document.querySelectorAll("#arSummary .ar-sum");
      expect(chips[0].classList.contains("is-zero")).toBe(false);
      expect(chips[1].classList.contains("is-zero")).toBe(true);
    });

    it("name a level the same way the row badge does", async () => {
      // A chip reading "Warning" over a badge reading "Medium" is two names
      // for one thing on one card.
      await render(
        payload([anAlert({ priority: "medium", severity_label: "Warning" })], { medium: 1 })
      );
      expect(document.querySelector("#arSummary .ar-sum.medium").textContent)
        .toContain("Warning");
      expect(document.querySelector(".ar-sev").textContent).toBe("Warning");
    });
  });

  describe("the buttons on a row", () => {
    it("are the ones the server said were available", async () => {
      await render(payload([anAlert()]));
      const moves = Array.from(root.querySelectorAll("[data-move]")).map(
        (el) => el.dataset.move
      );
      // Every move the server offered is on the row somewhere — dismiss
      // behind the kebab rather than on the face of it, but present.
      expect(moves).toEqual(expect.arrayContaining(["acknowledge", "dismiss"]));
      // Notify and Assign are offered on every alert: they are not state
      // transitions, so the server does not list them.
      expect(moves).toEqual(expect.arrayContaining(["notify", "assign"]));
    });

    it("put the forward moves on the row and the rest behind the kebab", async () => {
      // Resolve is the outcome this card exists to produce; dismissing closes
      // an alert with nothing done about it, so it is the furthest thing from
      // the pointer.
      await render(payload([anAlert({ available_actions: [
        { key: "resolve", label: "Resolve", needs_reason: false },
        { key: "dismiss", label: "Dismiss", needs_reason: true },
      ] })]));
      const onRow = Array.from(root.querySelectorAll(".ar-actions > .ar-btn[data-move]"))
        .map((el) => el.dataset.move);
      const behind = Array.from(root.querySelectorAll(".ar-menu [data-move]"))
        .map((el) => el.dataset.move);
      expect(onRow).toContain("resolve");
      expect(onRow).not.toContain("dismiss");
      expect(behind).toContain("dismiss");
    });

    it("do not invent one the server left out", async () => {
      // The whole reason there is no transition table in this file: a second
      // copy would drift, and the visible copy is the one that would be wrong.
      await render(payload([anAlert({ available_actions: [
        { key: "resolve", label: "Resolve", needs_reason: false },
      ] })]));
      const moves = Array.from(root.querySelectorAll("[data-move]")).map(
        (el) => el.dataset.move
      );
      expect(moves).not.toContain("acknowledge");
      expect(moves).not.toContain("start");
      expect(moves).not.toContain("dismiss");
      expect(moves).toContain("resolve");
    });

    it("lead with the record the alert is about", async () => {
      await render(payload([anAlert()]));
      const primary = root.querySelector(".ar-btn.primary");
      expect(primary.getAttribute("href")).toBe("/stock-report/?item=4");
      expect(primary.textContent).toContain("Starter Feed");
    });

    it("offer no record button when there is no specific record", async () => {
      // A button that goes nowhere in particular is worse than no button.
      await render(payload([anAlert({ action_url: "" })]));
      expect(root.querySelector(".ar-btn.primary")).toBeNull();
    });
  });

  describe("when there is nothing to do", () => {
    it("says so rather than showing an empty box", async () => {
      await render(payload([], { total: 0, shown: 0 }));
      expect(document.getElementById("arList").textContent).toContain("All caught up");
    });

    it("puts no count in the header", async () => {
      await render(payload([], { total: 0, shown: 0 }));
      expect(document.getElementById("arTotal").hidden).toBe(true);
    });
  });

  describe("what a row says about itself", () => {
    it("names who picked it up, once somebody has", async () => {
      // The status chip says an alert was picked up; without a name beside it
      // nobody knows whether to go and look themselves.
      await render(
        payload([anAlert({ status: "acknowledged", status_label: "Acknowledged",
                           status_tone: "acknowledged",
                           status_changed_by_name: "Ravi Kumar" })])
      );
      expect(root.querySelector(".ar-meta").textContent).toContain("Acknowledged by Ravi Kumar");
    });

    it("says nothing about who has it while nobody does", async () => {
      await render(payload([anAlert({ status_changed_by_name: "Ravi Kumar" })]));
      expect(root.querySelector(".ar-meta").textContent).not.toContain("Ravi Kumar");
    });

    it("escapes what came from the database", async () => {
      await render(payload([anAlert({ title: '<img src=x onerror="alert(1)">' })]));
      expect(root.querySelector(".ar-name").querySelector("img")).toBeNull();
      expect(root.querySelector(".ar-name").textContent).toContain("<img");
    });
  });
});
