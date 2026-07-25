import { useQuery } from "@tanstack/react-query";

import { listResource } from "@/api/resources";
import { Row } from "@/api/types";
import { pick } from "@/utils/format";

export interface Option {
  value: string;
  label: string;
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
