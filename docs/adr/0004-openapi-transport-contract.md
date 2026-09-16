# ADR 0004: OpenAPI transport contract

Status: Accepted
Date: 2026-09-15
Owners: BizAI

## Context

FastAPI routes and Pydantic request/response models define the implemented HTTP behavior. FastAPI
publishes OpenAPI, while `docs/api.md` provides curated semantics and examples. The React frontend
currently maintains handwritten request functions, runtime response schemas and TypeScript types
that mirror the backend. Repository audit compares documented endpoint paths with routes, but there
is no generated client, stable explicit operation-ID policy or compatibility gate.

Manual transport duplication gives useful runtime validation today but increases the chance that
backend and frontend contracts drift.

## Decision

- FastAPI OpenAPI becomes the canonical HTTP transport contract.
- Stable, unique `operationId` values will be established before SDK generation.
- A TypeScript transport client will later be generated reproducibly from OpenAPI.
- Frontend view models remain independent from generated transport DTOs.
- API compatibility will later become a CI fitness function.

This ADR does not change operation IDs or generate code now.

## Dependency rules

- Pydantic request/response models and route metadata own wire shapes.
- Generated TypeScript transport code belongs in `shared/api` or an equivalent low-level location
  and is not edited by hand.
- Pages/features consume frontend query/view adapters, not generator internals directly where
  transformation is required.
- UI presentation types may combine or reshape transport DTOs; generated DTOs must not absorb UI
  state or formatting concerns.
- Once generation is adopted, duplicate handwritten HTTP transport contracts are removed
  incrementally.

## Alternatives considered

- **Continue manually mirroring all transport types.** Rejected as the target because it duplicates
  a machine-readable contract and relies on synchronized edits.
- **Treat `docs/api.md` as the generator source.** Rejected: prose owns semantics and examples, not
  executable schema.
- **Share backend Python models directly with TypeScript.** Rejected because it couples languages and
  does not provide a browser transport implementation.
- **Adopt GraphQL or another API style.** Rejected because the current REST/OpenAPI surface meets the
  product need and migration would not solve a measured problem.

## Consequences

### Positive

- Backend and frontend transport changes derive from one executable source.
- Contract drift and breaking changes can be detected automatically.
- UI models remain free to reflect screen needs rather than wire structure.

### Negative

- Stable operation naming and generator/version ownership become required maintenance.
- Generated code adds review noise unless generation is reproducible and diffs are controlled.
- Runtime validation behavior must be intentionally retained or replaced; TypeScript generation
  alone does not validate untrusted JSON at runtime.

## Migration

Inventory and assign stable unique operation IDs without changing paths or behavior. Select and pin
a generator, generate into the agreed low-level frontend location, and adapt one query flow. Keep
current runtime validation where needed. Once output is reproducible, add regeneration and
compatibility checks to CI, then retire duplicated transport definitions slice by slice.

## Verification

- OpenAPI contains a stable unique operation ID for every supported endpoint.
- Client generation is deterministic and a clean checkout reproduces committed output.
- CI detects unreviewed generated-client diffs and backward-incompatible API changes.
- Frontend dependency checks keep pages/features from depending on inappropriate generator
  internals and keep view models separate.

## Revisit when

Revisit the generator or transport approach when it cannot express required authentication,
streaming, file transfer, runtime validation or compatibility needs, or when a measured client
ecosystem requirement calls for additional SDK languages. Do not revisit merely to adopt a newer
API style.
