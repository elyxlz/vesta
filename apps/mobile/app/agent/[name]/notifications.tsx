import Stack from "expo-router/stack";
import NotificationsPage from "@/agent/NotificationsPage";

function NotificationsContent() {
  return (
    <>
      <Stack.Title>Notifications</Stack.Title>
      <NotificationsPage />
    </>
  );
}

export default function NotificationsScreen() {
  return <NotificationsContent />;
}
