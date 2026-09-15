import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet, ScrollRestoration } from "react-router-dom";

import { api } from "../api/client";
import { t } from "../i18n";
import { fmtDate } from "../lib/format";

const NAV = [
  { to: "/", label: t.nav.overview, end: true },
  { to: "/alerts", label: t.nav.alerts, end: false },
  { to: "/models", label: t.nav.models, end: false },
];

export function Layout() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    retry: false,
    staleTime: 60_000,
  });
  const asOf = health.data?.marts_as_of_date;

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:p-2"
      >
        {t.app.skipToContent}
      </a>
      <header className="border-b border-line bg-white">
        <div className="mx-auto flex max-w-[1440px] items-center justify-between gap-6 px-6 py-3">
          <NavLink to="/" className="flex flex-col leading-tight">
            <span className="text-lg font-semibold text-accent-800">
              {t.app.title}
            </span>
            <span className="text-sm text-muted">{t.app.subtitle}</span>
          </NavLink>
          <nav aria-label={t.nav.main}>
            <ul className="flex items-center gap-1">
              {NAV.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) =>
                      `block rounded-md px-3 py-2 font-medium ${
                        isActive
                          ? "bg-accent-50 text-accent-800 underline decoration-2 underline-offset-8"
                          : "text-ink hover:bg-canvas"
                      }`
                    }
                  >
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
          <p className="text-sm text-muted tabular-nums">
            {asOf ? t.common.asOf(fmtDate(asOf)) : " "}
          </p>
        </div>
      </header>
      <main
        id="main"
        className="mx-auto w-full max-w-[1440px] flex-1 space-y-8 px-6 py-6"
      >
        <Outlet />
      </main>
      <footer className="border-t border-line bg-white">
        <p className="mx-auto max-w-[1440px] px-6 py-3 text-sm text-muted">
          {t.app.footer}
        </p>
      </footer>
      <ScrollRestoration />
    </div>
  );
}
