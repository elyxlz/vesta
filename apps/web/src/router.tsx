import { createBrowserRouter, Navigate } from "react-router-dom";
import { RouteErrorBoundary } from "@/components/ErrorBoundary";
import { AgentLayout } from "@/layouts/AgentLayout";
import { HomeLayout } from "@/layouts/HomeLayout";
import { NavigationGuard } from "@/layouts/NavigationGuard";
import {
  AgentLogs,
  AgentSettingsPage,
  Connect,
  Debug,
  Home,
  NewAgent,
} from "@/pages";

const basename = import.meta.env.BASE_URL.replace(/\/$/, "") || "/";

export const router = createBrowserRouter(
  [
    {
      errorElement: <RouteErrorBoundary />,
      children: [
        { path: "/connect", element: <Connect /> },
        { path: "/debug", element: <Debug /> },
        {
          element: <NavigationGuard />,
          errorElement: <RouteErrorBoundary />,
          children: [
            {
              element: <HomeLayout />,
              children: [
                { index: true, element: <Home /> },
                { path: "new", element: <NewAgent /> },
              ],
            },
            {
              path: "agent/:name",
              element: <AgentLayout />,
              errorElement: <RouteErrorBoundary />,
              children: [
                { index: true, element: null },
                { path: "chat", element: null },
                { path: "logs", element: <AgentLogs /> },
                { path: "settings", element: <AgentSettingsPage /> },
              ],
            },
            { path: "*", element: <Navigate to="/" replace /> },
          ],
        },
      ],
    },
  ],
  { basename },
);
