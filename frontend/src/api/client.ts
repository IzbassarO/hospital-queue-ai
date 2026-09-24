/**
 * Typed client for the hospital-queue-ai API (docs/api.md). Same-origin by default: `/api/v1` is proxied to the
 * backend by Vite (`make web-dev`) and by nginx (docker). VITE_API_BASE overrides it at build time.
 */
import type { Schema } from "./schema";
import {
  dictionariesSchema,
  healthSchema,
  hospitalCardSchema,
  overviewSchema,
} from "./types";

export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api/v1";
/** API key compiled in at build time (VITE_API_KEY; docker: DEMO_API_KEY from .env). Empty = no key sent. */
export const API_KEY: string = import.meta.env.VITE_API_KEY ?? "";
export const API_KEY_HEADER = "X-API-Key";

export type ApiErrorKind = "network" | "http" | "shape" | "auth" | "forbidden";

/** Everything the error state needs: what failed, where, and the API's own message. */
export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    readonly url: string,
    message: string,
    readonly status?: number,
    readonly detail?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function absoluteUrl(path: string): string {
  const base =
    typeof window !== "undefined" ? window.location.origin : "http://localhost";
  return new URL(`${API_BASE}${path}`, base).href;
}

type Query = Record<string, string | number | null | undefined>;

export function buildPath(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "")
      params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

export async function request<T>(
  schema: Schema<T>,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const url = absoluteUrl(path);
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: {
        Accept: "application/json",
        ...authHeaders(),
        ...init?.headers,
      },
    });
  } catch (cause) {
    throw new ApiError(
      "network",
      url,
      cause instanceof Error ? cause.message : String(cause),
    );
  }
  let body: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      // nginx answers 502/504 with HTML when the backend is down
      if (!response.ok)
        throw new ApiError(
          "network",
          url,
          `HTTP ${response.status}`,
          response.status,
        );
      throw new ApiError("shape", url, "response is not JSON", response.status);
    }
  }
  if (!response.ok) {
    const detail = extractDetail(body);
    const kind = errorKind(response.status);
    throw new ApiError(
      kind,
      url,
      detail ?? `HTTP ${response.status}`,
      response.status,
      detail,
    );
  }
  try {
    return schema.parse(body, "response");
  } catch (error) {
    throw new ApiError(
      "shape",
      url,
      error instanceof Error ? error.message : String(error),
      response.status,
    );
  }
}

function authHeaders(): Record<string, string> {
  return API_KEY ? { [API_KEY_HEADER]: API_KEY } : {};
}

function errorKind(status: number): ApiErrorKind {
  if (status === 502 || status === 504) return "network"; // nginx: backend down
  if (status === 401) return "auth";
  if (status === 403) return "forbidden";
  return "http";
}

function extractDetail(body: unknown): string | undefined {
  if (typeof body !== "object" || body === null || !("detail" in body))
    return undefined;
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === "string") return detail;
  // 422 from FastAPI: [{loc, msg, type}]
  if (Array.isArray(detail)) {
    return detail
      .map((d) =>
        typeof d === "object" && d !== null && "msg" in d
          ? String((d as { msg: unknown }).msg)
          : "",
      )
      .filter(Boolean)
      .join("; ");
  }
  return undefined;
}

const enc = encodeURIComponent;

export const api = {
  health: () => request(healthSchema, "/health"),
  overview: () => request(overviewSchema, "/overview"),
  dictionaries: () => request(dictionariesSchema, "/dictionaries"),
  hospitalCard: (org: string, profile: string) =>
    request(
      hospitalCardSchema,
      `/hospitals/${enc(org)}/profiles/${enc(profile)}`,
    ),
};
