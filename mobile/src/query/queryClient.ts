import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/api/types";

/**
 * Shared React Query client. Auth failures are already handled by the axios
 * refresh interceptor, so there's no point retrying a 401/403 here; other
 * errors get a couple of retries for flaky mobile networks.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry: (failureCount, error) => {
        if (error instanceof ApiError && [400, 401, 403, 404].includes(error.status ?? 0)) {
          return false;
        }
        return failureCount < 2;
      },
      refetchOnWindowFocus: false,
    },
  },
});
