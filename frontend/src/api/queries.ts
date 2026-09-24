/** TanStack Query hooks of the legacy mart endpoints still used by the demo (as-of snapshot, cached generously). */
import { useQuery } from "@tanstack/react-query";

import { api } from "./client";

export const queryKeys = {
  overview: ["overview"] as const,
  dictionaries: ["dictionaries"] as const,
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
