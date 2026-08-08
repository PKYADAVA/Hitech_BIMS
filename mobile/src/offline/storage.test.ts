/**
 * A phone that has filled up, and the rule that survives it.
 *
 * A queued round is photographs as much as figures, so storage runs out on
 * exactly the handsets doing the most work. The warning matters — and matters
 * more that it never reads as "your entries are about to be deleted", because
 * they never are: nothing pending is ever dropped to make room.
 */
import { describeStorage } from "./storage";

const MB = 1024 ** 2;
const GB = 1024 ** 3;

describe("describeStorage", () => {
  it("says nothing when there is room", () => {
    const state = describeStorage(4 * GB);
    expect(state.level).toBe("ok");
    expect(state.message).toBeNull();
  });

  it("recommends syncing when space is short", () => {
    const state = describeStorage(120 * MB);
    expect(state.level).toBe("low");
    expect(state.message).toMatch(/running low/i);
  });

  it("is plainer when the next save is at risk", () => {
    const state = describeStorage(20 * MB);
    expect(state.level).toBe("critical");
    // Must never read as "your data is about to be deleted" — it never is.
    expect(state.message).toMatch(/nothing already saved will be lost/i);
  });

  it("stays quiet when it cannot tell", () => {
    // Warning about storage that may be perfectly fine trains people to
    // dismiss the warning that matters.
    const state = describeStorage(null);
    expect(state.level).toBe("unknown");
    expect(state.message).toBeNull();
  });

  it("quotes a figure somebody can act on", () => {
    expect(describeStorage(150 * MB).message).toMatch(/150 MB/);
    expect(describeStorage(null).freeBytes).toBeNull();
  });
});
