/**
 * Canonical JSON `hqai-canonical-json-v1` in the browser (docs/transparency-ledger.md §3). The ledger hashes these
 * bytes, so this file does not use JSON.stringify or JSON.parse: it implements the contract itself, exactly as the
 * Python verifiers do, and is tested against the shared vectors in docs/transparency-ledger-vectors.json.
 *
 * Values: null, booleans, integers within ±(2^53−1), strings, arrays, objects with keys [a-z][a-z0-9_]{0,63}
 * (ASCII, so code-point, UTF-16 and byte order agree). Strings are Unicode scalar values without U+0000; `"` and
 * `\` get a backslash, \b \t \n \f \r their short escapes, other code points below U+0020 `\u00xx` (lowercase),
 * everything else is written as itself. No whitespace. Floats are rejected, also when they are integral ("1.0").
 */

export type CanonicalValue =
  | null
  | boolean
  | number
  | string
  | CanonicalValue[]
  | { [key: string]: CanonicalValue };

export class CanonicalError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(`${code}: ${message}`);
    this.name = "CanonicalError";
  }
}

export const MAX_SAFE = Number.MAX_SAFE_INTEGER;
const MAX_DEPTH = 32;
const KEY = /^[a-z][a-z0-9_]{0,63}$/;
const SHORT: Record<string, string> = {
  '"': '\\"',
  "\\": "\\\\",
  "\b": "\\b",
  "\t": "\\t",
  "\n": "\\n",
  "\f": "\\f",
  "\r": "\\r",
};

function checkScalars(value: string): void {
  for (let i = 0; i < value.length; i++) {
    const unit = value.charCodeAt(i);
    if (unit === 0)
      throw new CanonicalError("NUL_IN_STRING", "U+0000 in a string");
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(i + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff))
        throw new CanonicalError("LONE_SURROGATE", "lone high surrogate");
      i++;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) {
      throw new CanonicalError("LONE_SURROGATE", "lone low surrogate");
    }
  }
}

function encodeString(value: string): string {
  checkScalars(value);
  let out = '"';
  for (const char of value) {
    const short = SHORT[char];
    if (short) out += short;
    else if (char < " ")
      out += `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`;
    else out += char;
  }
  return `${out}"`;
}

function encode(value: unknown, depth: number): string {
  if (depth > MAX_DEPTH)
    throw new CanonicalError("TOO_DEEP", "nesting deeper than 32");
  if (value === null) return "null";
  if (value === true) return "true";
  if (value === false) return "false";
  if (typeof value === "number") {
    if (!Number.isInteger(value))
      throw new CanonicalError("FLOAT_NOT_ALLOWED", String(value));
    if (Math.abs(value) > MAX_SAFE)
      throw new CanonicalError("INTEGER_OUT_OF_RANGE", String(value));
    return Object.is(value, -0) ? "0" : String(value);
  }
  if (typeof value === "string") return encodeString(value);
  if (Array.isArray(value))
    return `[${value.map((item) => encode(item, depth + 1)).join(",")}]`;
  if (typeof value === "object") {
    const keys = Object.keys(value as object);
    for (const key of keys)
      if (!KEY.test(key)) throw new CanonicalError("INVALID_KEY", key);
    keys.sort();
    const record = value as Record<string, unknown>;
    return `{${keys.map((k) => `${encodeString(k)}:${encode(record[k], depth + 1)}`).join(",")}}`;
  }
  throw new CanonicalError("UNSUPPORTED_TYPE", typeof value);
}

/** Canonical text of a value; throws CanonicalError outside the contract. */
export function canonicalText(value: unknown): string {
  return encode(value, 0);
}

export function canonicalBytes(value: unknown): Uint8Array {
  return new TextEncoder().encode(canonicalText(value));
}

/**
 * Strict JSON parser for ledger lines: rejects floats (any number with a fraction or exponent), integers outside
 * the safe range, duplicate keys and everything JSON.parse would silently accept differently. The result is also
 * run through canonicalText, so keys and strings satisfy the contract.
 */
