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
      {eyebrow ? <p className="panel-eyebrow">{eyebrow}</p> : null}
      {title ? <h2 className="panel-title">{title}</h2> : null}
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
      <h3 className="nonclaims-title">{title}</h3>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

export function Bullets({
  items,
  tone = "default",
}: {
  items: string[];
  tone?: "default" | "check";
}) {
  return (
    <ul className={`bullets bullets-${tone}`}>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
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
