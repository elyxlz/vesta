import Stack from "expo-router/stack";
import NotificationsPage from "@/agent/NotificationsPage";
import { NativeSheetCloseButton } from "@/components/native-sheet-close-button";
import { SheetChrome } from "@/components/sheet-chrome";

function NotificationsContent() {
  return (
    <>
      <Stack.Title>Notifications</Stack.Title>
      <NativeSheetCloseButton accessibilityLabel="Close notifications" />
      <SheetChrome title="Notifications" closeLabel="Close notifications" />
      <NotificationsPage presentation="standalone" />
    </>
  );
}

export default function NotificationsScreen() {
  return <NotificationsContent />;
}
