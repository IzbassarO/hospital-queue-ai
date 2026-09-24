/** Presentation primitives of the guided journey: scene frame, stat tiles, non-claims, technical disclosure. */
import type { ReactNode } from "react";
import { t } from "../i18n";
import { fmtNumber } from "../lib/format";
import { severityLabel } from "./language";
import { useCountUp, useReducedMotion } from "./motion";

export function Scene({
  kicker,
  title,
  lead,
  children,
  aside,
}: {
  kicker: string;
  title: string;
  lead?: ReactNode;
  children: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <section className="scene" aria-labelledby="scene-title">
      <header className="scene-head">
        <div className="min-w-0">
          <p className="scene-kicker">{kicker}</p>
          <h1 id="scene-title" className="scene-title">
            {title}
          </h1>
          {lead ? <div className="scene-lead">{lead}</div> : null}
        </div>
        {aside ? <div className="scene-aside">{aside}</div> : null}
      </header>
      {children}
    </section>
  );
}

export function Panel({
  title,
  eyebrow,
  children,
  className = "",
  tone = "dark",
  id,
}: {
  title?: string;
  eyebrow?: string;
  children: ReactNode;
  className?: string;
  tone?: "dark" | "paper" | "glass";
  id?: string;
}) {
  return (
    <section
      className={`panel panel-${tone} ${className}`}
      aria-label={title}
      id={id}
    >
      {eyebrow || title ? (
        <header className="panel-head">
          {eyebrow ? <p className="panel-eyebrow">{eyebrow}</p> : null}
          {title ? <h2 className="panel-title">{title}</h2> : null}
        </header>
      ) : null}
      {children}
    </section>
  );
}

export function SeverityPill({
  value,
  size = "md",
}: {
  value: string;
  size?: "md" | "lg";
}) {
  return (
    <span
      className={`sev sev-${value.toLowerCase()} sev-${size}`}
      aria-label={`${t.tower.severity}: ${severityLabel(value)}`}
    >
      {severityLabel(value)}
    </span>
  );
}

/** A number that counts up once when it appears; rendered instantly under reduced motion. */
export function Stat({
  label,
  value,
  decimals = 1,
  unit,
  hint,
  emphasis = false,
  text,
}: {
  label: string;
  value?: number | null;
  decimals?: number;
  unit?: string;
  hint?: string;
  emphasis?: boolean;
  text?: string;
}) {
  const reduced = useReducedMotion();
  const shown = useCountUp(value ?? null, reduced);
  return (
    <div className={`stat ${emphasis ? "stat-emphasis" : ""}`}>
      <dt className="stat-label">{label}</dt>
      <dd
        className={`stat-value ${text !== undefined ? "is-text" : ""}`}
        data-final={value ?? text ?? ""}
      >
        {text ??
          (shown === null ? t.common.noData : fmtNumber(shown, decimals))}
        {unit && text === undefined && shown !== null ? (
          <span className="stat-unit"> {unit}</span>
        ) : null}
      </dd>
      {hint ? <dd className="stat-hint">{hint}</dd> : null}
    </div>
  );
}

export function StatGrid({ children }: { children: ReactNode }) {
  return <dl className="stat-grid">{children}</dl>;
}

/** Explicit boundaries. The container is marked so tests can exempt negated vocabulary from the forbidden list. */
export function NonClaims({
  title,
  items,
}: {
  title: string;
  items: string[];
}) {
  return (
    <section className="nonclaims" data-nonclaim="true" aria-label={title}>
      <p className="nonclaims-text">
        <strong className="nonclaims-title">{title}.</strong>{" "}
        {items.map((item, i) => (
          <span key={item} className="nonclaims-item">
            <span>{item}</span>
            {/[.!?…]$/.test(item) ? "" : "."}
            {i < items.length - 1 ? " " : ""}
          </span>
        ))}
      </p>
    </section>
  );
}

export function Bullets({
  items,
  tone = "default",
}: {
  items: string[];
  tone?: "default" | "check" | "numbered";
}) {
  const Tag = tone === "numbered" ? "ol" : "ul";
  return (
    <Tag className={`bullets bullets-${tone}`}>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </Tag>
  );
}

/** Ledger of facts: label on the left, value on the right, hairlines between rows. No tiles, no count-ups. */
export function Facts({
  rows,
  className = "",
}: {
  rows: { label: string; value: ReactNode; hint?: ReactNode }[];
  className?: string;
}) {
  return (
    <dl className={`facts ${className}`}>
      {rows.map((row, i) => (
        <div key={`${row.label}-${i}`} className="fact">
          <dt>{row.label}</dt>
          <dd>
            <span className="fact-value">{row.value}</span>
            {row.hint ? <span className="fact-hint">{row.hint}</span> : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** A number spoken inline: "207 сигналов в регионе · 60 высокого уровня". */
export function FactLine({
  parts,
}: {
  parts: { value: string; label: string }[];
}) {
  return (
    <p className="fact-line">
      {parts.map((part, i) => (
        <span key={`${part.label}-${i}`}>
          {i > 0 ? <span className="fact-line-sep"> · </span> : null}
          <strong>{part.value}</strong> {part.label}
        </span>
      ))}
    </p>
  );
}

/** Tertiary layer: raw identifiers, hashes and machine tokens, never in the primary surface. */
export function Technical({
  title,
  items,
  lines,
}: {
  title: string;
  items?: { label: string; value: string }[];
  lines?: string[];
}) {
  return (
    <details className="technical" data-technical="true">
      <summary>{title}</summary>
      {items?.length ? (
        <dl className="technical-list">
          {items.map((item, i) => (
            <div key={`${item.label}-${i}`}>
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {lines?.length ? (
        <ul className="technical-lines">
          {lines.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      ) : null}
    </details>
  );
}

export function Arrow() {
  return (
    <span className="arrow" aria-hidden="true">
      →
    </span>
  );
}

export function Legend({
  items,
}: {
  items: { swatch: string; label: string }[];
}) {
  return (
    <ul className="legend">
      {items.map((item) => (
        <li key={item.label}>
          <span className={`swatch ${item.swatch}`} aria-hidden="true" />
          {item.label}
        </li>
      ))}
    </ul>
  );
}
