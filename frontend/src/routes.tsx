import type { RouteObject } from "react-router-dom";

import { Layout } from "./components/Layout";
import { AlertsPage } from "./pages/AlertsPage";
import { HospitalPage } from "./pages/hospital/HospitalPage";
import { ModelsPage } from "./pages/ModelsPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SignalPage } from "./pages/SignalPage";
import { RegionPage } from "./pages/RegionPage";

/** Screen map: docs/frontend.md */
export const routes: RouteObject[] = [
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <OverviewPage /> },
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
