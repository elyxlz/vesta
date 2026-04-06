import { createBrowserRouter, Navigate } from "react-router-dom";
import { AgentLayout } from "@/lib/AgentLayout";
import { NavigationGuard } from "@/lib/NavigationGuard";
import { RootLayout } from "@/lib/RootLayout";
import {
  AgentChat,
  AgentDashboard,
  Connect,
  CreateAgent,
  Home,
} from "@/pages";

export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      { path: "/connect", element: <Connect /> },
      {
        element: <NavigationGuard />,
        children: [
          { index: true, element: <Home /> },
          { path: "new", element: <CreateAgent /> },
          {
            path: "agent/:name",
            element: <AgentLayout />,
            children: [
              { index: true, element: <AgentDashboard /> },
              { path: "chat", element: <AgentChat /> },
            ],
          },
          { path: "*", element: <Navigate to="/" replace /> },
        ],
      },
    ],
  },
]);
