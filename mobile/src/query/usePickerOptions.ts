import { useQuery } from "@tanstack/react-query";

import { listResource } from "@/api/resources";
import { Row } from "@/api/types";
import { pickerState } from "@/query/pickerState";
import { pick } from "@/utils/format";

export interface Option {
  value: string;
  label: string;
  /**
   * Listed but not selectable — a choice that exists and is unavailable.
   *
   * A shed already holding an open batch, for instance: hiding it would leave
   * someone hunting for a unit they know is there, so it is shown greyed with
   * the reason in its label. Only caller-supplied options set this; a fetched
   * master has nothing to say about availability.
   */
  disabled?: boolean;
}

export interface PickerOptions {
  options: Option[];
  loading: boolean;
  error: boolean;
  /**
   * There is nothing to show, and the master is not empty — the list simply
   * could not be had. A picker that cannot tell this from "no options" tells
   * somebody standing in a shed that their farm does not exist.
   */
  unavailable: boolean;
}

/**
 * Loads a master/reference endpoint into `{value,label}` options for FK pickers.
 * Masters are small, so one large page is fetched and filtered client-side.
 *
 * Offline, the answer comes from the read-cache the persister keeps on disk
 * (see App.tsx), so a list opened once on signal is there afterwards without
 * one. When there is no cached copy at all, React Query leaves the query
 * *paused* rather than failed — it is waiting for a network it has not got —
 * and a paused query is neither loading nor errored. Read as either, it looks
 * exactly like a master with nothing in it, which is how Daily Entry, Bird
 * Sale and Receipt came to show empty drop lists offline with no explanation.
 * `unavailable` is that third state, said out loud.
 */
export function usePickerOptions(path?: string, labelKeys: string[] = []): PickerOptions {
  const q = useQuery({
    queryKey: ["picker", path],
    enabled: !!path,
    staleTime: 5 * 60 * 1000,
    queryFn: () => listResource<Row>(path!, { page_size: 200 }),
  });

  const options: Option[] = (q.data?.items ?? []).map((row) => ({
    value: String(row.id),
    label: pick(row, labelKeys, `#${row.id}`),
  }));

  // Which of the three silences this is — see pickerState, where the rule
  // lives so it can be tested without a network or a component tree.
  const state = pickerState({
    enabled: !!path,
    hasData: q.data !== undefined,
    isLoading: q.isLoading,
    isError: q.isError,
    isPaused: q.fetchStatus === "paused",
  });

  return {
    options,
    loading: state === "loading",
    error: q.isError,
    unavailable: state === "unavailable",
  };
}
