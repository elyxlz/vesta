import { expect, it, vi } from "vitest";
import { SheetChrome } from "./sheet-chrome.android";
import { SheetTitle } from "./sheet-title";

vi.mock("react-native", () => ({
  Pressable: "Pressable",
  Text: "Text",
  View: "View",
  StyleSheet: { create: <T>(styles: T) => styles },
}));
vi.mock("@expo/vector-icons", () => ({ Ionicons: "Ionicons" }));
vi.mock("expo-router", () => ({ useRouter: () => ({ back: vi.fn() }) }));
vi.mock("expo-router/stack", () => ({ default: { Title: "Stack.Title" } }));
vi.mock("@/preferences/PreferencesProvider", () => ({
  usePreferences: () => ({ colors: { text: "black", elevated: "#f4f1ed" } }),
}));

it("keeps Android sheet titles in the same font, size, and weight as iOS", () => {
  const ios = SheetTitle({ children: "Provider and model" });
  const android = SheetChrome({ title: "Provider and model" });
  const title = android.props.children[1].props.children[0];

  expect(ios.props.style).toEqual({
    fontFamily: "Archivo_500Medium",
    fontSize: 20,
    fontWeight: "500",
  });
  expect(title.type).toBe("Text");
  expect(title.props.style[0]).toMatchObject(ios.props.style);
  expect(title.props.children).toBe("Provider and model");
});

it("gives sheet controls symmetric circular surfaces without shifting the title", () => {
  const android = SheetChrome({
    title: "Notifications",
    closeLabel: "Close notifications",
    action: {
      accessibilityLabel: "Notification rules",
      onPress: vi.fn(),
      icon: null,
    },
  });
  const [title, close, action] = android.props.children[1].props.children;

  expect(title.props.style[0]).toMatchObject({
    textAlign: "center",
    paddingHorizontal: 64,
  });
  expect(Object.assign({}, ...close.props.style)).toMatchObject({
    width: 44,
    height: 44,
    borderRadius: 22,
    left: 16,
    backgroundColor: "#f4f1ed",
  });
  expect(Object.assign({}, ...action.props.style)).toMatchObject({
    width: 44,
    height: 44,
    borderRadius: 22,
    right: 16,
    backgroundColor: "#f4f1ed",
  });
  expect(Object.assign({}, ...close.props.style)).not.toHaveProperty("boxShadow");
  expect(Object.assign({}, ...action.props.style)).not.toHaveProperty("boxShadow");
  expect(close.props.accessibilityLabel).toBe("Close notifications");
  expect(action.props.accessibilityLabel).toBe("Notification rules");
  expect(close.props.children.props.size).toBe(32);
  expect(close.props.children.props.name).toBe("close-outline");
});
