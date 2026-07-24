import { useInfiniteQuery } from "@tanstack/react-query";

import { listResource, Page } from "@/api/resources";
import { Row } from "@/api/types";

/**
 * One hook for every list screen — powers infinite scroll + pull-to-refresh
 * against any `/api/v1/` resource, page- or cursor-paginated alike. It follows
 * the envelope's `pagination.next` URL, so the screen never deals with page
 * numbers or cursors itself.
 *
 * Usage:
 *   const q = useResourceList("/broiler/daily-entries/");
 *   <FlatList data={q.items} onEndReached={q.loadMore}
 *             refreshing={q.isRefreshing} onRefresh={q.refresh} />
 */
export function useResourceList<T extends Row = Row>(
  path: string,
  params?: Record<string, string | number | undefined>
) {
  const query = useInfiniteQuery({
    queryKey: ["list", path, params],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      listResource<T>(pageParam ?? path, pageParam ? undefined : params),
    getNextPageParam: (lastPage: Page<T>) => lastPage.pagination?.next ?? undefined,
  });

  const items: T[] = query.data?.pages.flatMap((p) => p.items) ?? [];

  return {
    items,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isRefreshing: query.isRefetching && !query.isFetchingNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    hasNextPage: query.hasNextPage,
    refresh: () => query.refetch(),
    loadMore: () => {
      if (query.hasNextPage && !query.isFetchingNextPage) query.fetchNextPage();
    },
  };
}
