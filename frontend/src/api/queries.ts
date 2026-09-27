/** TanStack Query hooks of the legacy mart endpoints still used by the demo (as-of snapshot, cached generously). */
import { useQuery } from "@tanstack/react-query";

import { api } from "./client";

/** One page of the load-index mart is enough for the descriptive list; the API caps a page at 500 rows. */
export const LOAD_ALERTS_PAGE = 500;

export const queryKeys = {
  overview: ["overview"] as const,
  dictionaries: ["dictionaries"] as const,
  loadAlerts: (limit: number) => ["load-alerts", limit] as const,
};

export function useOverview() {
  return useQuery({ queryKey: queryKeys.overview, queryFn: api.overview });
}

export function useDictionaries() {
  return useQuery({
    queryKey: queryKeys.dictionaries,
    queryFn: api.dictionaries,
    staleTime: Infinity,
  });
}

/**
 * Rows of the load-index mart, for the descriptive "who waits longest at the as-of date" list. A failure is not
 * fatal for the page that uses it: the list simply says the mart is unavailable.
 */
export function useLoadAlerts(limit: number = LOAD_ALERTS_PAGE) {
  return useQuery({
    queryKey: queryKeys.loadAlerts(limit),
    queryFn: () => api.loadAlerts(limit),
    staleTime: Infinity,
    retry: false,
  });
}
