import { createBrowserRouter, Navigate } from "react-router-dom";
import { RouteErrorBoundary } from "@/components/ErrorBoundary";
import { AgentLayout } from "@/layouts/AgentLayout";
import { HomeLayout } from "@/layouts/HomeLayout";
import { NavigationGuard } from "@/layouts/NavigationGuard";
import { isTauri } from "@/lib/env";
import {
  AgentChat,
  AgentDashboard,
  AgentLogs,
  AgentSettingsPage,
  Connect,
  Debug,
  Home,
  Landing,
  NewAgent,
} from "@/pages";

export const router = createBrowserRouter([
  {
    errorElement: <RouteErrorBoundary />,
    children: [
      {
        index: true,
        element: isTauri ? <Navigate to="/connect" replace /> : <Landing />,
      },
      { path: "/connect", element: <Connect /> },
      { path: "/debug", element: <Debug /> },
      {
        element: <NavigationGuard />,
        errorElement: <RouteErrorBoundary />,
        children: [
          {
            element: <HomeLayout />,
            children: [
              { path: "home", element: <Home /> },
              { path: "new", element: <NewAgent /> },
            ],
          },
          {
            path: "agent/:name",
            element: <AgentLayout />,
            errorElement: <RouteErrorBoundary />,
            children: [
              { index: true, element: <AgentDashboard /> },
              { path: "chat", element: <AgentChat /> },
              { path: "logs", element: <AgentLogs /> },
              { path: "settings", element: <AgentSettingsPage /> },
            ],
          },
          { path: "*", element: <Navigate to="/home" replace /> },
        ],
      },
    ],
  },
]);
