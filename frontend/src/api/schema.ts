/**
 * Minimal runtime schemas for API responses. Every response is checked against its schema before the UI
 * sees it, so a backend change surfaces as one clear error ("overview.national.queue_now: expected number")
 * instead of a blank cell. TypeScript types are inferred from the schemas (see ./types.ts).
 */

export class ShapeError extends Error {
  constructor(
    readonly path: string,
    readonly expected: string,
    readonly received: unknown,
  ) {
    super(`${path}: expected ${expected}, got ${describe(received)}`);
    this.name = "ShapeError";
  }
}

function describe(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}

export interface Schema<T> {
  parse(value: unknown, path?: string): T;
}

export type Infer<S> = S extends Schema<infer T> ? T : never;

function primitive<T>(
  expected: string,
  check: (v: unknown) => boolean,
): Schema<T> {
  return {
    parse(value, path = "$") {
      if (!check(value)) throw new ShapeError(path, expected, value);
      return value as T;
    },
  };
}

export const str = primitive<string>("string", (v) => typeof v === "string");
export const num = primitive<number>(
  "number",
  (v) => typeof v === "number" && Number.isFinite(v),
);
export const bool = primitive<boolean>(
  "boolean",
  (v) => typeof v === "boolean",
);
/** ISO date "2025-03-31" */
export const isoDate = primitive<string>(
  "ISO date",
  (v) => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v),
);
/** ISO date-time "2026-09-15T13:11:55.887730Z" */
export const isoDateTime = primitive<string>(
  "ISO date-time",
  (v) => typeof v === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(v),
);
/** Any JSON value, not inspected (free-form objects such as model metrics) */
export const unknownValue = primitive<unknown>("any", () => true);

export function literal<const T extends readonly string[]>(
  ...values: T
): Schema<T[number]> {
  return primitive<T[number]>(
    values.join(" | "),
    (v) => typeof v === "string" && values.includes(v),
  );
}

export function nullable<T>(inner: Schema<T>): Schema<T | null> {
  return {
    parse(value, path = "$") {
      return value === null ? null : inner.parse(value, path);
    },
  };
}

export function array<T>(inner: Schema<T>): Schema<T[]> {
  return {
    parse(value, path = "$") {
      if (!Array.isArray(value)) throw new ShapeError(path, "array", value);
      return value.map((item, i) => inner.parse(item, `${path}[${i}]`));
    },
  };
}

export function record<T>(inner: Schema<T>): Schema<Record<string, T>> {
  return {
    parse(value, path = "$") {
      if (typeof value !== "object" || value === null || Array.isArray(value)) {
        throw new ShapeError(path, "object", value);
      }
      return Object.fromEntries(
        Object.entries(value).map(([k, v]) => [
          k,
          inner.parse(v, `${path}.${k}`),
        ]),
      );
    },
  };
}

type Shape = Record<string, Schema<unknown>>;
type FromShape<S extends Shape> = { [K in keyof S]: Infer<S[K]> };

/** An object with at least these keys; unknown extra keys are kept (the API may add fields). */
export function object<S extends Shape>(
  shape: S,
): Schema<FromShape<S>> & { shape: S } {
  return {
    shape,
    parse(value, path = "$") {
      if (typeof value !== "object" || value === null || Array.isArray(value)) {
        throw new ShapeError(path, "object", value);
      }
      const source = value as Record<string, unknown>;
      const out: Record<string, unknown> = { ...source };
      for (const [key, schema] of Object.entries(shape)) {
        if (!(key in source))
          throw new ShapeError(`${path}.${key}`, "a field", undefined);
        out[key] = schema.parse(source[key], `${path}.${key}`);
      }
      return out as FromShape<S>;
    },
  };
}

/** Same object schema with more keys (Pydantic subclassing). */
export function extend<S extends Shape, E extends Shape>(
  base: { shape: S },
  extra: E,
): Schema<FromShape<S & E>> & { shape: S & E } {
  return object({ ...base.shape, ...extra });
}
