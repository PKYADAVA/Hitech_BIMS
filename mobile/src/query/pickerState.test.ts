import { pickerState, QueryFacts } from "./pickerState";

const facts = (over: Partial<QueryFacts> = {}): QueryFacts => ({
  enabled: true, hasData: false, isLoading: false, isError: false, isPaused: false,
  ...over,
});

describe("pickerState", () => {
  it("is unavailable when offline with nothing cached", () => {
    // The reported bug. React Query pauses rather than fails, so this state
    // is neither loading nor errored — and anything checking only those two
    // reads it as an empty master.
    expect(pickerState(facts({ isPaused: true }))).toBe("unavailable");
  });

  it("is unavailable when the request was refused and nothing is cached", () => {
    expect(pickerState(facts({ isError: true }))).toBe("unavailable");
  });

  it("is ready whenever there is a cached answer, network or not", () => {
    // The whole point of the persisted read-cache: a list opened once on
    // signal is there afterwards without one.
    expect(pickerState(facts({ hasData: true, isPaused: true }))).toBe("ready");
    expect(pickerState(facts({ hasData: true, isError: true }))).toBe("ready");
  });

  it("does not call a genuinely empty master unavailable", () => {
    // Data arrived and had no rows in it. Saying "not available offline"
    // here would be its own lie, in the other direction.
    expect(pickerState(facts({ hasData: true }))).toBe("ready");
  });

  it("says loading only while something is actually on its way", () => {
    expect(pickerState(facts({ isLoading: true }))).toBe("loading");
    // Paused is not loading: nothing is in flight and nothing will be until
    // the network is back. Reporting it as loading spins forever.
    expect(pickerState(facts({ isPaused: true }))).not.toBe("loading");
  });

  it("says nothing about a picker that was never asked to fetch", () => {
    // Inline options, or a field still waiting on an earlier one. There is no
    // query, so there is no failure to report.
    expect(pickerState(facts({ enabled: false, isPaused: true }))).toBe("ready");
  });
});