export function parseStrict(text: string): CanonicalValue {
  let i = 0;
  const fail = (code: string, message: string): never => {
    throw new CanonicalError(code, `${message} at ${i}`);
  };
  const ws = () => {
    while (i < text.length && " \t\n\r".includes(text[i])) i++;
  };
  const parseString = (): string => {
    i++; // opening quote
    let out = "";
    for (;;) {
      if (i >= text.length) fail("MALFORMED_JSON", "unterminated string");
      const ch = text[i];
      if (ch === '"') {
        i++;
        return out;
      }
      if (ch === "\\") {
        const esc = text[i + 1];
        const simple: Record<string, string> = {
          '"': '"',
          "\\": "\\",
          "/": "/",
          b: "\b",
          f: "\f",
          n: "\n",
          r: "\r",
          t: "\t",
        };
        if (esc in simple) {
          out += simple[esc];
          i += 2;
        } else if (esc === "u") {
          const hex = text.slice(i + 2, i + 6);
          if (!/^[0-9a-fA-F]{4}$/.test(hex))
            fail("MALFORMED_JSON", "bad \\u escape");
          out += String.fromCharCode(parseInt(hex, 16));
          i += 6;
        } else fail("MALFORMED_JSON", "bad escape");
      } else {
        if (ch < " ") fail("MALFORMED_JSON", "control character in string");
        out += ch;
        i++;
      }
    }
  };
  const parseValue = (depth: number): CanonicalValue => {
    ws();
    const ch = text[i];
    if (ch === "{") {
      if (depth > MAX_DEPTH) fail("TOO_DEEP", "nesting deeper than 32");
      i++;
      // no prototype: a key such as "__proto__" stays an ordinary (and then rejected) key
      const obj = Object.create(null) as Record<string, CanonicalValue>;
      ws();
      if (text[i] === "}") {
        i++;
        return obj;
      }
      for (;;) {
        ws();
        if (text[i] !== '"') fail("MALFORMED_JSON", "expected a key");
        const key = parseString();
        if (Object.prototype.hasOwnProperty.call(obj, key))
          fail("DUPLICATE_KEY", `duplicate key ${key}`);
        ws();
        if (text[i] !== ":") fail("MALFORMED_JSON", "expected ':'");
        i++;
        obj[key] = parseValue(depth + 1);
        ws();
        if (text[i] === ",") {
          i++;
          continue;
        }
        if (text[i] === "}") {
          i++;
          return obj;
        }
        fail("MALFORMED_JSON", "expected ',' or '}'");
      }
    }
    if (ch === "[") {
      if (depth > MAX_DEPTH) fail("TOO_DEEP", "nesting deeper than 32");
      i++;
      const arr: CanonicalValue[] = [];
      ws();
      if (text[i] === "]") {
        i++;
        return arr;
      }
      for (;;) {
        arr.push(parseValue(depth + 1));
        ws();
        if (text[i] === ",") {
          i++;
          continue;
        }
        if (text[i] === "]") {
          i++;
          return arr;
        }
        fail("MALFORMED_JSON", "expected ',' or ']'");
      }
    }
    if (ch === '"') return parseString();
    if (text.startsWith("true", i)) {
      i += 4;
      return true;
    }
    if (text.startsWith("false", i)) {
      i += 5;
      return false;
    }
    if (text.startsWith("null", i)) {
      i += 4;
      return null;
    }
    const number = /^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?/.exec(
      text.slice(i),
    );
    if (number) {
      if (number[2] !== undefined || number[3] !== undefined)
        fail("FLOAT_NOT_ALLOWED", `floating-point number ${number[0]}`);
      i += number[0].length;
      const big = BigInt(number[0]);
      if (big > BigInt(MAX_SAFE) || big < -BigInt(MAX_SAFE))
        fail("INTEGER_OUT_OF_RANGE", number[0]);
      return Number(number[0]);
    }
    return fail("MALFORMED_JSON", "unexpected token");
  };
  const value = parseValue(0);
  ws();
  if (i !== text.length) fail("MALFORMED_JSON", "trailing characters");
  canonicalText(value);
  return value;
}
