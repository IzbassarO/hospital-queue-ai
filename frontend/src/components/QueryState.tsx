import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { ErrorState } from "./ErrorState";

/** Loading skeleton → error state with retry → content. */
export function QueryState<T>({
  query,
  skeleton,
  children,
}: {
  query: UseQueryResult<T, Error>;
  skeleton: ReactNode;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <>{skeleton}</>;
  if (query.isError)
    return (
      <ErrorState error={query.error} onRetry={() => void query.refetch()} />
    );
  return <>{children(query.data)}</>;
}
