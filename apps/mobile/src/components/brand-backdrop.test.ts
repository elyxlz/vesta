import { expect, it, vi } from "vitest";
import { BrandBackdrop } from "./brand-backdrop";
import { BlockingSheetGateView } from "./blocking-sheet-gate-view";
import { SheetGateScreen } from "./sheet-gate-screen.android";

vi.mock("react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react")>()),
  useEffect: vi.fn(),
}));
vi.mock("react-native", () => ({
  View: "View",
  StyleSheet: { create: <T>(styles: T) => styles },
}));
vi.mock("expo-status-bar", () => ({ StatusBar: "StatusBar" }));
vi.mock("./VestaBrand", () => ({ VestaBrand: "VestaBrand" }));
vi.mock("@/preferences/PreferencesProvider", () => ({
  usePreferences: () => ({
    colors: { background: "#fff", card: "#eee" },
    dark: false,
  }),
}));

it("centers the lockup in the full page without reserving space for sheets or system bars", () => {
  const backdrop = BrandBackdrop({});
  expect(Object.assign({}, ...backdrop.props.style)).toEqual({
    position: "absolute",
    inset: 0,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
    backgroundColor: "#fff",
  });
  expect(backdrop.props.pointerEvents).toBe("none");
  expect(backdrop.props.children.type).toBe("VestaBrand");
});

it("preserves the auth orb's boot-transition target", () => {
  const orb = "custom boot target";
  expect(BrandBackdrop({ orb }).props.children.props.orb).toBe(orb);
});

it("uses the same page-filling backdrop while a blocking sheet is being presented", () => {
  const gate = BlockingSheetGateView({
    blocked: true,
    presented: false,
    children: "app",
  });
  const [content, overlay] = gate.props.children;
  expect(content.props.accessibilityElementsHidden).toBe(true);
  expect(overlay.props.style).toMatchObject({ position: "absolute", inset: 0 });
  expect(overlay.props.children[1].type).toBe(BrandBackdrop);
});

it("layers Android sheet content over the full-page brand instead of sharing its flex space", () => {
  const screen = SheetGateScreen({ children: "sheet of any height" });
  const [, backdrop, scrim, card] = screen.props.children;
  expect(Object.assign({}, ...screen.props.style)).toMatchObject({
    flex: 1,
    justifyContent: "flex-end",
  });
  expect(backdrop.type).toBe(BrandBackdrop);
  expect(scrim.props.pointerEvents).toBe("none");
  expect(card.props.children).toBe("sheet of any height");
});
