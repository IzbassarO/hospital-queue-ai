import { Navigate, type RouteObject } from "react-router-dom";

import { Layout } from "./components/Layout";
import { DemoLayout } from "./demo/DemoLayout";
import { DemoScene } from "./demo/scenes/DemoScene";
import { AlertsPage } from "./pages/AlertsPage";
import { HospitalPage } from "./pages/hospital/HospitalPage";
import { ModelsPage } from "./pages/ModelsPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SignalPage } from "./pages/SignalPage";
import { RegionPage } from "./pages/RegionPage";

/**
 * Screen map: docs/frontend.md. The guided decision journey (/demo/:scene) is the primary experience;
 * the Control Tower remains the secondary operations view under /operations and its drill-down routes.
 */
export const routes: RouteObject[] = [
  { path: "/", element: <Navigate to="/demo/detect" replace /> },
  {
    path: "/demo",
    element: <DemoLayout />,
    children: [
      { index: true, element: <Navigate to="/demo/detect" replace /> },
      { path: ":scene", element: <DemoScene /> },
    ],
  },
  {
    element: <Layout />,
    children: [
      { path: "operations", element: <OverviewPage /> },
      { path: "regions/:code", element: <RegionPage /> },
      { path: "hospitals/:org/profiles/:profile", element: <HospitalPage /> },
      { path: "signals", element: <AlertsPage /> },
      { path: "signals/:signalId", element: <SignalPage /> },
      { path: "assurance", element: <ModelsPage /> },
      { path: "alerts", element: <AlertsPage /> },
      { path: "models", element: <ModelsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
