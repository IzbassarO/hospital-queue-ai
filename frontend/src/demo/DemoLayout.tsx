/** Guided journey shell: brand, five-scene progress navigation, previous/next controls and keyboard arrows. */
import { useEffect } from "react";
import {
  Link,
  Navigate,
  Outlet,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import { ApiError } from "../api/client";
import { useOperationalOverview } from "../api/operational";
import { t } from "../i18n";
import { fmtDate } from "../lib/format";
import { SCENES, isScene, scenePath, type SceneId } from "./journey";

export function DemoLayout() {
  const { scene = "" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const overview = useOperationalOverview();
  const index = SCENES.indexOf(scene as SceneId);
  const previous = index > 0 ? SCENES[index - 1] : null;
  const next =
    index >= 0 && index < SCENES.length - 1 ? SCENES[index + 1] : null;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented ||
        event.altKey ||
        event.metaKey ||
        event.ctrlKey
      )
        return;
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.closest("input, select, textarea, [contenteditable]") ||
          document.querySelector('[role="dialog"]'))
      )
        return;
      if (event.key === "ArrowRight" && next) {
        event.preventDefault();
        navigate(scenePath(next, location.search));
      } else if (event.key === "ArrowLeft" && previous) {
        event.preventDefault();
        navigate(scenePath(previous, location.search));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [next, previous, navigate, location.search]);

  if (!isScene(scene)) return <Navigate to={scenePath("detect")} replace />;
  const snapshot = overview.data?.snapshot;
  return (
    <div className="demo-root">
      <a href="#scene-title" className="skip-link">
        {t.app.skipToContent}
      </a>
      <header className="demo-header">
        <div className="demo-brand">
          <Link to={scenePath("detect", location.search)} className="min-w-0">
            <span className="demo-brand-name">{t.demo.brand}</span>
            <span className="demo-brand-kicker">{t.demo.brandKicker}</span>
          </Link>
        </div>
        <nav className="demo-progress" aria-label={t.demo.progress}>
          <ol>
            {SCENES.map((id, i) => (
              <li key={id}>
                <Link
                  to={scenePath(id, location.search)}
                  className={`progress-step ${i === index ? "is-active" : ""} ${i < index ? "is-done" : ""}`}
                  aria-current={i === index ? "step" : undefined}
                >
                  <span className="progress-index">{i + 1}</span>
                  <span className="progress-label">
                    {t.demo.scenes[id].label}
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        </nav>
        <div className="demo-header-right">
          <span className="demo-origin" role="status">
            {snapshot
              ? `${t.demo.origin}: ${fmtDate(snapshot.origin)}`
              : overview.isError
                ? overview.error instanceof ApiError &&
                  overview.error.status === 404
                  ? t.tower.noPublication
                  : t.tower.unavailable
                : t.common.loading}
          </span>
          <Link to="/operations" className="btn-ghost">
            {t.demo.openOperations}
          </Link>
        </div>
      </header>
      <main id="main" className="demo-main" key={scene}>
        <Outlet />
      </main>
      <footer className="demo-footer">
        <div className="demo-footer-left">
          <span>{t.demo.scene(index + 1, SCENES.length)}</span>
          <span className="demo-keyhint">{t.demo.keyboardHint}</span>
        </div>
        <div className="demo-footer-nav">
          {previous ? (
            <Link
              to={scenePath(previous, location.search)}
              className="btn-ghost"
              rel="prev"
            >
              ← {t.demo.previous}
            </Link>
          ) : (
            <span className="btn-ghost is-disabled" aria-disabled="true">
              ← {t.demo.previous}
            </span>
          )}
          {next ? (
            <Link
              to={scenePath(next, location.search)}
              className="btn-accent"
              rel="next"
            >
              {t.demo.next}: {t.demo.scenes[next].label} →
            </Link>
          ) : (
            <Link to="/operations" className="btn-accent">
              {t.demo.openOperations} →
            </Link>
          )}
        </div>
      </footer>
    </div>
  );
}
