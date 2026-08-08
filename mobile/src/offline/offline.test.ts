/**
 * Saving with no signal, and getting it to the ERP afterwards.
 *
 * The behaviours worth pinning are the ones that lose or duplicate a round if
 * they go wrong: order, dependency, retry timing, and who an entry belongs to.
 */
jest.mock("react-native", () => ({ Platform: { OS: "web" } }));

jest.mock("@react-native-async-storage/async-storage", () => ({
  __esModule: true,
  default: {
    getItem: jest.fn(async () => null),
    setItem: jest.fn(async () => undefined),
    removeItem: jest.fn(async () => undefined),
  },
}));

jest.mock("@/api/client", () => ({
  http: { post: jest.fn(), patch: jest.fn(), put: jest.fn(), delete: jest.fn() },
}));

jest.mock("./files", () => ({
  persistForOffline: jest.fn(async (field: string, uri: string) => ({
    field, uri: `kept://${uri.split("/").pop()}`, name: "shot.jpg", type: "image/jpeg",
  })),
  discardOfflineFile: jest.fn(async () => undefined),
}));

import { onlineManager } from "@tanstack/react-query";

import { http } from "@/api/client";
import { resetDatabase } from "./db";
import { runSync, retryEntry, resolveConflict, discardEntry, humanError } from "./engine";
import { nextOfflineNumber } from "./identity";
import { listEntries, sendableEntries, setQueueUser, summarise } from "./queue";
import { saveOffline } from "./save";

const post = http.post as jest.Mock;

/** An error shaped the way ApiError is: a status, or none when nothing came back. */
const failure = (status?: number, extra: Record<string, unknown> = {}) =>
  Object.assign(new Error("failed"), { status, ...extra });

const save = (over: Partial<Parameters<typeof saveOffline>[0]> = {}) =>
  saveOffline({
    type: "mortality", label: "Mortality", method: "POST",
    path: "/broiler/daily-entries/", body: { fields: { mortality: 3 } }, ...over,
  });

beforeEach(async () => {
  jest.clearAllMocks();
  await resetDatabase();
  onlineManager.setOnline(true);
  setQueueUser("7");
  post.mockResolvedValue({ data: { data: { id: 42 } } });
});

describe("saving", () => {
  it("sends straight out when there is a signal", async () => {
    const result = await save();
    expect(result).toEqual({ queued: false, data: { id: 42 } });
    expect(await listEntries()).toHaveLength(0);
  });

  it("keeps it when there is none", async () => {
    onlineManager.setOnline(false);
    const result = await save();
    expect(result.queued).toBe(true);
    expect(post).not.toHaveBeenCalled();
    expect(await listEntries()).toHaveLength(1);
  });

  it("keeps it when the signal dies mid-request", async () => {
    // The phone still believed it was online; the request is what found out.
    post.mockRejectedValueOnce(failure());
    expect((await save()).queued).toBe(true);
  });

  it("throws a rejected payload rather than filing it for later", async () => {
    // The user is still looking at the form. Filing an invalid entry would tell
    // them it worked and surface the failure hours afterwards, out of context.
    post.mockRejectedValueOnce(failure(400));
    await expect(save()).rejects.toBeTruthy();
    expect(await listEntries()).toHaveLength(0);
  });

  it("records when it was filled, not when it is sent", async () => {
    // A round walked at 09:12 and synced at 11:47 is two different facts, and
    // only one of them is about where somebody was.
    onlineManager.setOnline(false);
    await save();
    const [entry] = await listEntries();
    expect(entry.device_created_at).toBeTruthy();
    expect(entry.last_sync_at).toBeNull();
  });

  it("gives every entry a number a person can quote", async () => {
    onlineManager.setOnline(false);
    await save();
    await save();
    const numbers = (await listEntries()).map((e) => e.offline_no);
    expect(numbers[0]).toMatch(/^OFF-\d{8}-\d{6}$/);
    expect(new Set(numbers).size).toBe(2);
  });

  it("keeps the offline number counting across a restart", async () => {
    // Handing out 000001 again after a crash would defeat the point of having
    // a number a supervisor can read out.
    const first = await nextOfflineNumber();
    const second = await nextOfflineNumber();
    expect(Number(second.slice(-6))).toBe(Number(first.slice(-6)) + 1);
  });

  it("copies a photo somewhere the camera cache cannot reclaim", async () => {
    onlineManager.setOnline(false);
    await save({ body: { fields: {}, files: [{ field: "image", uri: "file:///cache/a.jpg" }] } });
    const [entry] = await listEntries();
    expect(entry.files[0].uri).toBe("kept://a.jpg");
  });
});

