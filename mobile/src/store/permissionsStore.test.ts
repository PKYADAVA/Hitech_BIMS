/**
 * The client half of Mobile Access.
 *
 * The subtractive rule now lives on both sides of the wire: the server decides
 * and the client hides. The server half has Django tests; this is the half
 * that used to have none, and it is where a wrong answer is invisible — a
 * button that should be gone simply stays on screen.
 */
import * as api from "@/api/permissions";
import { usePermissionsStore } from "@/store/permissionsStore";

jest.mock("@/api/permissions", () => ({
  ...jest.requireActual("@/api/permissions"),
  fetchPermissions: jest.fn(),
}));

const fetchPermissions = api.fetchPermissions as jest.MockedFunction<
  typeof api.fetchPermissions
>;

/** A server answer with everything off unless named. */
function payload(over: Partial<api.Permissions> = {}): api.Permissions {
  return {
    unrestricted: false,
    nav_groups: [],
    nav_order: [],
    tabs: [],
    module_actions: {},
    tab_actions: {},
    ...over,
  };
}

const store = () => usePermissionsStore.getState();

beforeEach(() => {
  usePermissionsStore.getState().reset();
  fetchPermissions.mockReset();
});

describe("before anything is loaded", () => {
  it("fails open so a slow network never looks like a lockout", () => {
    expect(store().canModule("broiler")).toBe(true);
    expect(store().canTabAction("daily_entry_list", "edit")).toBe(true);
  });
});

describe("load", () => {
  it("fails open when the very first fetch fails", async () => {
    fetchPermissions.mockRejectedValue(new Error("offline"));
    await store().load();
    expect(store().unrestricted).toBe(true);
    expect(store().canModule("broiler")).toBe(true);
  });

  it("keeps what it had when a later fetch fails", async () => {
    fetchPermissions.mockResolvedValue(payload({ nav_groups: ["broiler"] }));
    await store().load();

    fetchPermissions.mockRejectedValue(new Error("offline"));
    await store().refresh();

    // Not thrown open: falling open after a real answer would *widen* access.
    expect(store().unrestricted).toBe(false);
    expect(store().canModule("broiler")).toBe(true);
    expect(store().canModule("sales")).toBe(false);
  });
});

describe("module gating", () => {
  beforeEach(async () => {
    fetchPermissions.mockResolvedValue(payload({ nav_groups: ["broiler", "hatchery"] }));
    await store().load();
  });

  it("shows a module the server listed", () => {
    expect(store().canModule("broiler")).toBe(true);
  });

  it("hides one it did not", () => {
    expect(store().canModule("sales")).toBe(false);
  });

  it("maps sms onto the notifications nav", async () => {
    fetchPermissions.mockResolvedValue(payload({ nav_groups: ["notifications"] }));
    await store().load();
    expect(store().canModule("sms")).toBe(true);
  });

  it("lets a superuser through regardless", async () => {
    fetchPermissions.mockResolvedValue(payload({ unrestricted: true }));
    await store().load();
    expect(store().canModule("sales")).toBe(true);
  });
});

describe("per-screen actions", () => {
  beforeEach(async () => {
    fetchPermissions.mockResolvedValue(
      payload({
        nav_groups: ["broiler"],
        tabs: ["daily_entry_list", "bird_sale_list"],
        module_actions: { broiler: { add: true, edit: true, delete: true } },
        tab_actions: {
          daily_entry_list: { view: true, add: true, edit: true, delete: false },
          bird_sale_list: { view: true, add: false, edit: false, delete: false },
        },
      })
    );
    await store().load();
  });

  it("answers per screen, not per module", () => {
    expect(store().canResource("broiler-daily-entries", "broiler", "edit")).toBe(true);
    // The module says edit is fine; this screen says otherwise. The whole
    // point of the per-screen matrix is that the screen wins.
    expect(store().canResource("broiler-bird-sales", "broiler", "edit")).toBe(false);
  });

  it("hides delete on a screen that allows add", () => {
    expect(store().canResource("broiler-daily-entries", "broiler", "add")).toBe(true);
    expect(store().canResource("broiler-daily-entries", "broiler", "delete")).toBe(false);
  });

  it("falls back to the module for a screen the server did not send", () => {
    // Not in tab_actions — Mobile Access has no opinion, so do not invent one.
    expect(store().canResource("broiler-batches", "broiler", "add")).toBe(true);
  });

  it("falls back to the module for an unmapped resource key", () => {
    expect(store().canResource("not-a-resource", "broiler", "add")).toBe(true);
  });

  it("still lets a superuser do everything", async () => {
    fetchPermissions.mockResolvedValue(payload({ unrestricted: true }));
    await store().load();
    expect(store().canResource("broiler-bird-sales", "broiler", "delete")).toBe(true);
  });
});

describe("home hub order", () => {
  it("uses the order the server sent, not alphabetical", async () => {
    fetchPermissions.mockResolvedValue(
      payload({
        nav_groups: ["broiler", "sales", "hatchery"],
        nav_order: ["sales", "hatchery", "broiler"],
      })
    );
    await store().load();
    expect(store().moduleOrder()).toEqual(["sales", "hatchery", "broiler"]);
  });

  it("is empty until the server says otherwise", () => {
    expect(store().moduleOrder()).toEqual([]);
  });
});

describe("reset", () => {
  it("clears everything on logout", async () => {
    fetchPermissions.mockResolvedValue(payload({ nav_groups: ["broiler"] }));
    await store().load();
    store().reset();
    expect(store().loaded).toBe(false);
    expect(store().navOrder).toEqual([]);
    expect(store().tabActions).toEqual({});
  });
});
