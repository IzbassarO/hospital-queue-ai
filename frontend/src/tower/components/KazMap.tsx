/**
 * The map: twenty quiet region outlines, one dot per hospital of the registry, published severity as colour. Only
 * the attention queue (signals above the materiality floor) colours a dot; hospitals whose HIGH/ELEVATED signals
 * are all small flows sit in a muted layer that is off by default and switched on by the "малые потоки" toggle.
 * Hover shows what matters for that point; click focuses the hospital. All geometry is precomputed.
 */
import {
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
} from "react";
import { createPortal } from "react-dom";
import { t } from "../../i18n";
import { fmtDate, fmtNumber } from "../../lib/format";
import { POLYGON_CHILDREN, REGION_CAPITALS } from "../geo/places";
import {
  MAP_H,
  MAP_VARIANT,
  MAP_W,
  REGION_SHAPES,
  project,
} from "../geo/project";
import type { RegionSummary, TowerHospital } from "../useTowerData";

interface Tip {
  x: number;
  y: number;
  title: string;
  lines: string[];
  tone: "high" | "elevated" | "quiet" | "region" | "low";
}

export function KazMap({
  hospitals,
  regions,
  lowVolumeTotal,
  profileName,
  focus,
  pulse,
  outageRegion,
  onFocus,
}: {
  hospitals: TowerHospital[];
  regions: Map<string, RegionSummary>;
  /** HIGH + ELEVATED signals below the materiality floor, for the toggle's hint */
  lowVolumeTotal: number;
  profileName: (code: string) => string;
  focus: string | null;
  pulse: Set<string>;
  outageRegion: string | null;
  onFocus: (org: string | null) => void;
}) {
  const [tip, setTip] = useState<Tip | null>(null);
  const [hoverRegion, setHoverRegion] = useState<string | null>(null);
  const [showLowVolume, setShowLowVolume] = useState(false);
  const layers = useMemo(() => {
    const quiet = hospitals.filter((h) => !h.severity);
    const low = hospitals.filter((h) => !h.severity && h.lowVolume);
    const elevated = hospitals.filter((h) => h.severity === "ELEVATED");
    const high = hospitals.filter((h) => h.severity === "HIGH");
    return { quiet, low, elevated, high };
  }, [hospitals]);
  const focused = focus ? hospitals.find((h) => h.org === focus) : undefined;

  // Viewport coordinates: the tooltip is portalled to <body> so the map frame never clips it.
  const place = (e: MouseEvent) => ({ x: e.clientX, y: e.clientY });
  const showHospital = (h: TowerHospital, e: MouseEvent) => {
    const top = h.signals[0];
    const neighbours =
      hospitals.filter((x) => x.anchor === h.anchor).length - 1;
    const lines = top
      ? [
          `${h.regionName}`,
          `${t.control.map.signalsOf(h.signals.length)} · ${profileName(top.profile ?? "")}`,
          top.rawCrossing
            ? t.control.map.crossing(fmtDate(top.rawCrossing))
            : "",
        ].filter(Boolean)
      : [h.regionName, t.control.map.noSignal];
    if (h.lowVolumeSignals.length)
      lines.push(t.control.map.lowVolumeOf(h.lowVolumeSignals.length));
    if (neighbours > 0) lines.push(t.control.map.neighbours(neighbours));
    setTip({
      ...place(e),
      title: h.name,
      lines,
      tone:
        h.severity === "HIGH"
          ? "high"
          : h.severity === "ELEVATED"
            ? "elevated"
            : h.lowVolume
              ? "low"
              : "quiet",
    });
  };
  const regionLine = (r: RegionSummary) =>
    t.control.map.regionSignals(
      fmtNumber(r.attention, 0),
      fmtNumber(r.highMaterial, 0),
      fmtNumber(r.total, 0),
    );
  const showRegion = (code: string, e: MouseEvent) => {
    const own = regions.get(code);
    const kids = (
      MAP_VARIANT === "legacy" ? (POLYGON_CHILDREN[code] ?? []) : []
    )
      .map((k) => regions.get(k))
      .filter((r): r is RegionSummary => Boolean(r));
    const lines = [
      own ? regionLine(own) : "",
      own && own.lowVolume
        ? t.control.map.regionLowVolume(fmtNumber(own.lowVolume, 0))
        : "",
      ...kids.map((k) => `${t.control.map.includes(k.name)}: ${regionLine(k)}`),
      outageRegion === code || kids.some((k) => k.code === outageRegion)
        ? t.control.map.outage
        : "",
    ].filter(Boolean);
    setHoverRegion(code);
    setTip({ ...place(e), title: own?.name ?? code, lines, tone: "region" });
  };
  const hide = () => {
    setTip(null);
    setHoverRegion(null);
  };
  const dot = (h: TowerHospital, r: number, className: string) => (
    <circle
      key={h.org}
      cx={h.x}
      cy={h.y}
      r={r}
      className={className}
      onMouseEnter={(e) => showHospital(h, e)}
      onMouseMove={(e) => showHospital(h, e)}
      onClick={() => onFocus(h.org)}
    />
  );

  return (
    <div className="map-frame" onMouseLeave={hide}>
      <svg
        className="map-svg"
        viewBox={`0 0 ${MAP_W} ${MAP_H}`}
        role="img"
        aria-label={t.control.map.title}
      >
        <title>{t.control.map.title}</title>
        <g className="map-regions">
          {REGION_SHAPES.map((r) => {
            const outage =
              outageRegion !== null &&
              (r.code === outageRegion ||
                (MAP_VARIANT === "legacy" &&
                  (POLYGON_CHILDREN[r.code] ?? []).includes(outageRegion)));
            return (
              <path
                key={r.code}
                d={r.d}
                className={`map-region ${hoverRegion === r.code ? "is-hover" : ""} ${outage ? "is-outage" : ""}`}
                onMouseMove={(e) => showRegion(r.code, e)}
                onMouseEnter={(e) => showRegion(r.code, e)}
                onClick={() => onFocus(null)}
              />
            );
          })}
        </g>
        <g className="map-capitals" aria-hidden="true">
          {Object.entries(REGION_CAPITALS).map(([code, c]) => {
            const [x, y] = project(c.at);
            return (
              <text key={code} x={x + 6} y={y - 6} className="map-capital">
                {c.name}
              </text>
            );
          })}
        </g>
        <g className="map-dots">
          {layers.quiet.map((h) => dot(h, 2.2, "dot dot-quiet"))}
          {showLowVolume ? (
            <g className="map-low-volume" data-testid="map-low-volume">
              {layers.low.map((h) => dot(h, 2.8, "dot dot-low"))}
            </g>
          ) : null}
          {layers.elevated.map((h) =>
            dot(
              h,
              3.4,
              `dot dot-elevated ${pulse.has(h.org) ? "is-pulse" : ""}`,
            ),
          )}
          {layers.high.map((h) =>
            dot(h, 4.2, `dot dot-high ${pulse.has(h.org) ? "is-pulse" : ""}`),
          )}
          {focused ? (
            <g className="dot-focus" aria-hidden="true">
              <circle cx={focused.x} cy={focused.y} r={11} />
              <circle cx={focused.x} cy={focused.y} r={5} />
            </g>
          ) : null}
        </g>
      </svg>
      {tip ? <MapTip tip={tip} /> : null}
      <ul className="map-legend" aria-label={t.control.map.title}>
        <li>
          <span className="dot-swatch dot-high" /> {t.control.map.legend.high}
        </li>
        <li>
          <span className="dot-swatch dot-elevated" />{" "}
          {t.control.map.legend.elevated}
        </li>
        <li>
          <span className="dot-swatch dot-quiet" /> {t.control.map.legend.quiet}
        </li>
        <li>
          <span className="dot-swatch dot-ring" /> {t.control.map.legend.focus}
        </li>
        <li>
          <label className="map-toggle">
            <input
              type="checkbox"
              checked={showLowVolume}
              onChange={(e) => setShowLowVolume(e.target.checked)}
              title={t.control.map.lowVolumeToggleHint(
                fmtNumber(lowVolumeTotal, 0),
              )}
            />
            <span className="dot-swatch dot-low" />{" "}
            {t.control.map.lowVolumeToggle} ({fmtNumber(lowVolumeTotal, 0)})
          </label>
        </li>
      </ul>
    </div>
  );
}

/**
 * The floating card next to the cursor. Rendered on <body> with fixed positioning and flipped or shifted so it
 * always stays fully inside the viewport: above the cursor by default, below it near the top edge, clamped left
 * and right.
 */
function MapTip({ tip }: { tip: Tip }) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 240, h: 90 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    if (Math.abs(r.width - size.w) > 1 || Math.abs(r.height - size.h) > 1)
      setSize({ w: r.width, h: r.height });
  }, [tip, size.w, size.h]);
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const gap = 16;
  const above = tip.y - gap - size.h;
  const top = above >= 8 ? above : Math.min(vh - size.h - 8, tip.y + gap);
  const left = Math.min(Math.max(8, tip.x - size.w / 2), vw - size.w - 8);
  return createPortal(
    <div
      ref={ref}
      className={`map-tip tone-${tip.tone}`}
      style={{ left, top }}
      role="status"
    >
      <strong>{tip.title}</strong>
      {tip.lines.map((line) => (
        <span key={line}>{line}</span>
      ))}
    </div>,
    document.body,
  );
}