describe("order", () => {
  it("sends the entries that move stock before the ones that do not", async () => {
    onlineManager.setOnline(false);
    await save({ type: "note", label: "Note" });
    await save({ type: "mortality", label: "Mortality" });
    const order = (await sendableEntries()).map((e) => e.transaction_type);
    expect(order).toEqual(["mortality", "note"]);
  });

  it("holds a child back until its parent has landed", async () => {
    // The server would reject a child pointing at an id that does not exist,
    // and that rejection reads as a bad payload rather than bad sequencing.
    onlineManager.setOnline(false);
    const parent = await save({ type: "chicks_placement", label: "Chicks Placement" });
    if (!parent.queued) throw new Error("expected it to queue");
    await save({ type: "note", label: "Note", dependsOn: parent.localId });
    const sendable = await sendableEntries();
    expect(sendable.map((e) => e.transaction_type)).toEqual(["chicks_placement"]);
  });
});

describe("syncing", () => {
  const queueTwo = async () => {
    onlineManager.setOnline(false);
    await save({ type: "mortality", label: "Mortality" });
    await save({ type: "daily_weight", label: "Daily Weight" });
    onlineManager.setOnline(true);
  };

  it("sends what was waiting and marks it synced", async () => {
    await queueTwo();
    const outcome = await runSync();
    expect(outcome.sent).toBe(2);
    expect((await listEntries()).every((e) => e.sync_status === "synced")).toBe(true);
  });

  it("keeps the entry's own key on every attempt", async () => {
    // The same key each time is what stops a request that landed but lost its
    // answer being performed twice.
    onlineManager.setOnline(false);
    const queued = await save();
    onlineManager.setOnline(true);
    await runSync();
    if (!queued.queued) throw new Error("expected it to queue");
    const [entryCall] = post.mock.calls.filter((c) => c[0] !== "/sync/heartbeat");
    expect(entryCall[2].headers["Idempotency-Key"]).toBe(queued.localId);
  });

  it("tells the ERP when the entry was actually filled", async () => {
    onlineManager.setOnline(false);
    await save();
    onlineManager.setOnline(true);
    await runSync();
    const [entryCall] = post.mock.calls.filter((c) => c[0] !== "/sync/heartbeat");
    expect(entryCall[2].headers["X-Offline-Created-At"]).toBeTruthy();
  });

  it("stops at a dead link instead of running the whole queue into it", async () => {
    await queueTwo();
    post.mockRejectedValue(failure());
    const outcome = await runSync();
    expect(outcome.sent).toBe(0);
    // The run also posts a heartbeat; counting every call would make this
    // pass or fail on unrelated traffic.
    expect(post.mock.calls.filter((c) => c[0] !== "/sync/heartbeat")).toHaveLength(1);
  });

  it("waits before trying a failed entry again", async () => {
    // A handset retrying every second on a dead connection flattens its own
    // battery, and a hundred of them flatten the server.
    await queueTwo();
    post.mockRejectedValue(failure());
    await runSync();

    // Only the entry that was actually tried carries a wait. The run stopped
    // before reaching the second, and penalising an entry nobody attempted
    // would delay it for no reason.
    const [tried] = await listEntries();
    expect(tried.next_attempt_at).toBeTruthy();

    const now = (await sendableEntries()).map((e) => e.local_id);
    expect(now).not.toContain(tried.local_id);
    const later = (await sendableEntries(new Date(Date.now() + 3_600_000)))
      .map((e) => e.local_id);
    expect(later).toContain(tried.local_id);
  });

  it("steps over a refused entry and keeps it", async () => {
    // One bad payload must not hold up a whole round, and a refused entry the
    // user never hears about is a lost record.
    await queueTwo();
    post.mockRejectedValueOnce(failure(400));
    const outcome = await runSync();
    expect(outcome).toMatchObject({ sent: 1, failed: 1 });
    const failed = (await listEntries()).filter((e) => e.sync_status === "failed");
    expect(failed).toHaveLength(1);
  });

  it("puts the parent's real id into the entry that followed it", async () => {
    onlineManager.setOnline(false);
    const parent = await save({ type: "chicks_placement", label: "Chicks Placement",
                                producesId: true });
    if (!parent.queued) throw new Error("expected it to queue");
    await save({ type: "note", label: "Note", dependsOn: parent.localId,
                 body: { fields: { entry: parent.ref } } });
    onlineManager.setOnline(true);
    await runSync();
    const entryCalls = post.mock.calls.filter((c) => c[0] !== "/sync/heartbeat");
    expect(entryCalls[1][1]).toEqual({ entry: "42" });
  });

  it("does not overwrite the ERP when the two disagree", async () => {
    // A supervisor's ten birds and the office's seven are both somebody's
    // count of the same shed. Picking one without asking loses a real number.
    await queueTwo();
    post.mockRejectedValueOnce(failure(409, {
      code: "sync_conflict",
      conflict: { message: "Already recorded", fields: [] },
    }));
    const outcome = await runSync();
    expect(outcome.conflicts).toBe(1);
    const conflicted = (await listEntries()).filter((e) => e.sync_status === "conflict");
    expect(conflicted).toHaveLength(1);
  });

  it("tells the ERP what this phone is still holding", async () => {
    // The queue is on the handset, so the administrator's monitor has nothing
    // to show unless the device says.
    await queueTwo();
    await runSync();
    const [beat] = post.mock.calls.filter((c) => c[0] === "/sync/heartbeat");
    expect(beat[1]).toMatchObject({ pending: 0, failed: 0, synced: 2 });
    expect(beat[1].device_id).toBeTruthy();
  });

  it("leaves another user's round alone", async () => {
    onlineManager.setOnline(false);
    await save();
    setQueueUser("9");
    onlineManager.setOnline(true);
    expect((await runSync()).sent).toBe(0);
    expect((await summarise(true, false)).pending).toBe(0);

    setQueueUser("7");
    expect((await summarise(true, false)).pending).toBe(1);
  });
});

