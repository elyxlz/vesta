import { createBrowserRouter, Navigate } from "react-router-dom";
import { RouteErrorBoundary } from "@/components/ErrorBoundary";
import { AgentLayout } from "@/lib/AgentLayout";
import { NavigationGuard } from "@/lib/NavigationGuard";
import { RootLayout } from "@/lib/RootLayout";
import {
  AgentChat,
  AgentDashboard,
  AgentSettingsPage,
  Connect,
  Home,
  NewAgent,
} from "@/pages";

export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    errorElement: <RouteErrorBoundary />,
    children: [
      { path: "/connect", element: <Connect /> },
      {
        element: <NavigationGuard />,
        errorElement: <RouteErrorBoundary />,
        children: [
          { index: true, element: <Home /> },
          { path: "new", element: <NewAgent /> },
          {
            path: "agent/:name",
            element: <AgentLayout />,
            errorElement: <RouteErrorBoundary />,
            children: [
              { index: true, element: <AgentDashboard /> },
              { path: "chat", element: <AgentChat /> },
              { path: "settings", element: <AgentSettingsPage /> },
            ],
          },
          { path: "*", element: <Navigate to="/" replace /> },
        ],
      },
    ],
  },
]);
