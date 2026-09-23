import {
  Link,
  NavLink,
  Outlet,
  ScrollRestoration,
  useLocation,
} from "react-router-dom";
import { ApiError } from "../api/client";
import { useOperationalOverview } from "../api/operational";
import { label } from "../api/operational-adapters";
import { useMe } from "../api/queries";
import { t } from "../i18n";
import { fmtDate } from "../lib/format";
import { IconUser } from "./icons";

export function Layout() {
  const overview = useOperationalOverview();
  const snapshot = overview.data?.snapshot;
  const me = useMe();
  const location = useLocation();
  const nav = [
    {
      to: "/operations",
      label: t.tower.overview,
      active: location.pathname === "/operations",
    },
    {
      to: "/signals",
      label: t.tower.signals,
      active:
        location.pathname.startsWith("/signals") ||
        location.pathname === "/alerts",
    },
    {
      to: "/assurance",
      label: t.tower.assurance,
      active:
        location.pathname === "/assurance" || location.pathname === "/models",
    },
  ];
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="skip-link">
        {t.app.skipToContent}
      </a>
      <header className="tower-header">
        <div className="tower-masthead">
          <NavLink to="/operations" className="min-w-0">
            <span className="brand-kicker">{t.tower.brand}</span>
            <span className="block text-xl font-semibold">
              {t.tower.subtitle}
            </span>
          </NavLink>
          <div className="role-state">
            {me.data ? (
              <>
                <span className="inline-flex items-center gap-2">
                  <IconUser size={16} />
                  {t.app.role(me.data.role_label)}
                </span>
                <span className="text-xs">{me.data.label}</span>
              </>
            ) : (
              <span>{me.isError ? t.app.noKey : t.common.loading}</span>
            )}
          </div>
        </div>
        <div className="tower-nav">
          <nav aria-label={t.nav.main}>
            <ul className="flex flex-wrap gap-1">
              {nav.map((item) => (
                <li key={item.to}>
                  <Link
                    to={item.to}
                    aria-current={item.active ? "page" : undefined}
                    className={`tower-nav-link ${item.active ? "is-active" : ""}`}
                  >
                    {item.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <Link to="/demo/detect" className="tower-nav-link tower-guide-link">
              {t.demo.openGuide} →
            </Link>
            <div role="status">
              {snapshot ? (
                <>
                  <span>
                    {t.tower.origin}: {fmtDate(snapshot.origin)}
                  </span>
                  <span className="ml-3">
                    {label(snapshot.status)} · {t.tower.freshness}:{" "}
                    {label(snapshot.freshness)}
                  </span>
                </>
              ) : overview.isError ? (
                overview.error instanceof ApiError &&
                overview.error.status === 404 ? (
                  t.tower.noPublication
                ) : (
                  t.tower.unavailable
                )
              ) : (
                t.common.loading
              )}
            </div>
          </div>
        </div>
      </header>
      <main
        id="main"
        tabIndex={-1}
        className="mx-auto w-full max-w-[1440px] flex-1 px-4 py-7 md:px-6"
      >
        <Outlet />
      </main>
      <footer className="border-t border-line bg-white">
        <p className="mx-auto max-w-[1440px] px-6 py-4 text-sm text-muted">
          {t.tower.footer}
        </p>
      </footer>
      <ScrollRestoration />
    </div>
  );
}