describe("what the user can do about it", () => {
  it("puts a given-up entry back in the queue", async () => {
    onlineManager.setOnline(false);
    const queued = await save();
    if (!queued.queued) throw new Error("expected it to queue");
    onlineManager.setOnline(true);
    post.mockRejectedValueOnce(failure(400));
    await runSync();
    await retryEntry(queued.localId);
    const [entry] = await listEntries();
    expect(entry.sync_status).toBe("pending");
    expect(entry.sync_attempts).toBe(0);
  });

  it("keeps the record when the ERP's version is chosen", async () => {
    // The decision is auditable; the row does not simply vanish.
    onlineManager.setOnline(false);
    const queued = await save();
    if (!queued.queued) throw new Error("expected it to queue");
    await resolveConflict(queued.localId, "server");
    const [entry] = await listEntries();
    expect(entry.sync_status).toBe("synced");
    expect(entry.sync_error).toMatch(/ERP/);
  });

  it("only ever destroys an entry when asked to", async () => {
    onlineManager.setOnline(false);
    const queued = await save();
    if (!queued.queued) throw new Error("expected it to queue");
    await discardEntry(queued.localId);
    expect(await listEntries()).toHaveLength(0);
  });
});

describe("what the user is told", () => {
  it("never quotes the transport at them", () => {
    // "Socket exception" describes the plumbing to someone who only wants to
    // know whether their round is safe.
    for (const status of [undefined, 500, 503, 401, 403]) {
      const message = humanError({ status });
      expect(message).not.toMatch(/socket|HTTP|\d{3}|exception/i);
      expect(message.length).toBeGreaterThan(10);
    }
  });
});
