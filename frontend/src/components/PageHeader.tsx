import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { t } from "../i18n";
import { IconChevronRight } from "./icons";

export type Crumb = { label: string; to?: string };

export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label={t.nav.breadcrumbs}>
      <ol className="flex flex-wrap items-center gap-1 text-sm text-muted">
        {items.map((item, i) => (
          <li key={`${item.label}-${i}`} className="flex items-center gap-1">
            {i > 0 ? <IconChevronRight size={14} /> : null}
            {item.to ? (
              <Link to={item.to} className="link">
                {item.label}
              </Link>
            ) : (
              <span aria-current="page">{item.label}</span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function PageHeader({
  title,
  crumbs,
  children,
  aside,
}: {
  title: ReactNode;
  crumbs?: Crumb[];
  children?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <header className="space-y-2">
      {crumbs ? <Breadcrumbs items={crumbs} /> : null}
      <div className="flex items-start justify-between gap-6">
        <div className="min-w-0 space-y-1">
          <h1 className="text-2xl font-semibold leading-tight text-ink">
            {title}
          </h1>
          {children}
        </div>
        {aside ? <div className="shrink-0">{aside}</div> : null}
      </div>
    </header>
  );
}

export function Section({
  title,
  caption,
  actions,
  children,
  id,
}: {
  title: string;
  caption?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  id?: string;
}) {
  const headingId = id ? `${id}-title` : undefined;
  return (
    <section className="space-y-3" aria-labelledby={headingId} id={id}>
      <div className="flex items-end justify-between gap-4">
        <div>
          <h2 id={headingId} className="text-xl font-semibold text-ink">
            {title}
          </h2>
          {caption ? <p className="text-sm text-muted">{caption}</p> : null}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}
