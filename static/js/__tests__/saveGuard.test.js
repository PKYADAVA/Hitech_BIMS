/**
 * One save per press, and one key per attempt.
 *
 * main.js had no tests at all — seven hundred lines of behaviour the whole ERP
 * loads on every page, while the phone app next door has two hundred and
 * forty. That asymmetry is why a wrong decision in here reached production:
 * the idempotency key was retired whenever a request settled, including when
 * it settled with no answer, which is the one case the key exists for. On a
 * slow link the save lands, the answer is lost, the key is thrown away, the
 * person presses save again — and the retry carries a new key the server
 * cannot recognise. Two records.
 *
 * Nothing checked that, so it shipped. These tests are the check.
 *
 * main.js is a browser script, not a module, so it is read and evaluated into
 * jsdom with a jQuery stub standing in for the plugins it expects. Everything
 * under test reaches the outside through `window.fetch`, which is what the
 * assertions watch.
 */
const fs = require("fs");
const path = require("path");

const MAIN_JS = path.join(__dirname, "..", "main.js");

/** Enough jQuery for main.js to finish loading. It registers handlers and
 *  defines plugins at load; none of that is what these tests are about. */
function jqueryStub() {
  const chain = new Proxy(function () {}, {
    get: (target, prop) => {
      if (prop === "then") return undefined;      // not a promise
      return chain;
    },
    apply: () => chain,
  });
  const $ = function () { return chain; };
  Object.assign($, {
    // DataTables and Select2 defaults are configured at load; the shapes have
    // to exist for that to run, but nothing here reads them back.
    fn: { dataTable: { defaults: {} }, select2: { defaults: { set: () => {} } } },
    extend: () => ({}),
    ajax: () => chain, ajaxSetup: () => {},
    get: () => chain, post: () => chain, getJSON: () => chain,
    ready: (fn) => fn && fn(),
  });
  // ajaxSend / ajaxComplete are registered on $(document); the stub's proxy
  // swallows them. The fetch path is what these tests exercise.
  return $;
}

function loadMainJs(win) {
  win.jQuery = win.$ = jqueryStub();
  win.bootstrap = { Modal: function () { return { show() {}, hide() {} }; } };
  // Evaluated in the window's own realm rather than a fresh vm context: the
  // script is written for a browser and reaches for `window` and `document`
  // at load, which a separate context would not have.
  win.eval(fs.readFileSync(MAIN_JS, "utf8"));
}

