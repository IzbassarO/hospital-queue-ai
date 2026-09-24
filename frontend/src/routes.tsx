import { Navigate, type RouteObject } from "react-router-dom";

import { DemoLayout } from "./demo/DemoLayout";
import { DemoScene } from "./demo/scenes/DemoScene";
import { NotificationsPage } from "./tower/NotificationsPage";
import { QueuePage } from "./tower/QueuePage";
import { TowerLayout } from "./tower/TowerLayout";
import { TowerPage } from "./tower/TowerPage";

/**
 * Screen map: the control centre at "/" (map, feed, waiting counts, top tasks), the notifications inbox at
 * "/notifications", the full queue at "/queue", and the six-scene story under /demo/:scene. Anything else goes home.
 */
export const routes: RouteObject[] = [
  {
    element: <TowerLayout />,
    children: [
      { index: true, path: "/", element: <TowerPage /> },
      { path: "notifications", element: <NotificationsPage /> },
      { path: "queue", element: <QueuePage /> },
    ],
  },
  {
    path: "/demo",
    element: <DemoLayout />,
    children: [
      { index: true, element: <Navigate to="/demo/flow" replace /> },
      { path: ":scene", element: <DemoScene /> },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
];
