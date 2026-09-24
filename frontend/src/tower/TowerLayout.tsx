/** Shell of the control centre: brand, sections, language, the task bell, and the drawer + dialog host. */
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { ApiError } from "../api/client";
import { useOperationalOverview } from "../api/operational";
import { SCENES, scenePath } from "../demo/journey";
import { GlyphMark } from "../demo/glyphs";
import { t, useLang } from "../i18n";
import { fmtDate } from "../lib/format";
import { Tour } from "./components/Tour";
import { tourSeen } from "./tour-state";
import { LanguageSwitch, TaskBell, TaskHost } from "./TaskHost";
import { useUi } from "./ui";

export function TowerLayout() {
  const overview = useOperationalOverview();
  const snapshot = overview.data?.snapshot;
  const lang = useLang();
  const ui = useUi();
  const location = useLocation();
  const [tour, setTour] = useState(false);
  // First visit of the control centre: open the walkthrough once the page has its anchors.
  useEffect(() => {
    if (location.pathname !== "/" || tourSeen()) return;
    // Wait until the page has rendered its anchors (data arrives asynchronously), then open once.
    let tries = 0;
    const timer = window.setInterval(() => {
      tries += 1;
      if (document.querySelector('[data-tour="play"]')) {
        window.clearInterval(timer);
        setTour(true);
      } else if (tries > 40) window.clearInterval(timer);
    }, 300);
    return () => window.clearInterval(timer);
  }, [location.pathname]);
  return (
    <div
      className={`demo-root tower-root ${ui.explorerOpen ? "explorer-open" : ""}`}
    >
      <a href="#main" className="skip-link">
        {t.app.skipToContent}
      </a>
      <header className="tower-head">
        <Link to="/" className="tower-brand">
          <span className="demo-brand-mark" aria-hidden="true">
            <GlyphMark size={18} />
          </span>
          <span className="demo-brand-text">
            <span className="demo-brand-name">{t.control.brand}</span>
            <span className="demo-brand-kicker">{t.control.brandKicker}</span>
          </span>
        </Link>
        <nav className="tower-nav" aria-label={t.control.nav.menu}>
          <NavLink to="/" end className="tower-nav-link">
            {t.control.nav.tower}
          </NavLink>
          <NavLink
            to="/notifications"
            className="tower-nav-link"
            data-tour="notifications"
          >
            {t.control.nav.notifications}
          </NavLink>
          <NavLink to="/queue" className="tower-nav-link">
            {t.control.nav.queue}
          </NavLink>
          <details className="tower-menu">
            <summary className="tower-nav-link">
              {t.control.nav.howItWorks}
            </summary>
            <div className="tower-menu-panel">
              <p>{t.control.nav.howItWorksLead}</p>
              <ol>
                {SCENES.map((id, i) => (
                  <li key={id}>
                    <Link to={scenePath(id)}>
                      <span className="tower-menu-index">{i + 1}</span>
                      <span>
                        <strong>{t.demo.scenes[id].label}</strong>
                        <small>{t.demo.scenes[id].kicker}</small>
                      </span>
                    </Link>
                  </li>
                ))}
              </ol>
            </div>
          </details>
        </nav>
        <div className="tower-state">
          <span role="status" className="tower-origin">
            {snapshot ? (
              <>
                {t.control.origin(fmtDate(snapshot.origin))}
                <span className="tower-state-tag">{t.control.publication}</span>
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
          </span>
          <LanguageSwitch />
          <button
            type="button"
            className="help-btn"
            aria-label={t.control.tour.open}
            title={t.control.tour.open}
            onClick={() => setTour(true)}
          >
            ?
          </button>
          <span data-tour="tasks" className="tour-anchor">
            <TaskBell />
          </span>
        </div>
      </header>
      <main id="main" className="tower-main" key={lang}>
        <Outlet />
      </main>
      <footer className="tower-foot">
        <p>{t.control.footer}</p>
      </footer>
      <TaskHost />
      {tour ? <Tour onClose={() => setTour(false)} /> : null}
    </div>
  );
}
