import { useQuery } from "@tanstack/react-query";

import { listResource } from "@/api/resources";
import { Row } from "@/api/types";
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

/**
 * Loads a master/reference endpoint into `{value,label}` options for FK pickers.
 * Masters are small, so one large page is fetched and filtered client-side.
 */
export function usePickerOptions(path?: string, labelKeys: string[] = []) {
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

  return { options, loading: q.isLoading, error: q.isError };
}
