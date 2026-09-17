/** Compile-time proof that the generated operation response is usable as the current runtime-validated view type. */
import type { OverviewGetResponse } from "./generated";
import type { Overview } from "./types";

type Assert<T extends true> = T;
type MutuallyAssignable<Left, Right> = Left extends Right
  ? Right extends Left
    ? true
    : false
  : false;

export type GeneratedOverviewContractProof = Assert<
  MutuallyAssignable<OverviewGetResponse, Overview>
>;
