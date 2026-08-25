import { createBrowserRouter, Navigate } from "react-router-dom";
import { RouteErrorBoundary } from "@/components/ErrorBoundary";
import { AgentLayout } from "@/layouts/AgentLayout";
import { HomeLayout } from "@/layouts/HomeLayout";
import { NavigationGuard } from "@/layouts/NavigationGuard";
import {
  AppSettingsPage,
  Callback,
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
        { path: "/cb", element: <Callback /> },
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
            { path: "settings", element: <AppSettingsPage /> },
            {
              path: "agent/:name",
              element: <AgentLayout />,
              errorElement: <RouteErrorBoundary />,
              // Subpages render as null: AgentLayout keeps every pane mounted
              // in an Activity and shows the one matching the location.
              children: [
                { index: true, element: null },
                { path: "chat", element: null },
                { path: "logs", element: null },
                { path: "settings", element: null },
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
