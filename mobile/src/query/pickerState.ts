/**
 * Which of the three silences a picker is in.
 *
 * A drop list with nothing in it can mean three different things, and telling
 * somebody the wrong one sends them after the wrong problem:
 *
 *   loading      the answer is on its way
 *   unavailable  there is no answer to be had — offline with nothing cached
 *   empty        the master really has no rows
 *
 * React Query has no single flag for the middle one. Offline it *pauses* a
 * query rather than failing it: it is waiting for a network it has not got, so
 * the query is neither loading nor errored, and anything that checks only
 * those two reads a paused query as an empty one. That is how Daily Entry,
 * Bird Sale and Receipt came to show blank drop lists offline with no word of
 * explanation.
 *
 * Kept apart from the hook so the rule can be tested without a QueryClient,
 * a network, or a component tree.
 */
export type PickerState = "loading" | "unavailable" | "ready";

export interface QueryFacts {
  /** Whether the caller asked for anything at all. */
  enabled: boolean;
  /** Is there a cached answer — from this session or from disk? */
  hasData: boolean;
  isLoading: boolean;
  isError: boolean;
  /** React Query's "waiting for a network" status. */
  isPaused: boolean;
}

export function pickerState(q: QueryFacts): PickerState {
  if (!q.enabled) return "ready";
  if (q.hasData) return "ready";
  if (q.isLoading) return "loading";
  // Nothing cached, not fetching: either the network is absent or the request
  // was refused. Both mean the list could not be had, which is not the same
  // as the list being empty.
  if (q.isPaused || q.isError) return "unavailable";
  return "ready";
}