describe("the save guard", () => {
  let calls;
  let toasts;

  beforeEach(() => {
    document.body.innerHTML = "";
    calls = [];
    // A fetch that never settles unless a test settles it, so "in flight" is
    // an observable state rather than a race with the event loop.
    window.fetch = jest.fn((url, init) => {
      const record = { url, init, headers: (init && init.headers) || null };
      let settle;
      record.promise = new Promise((resolve, reject) => {
        settle = { resolve, reject };
      });
      record.settle = settle;
      calls.push(record);
      return record.promise;
    });
    window.crypto = { randomUUID: () => "key-" + (calls.length + 1) + "-" + Math.random() };
    toasts = [];
    window.showToast = (type, message) => toasts.push({ type, message });
    loadMainJs(window);
  });

  function formWithButton() {
    const form = document.createElement("form");
    const button = document.createElement("button");
    button.type = "submit";
    form.appendChild(button);
    // preventDefault, because this stands for a form that saves over the
    // network — which is every form these tests are about. A form that does
    // *not* prevent its submit is navigating away, and the guard deliberately
    // leaves that button held: the page it belongs to is about to be gone.
    form.addEventListener("submit", (e) => e.preventDefault());
    document.body.appendChild(form);
    return { form, button };
  }

  /** A press that starts a write, the way a page's own handler would. */
  function press(button, url = "/save/") {
    button.click();
    return window.fetch(url, { method: "POST", body: "{}" });
  }

  function keyOf(call) {
    const headers = call.init && call.init.headers;
    return headers && typeof headers.get === "function"
      ? headers.get("Idempotency-Key") : null;
  }

  it("holds the button while its save is in flight", () => {
    const { button } = formWithButton();
    press(button);
    expect(button.disabled).toBe(true);
  });

  it("releases the button once the save is answered", async () => {
    const { button } = formWithButton();
    press(button);
    calls[0].settle.resolve({ status: 200 });
    await calls[0].promise;
    await Promise.resolve();
    expect(button.disabled).toBe(false);
  });

  it("releases the button when nothing comes back, so it can be tried again", async () => {
    const { button } = formWithButton();
    press(button).catch(() => {});
    calls[0].settle.reject(new Error("network"));
    await new Promise((r) => setTimeout(r, 0));
    expect(button.disabled).toBe(false);
  });

  it("sends an idempotency key with every write", () => {
    const { button } = formWithButton();
    press(button);
    expect(keyOf(calls[0])).toBeTruthy();
  });

  it("sends no key on a read", () => {
    window.fetch("/list/", { method: "GET" });
    expect(keyOf(calls[0])).toBeNull();
  });

  describe("the key", () => {
    it("is reused when the first attempt got no answer", async () => {
      // The bug this file exists for. The save may well have landed; only the
      // answer was lost, so the retry has to be recognisable as the same one.
      const { button } = formWithButton();
      press(button).catch(() => {});
      calls[0].settle.reject(new Error("network"));
      await new Promise((r) => setTimeout(r, 0));

      press(button);
      expect(keyOf(calls[1])).toBe(keyOf(calls[0]));
    });

    it("is retired once the save is known to have landed", async () => {
      const { button } = formWithButton();
      press(button);
      calls[0].settle.resolve({ status: 201 });
      await calls[0].promise;
      await Promise.resolve();

      press(button);
      expect(keyOf(calls[1])).not.toBe(keyOf(calls[0]));
    });

    it("is retired when the payload was refused", async () => {
      // The person fixes the field and presses again. That is a different
      // save, and answering it from the stored complaint about what they just
      // corrected would be worse than useless.
      const { button } = formWithButton();
      press(button);
      calls[0].settle.resolve({ status: 400 });
      await calls[0].promise;
      await Promise.resolve();

      press(button);
      expect(keyOf(calls[1])).not.toBe(keyOf(calls[0]));
    });

    it("survives a server error, which says nothing about what was written", async () => {
      const { button } = formWithButton();
      press(button);
      calls[0].settle.resolve({ status: 500 });
      await calls[0].promise;
      await Promise.resolve();

      press(button);
      expect(keyOf(calls[1])).toBe(keyOf(calls[0]));
    });

    it("belongs to the form, so two forms on a page never share one", () => {
      const first = formWithButton();
      const second = formWithButton();
      press(first.button);
      press(second.button);
      expect(keyOf(calls[1])).not.toBe(keyOf(calls[0]));
    });
  });


  describe("when a save does not get through", () => {
    it("says so, rather than leaving the button to look like it did nothing", async () => {
      // Silence is what makes somebody press save a second time.
      const { button } = formWithButton();
      press(button).catch(() => {});
      calls[0].settle.reject(new Error("network"));
      await new Promise((r) => setTimeout(r, 0));
      expect(toasts).toHaveLength(1);
      expect(toasts[0].type).toBe("danger");
    });

    it("does not claim the save failed when only the reply was lost", async () => {
      // It may well have been filed. Saying otherwise is a guess presented as
      // a fact, and the person then re-enters work that is already there.
      const { button } = formWithButton();
      press(button).catch(() => {});
      calls[0].settle.reject(new Error("network"));
      await new Promise((r) => setTimeout(r, 0));
      expect(toasts[0].message).toMatch(/may or may not have saved/i);
      expect(toasts[0].message).toMatch(/not be filed twice/i);
    });

    it("is plainer about a server error, where nothing was written", async () => {
      const { button } = formWithButton();
      press(button);
      calls[0].settle.resolve({ status: 500 });
      await calls[0].promise;
      await Promise.resolve();
      expect(toasts[0].message).toMatch(/could not save/i);
    });

    it("says nothing when the save went through", async () => {
      const { button } = formWithButton();
      press(button);
      calls[0].settle.resolve({ status: 200 });
      await calls[0].promise;
      await Promise.resolve();
      expect(toasts).toHaveLength(0);
    });

    it("says nothing when the page refused the payload", async () => {
      // A 400 arrives with the page's own message on it; a second notice
      // about the same thing is noise.
      const { button } = formWithButton();
      press(button);
      calls[0].settle.resolve({ status: 400 });
      await calls[0].promise;
      await Promise.resolve();
      expect(toasts).toHaveLength(0);
    });

    it("does not interrupt over a write nobody pressed a button for", async () => {
      // A background write failing is not something to put on screen.
      window.fetch("/background/", { method: "POST" }).catch(() => {});
      calls[0].settle.reject(new Error("network"));
      await new Promise((r) => setTimeout(r, 0));
      expect(toasts).toHaveLength(0);
    });
  });
});
