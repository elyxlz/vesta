import { readFile } from "node:fs/promises";
import vm from "node:vm";
import { expect, it, vi } from "vitest";

async function loadScrollView(pageScrolling) {
  const native = Object.assign(function NativeScrollView() {}, {
    Context: Symbol("native context"),
  });
  const modules = {
    react: {
      forwardRef: (render) => render,
      useRef: (value) => ({ current: value }),
      createElement: (type, props) => ({ type, props }),
    },
    "../../../node_modules/react-native/Libraries/Components/ScrollView/ScrollView":
      {
        default: native,
      },
    "./launch-query": { visualSwitch: () => pageScrolling },
  };
  const sandbox = vm.createContext({
    require: (name) => modules[name],
    exports: {},
  });
  vm.runInContext(
    await readFile(
      new URL("../visual/harness/scroll-view.js", import.meta.url),
      "utf8",
    ),
    sandbox,
  );
  // Metro's default import interop is also used by RN's Animated.ScrollView.
  const imported = sandbox.exports.__esModule
    ? sandbox.exports
    : { default: sandbox.exports };
  return { ScrollView: imported.default, native };
}

it("advances one overlapping viewport regardless of gesture distance or momentum", async () => {
  const { ScrollView, native } = await loadScrollView("page");
  const onScrollEndDrag = vi.fn();
  const ref = {};
  const children = {};
  const view = ScrollView({ onScrollEndDrag, children, testID: "page" }, ref);
  expect(view.type).toBe(native);
  expect(ScrollView.Context).toBe(native.Context);
  expect(view.props).toMatchObject({
    children,
    testID: "page",
    decelerationRate: "fast",
  });
  const scrollTo = vi.fn();
  view.props.ref({ scrollTo });
  expect(ref.current).toEqual({ scrollTo });
  for (const distance of [100, 700]) {
    view.props.onScrollBeginDrag(scrollEvent(0));
    const end = scrollEvent(distance);
    view.props.onScrollEndDrag(end);
    expect(onScrollEndDrag).toHaveBeenLastCalledWith(end);
    expect(scrollTo).toHaveBeenLastCalledWith({ y: 600, animated: false });
    view.props.onMomentumScrollEnd(scrollEvent(900));
    expect(scrollTo).toHaveBeenLastCalledWith({ y: 600, animated: false });
  }
});

function scrollEvent(y, contentHeight = 2500) {
  return {
    nativeEvent: {
      contentOffset: { y },
      layoutMeasurement: { height: 800 },
      contentSize: { height: contentHeight },
    },
  };
}

it.each([
  [1500, 1650, 2500, 1700],
  [100, 0, 2500, 0],
  [0, 0, 500, 0],
])(
  "clamps a drag from %s to %s within the real content",
  async (start, end, height, expected) => {
    const { ScrollView } = await loadScrollView("page");
    const ref = vi.fn();
    const view = ScrollView({}, ref);
    const native = { scrollTo: vi.fn() };
    view.props.ref(native);
    expect(ref).toHaveBeenCalledWith(native);
    view.props.onScrollBeginDrag(scrollEvent(start, height));
    view.props.onScrollEndDrag(scrollEvent(end, height));
    expect(native.scrollTo).toHaveBeenLastCalledWith({
      y: expected,
      animated: false,
    });
  },
);

it.each([
  ["", false],
  ["page", true],
])(
  "preserves ordinary scrolling for mode %s, horizontal %s",
  async (mode, horizontal) => {
    const { ScrollView, native } = await loadScrollView(mode);
    const props = { horizontal, snapToInterval: 123, onLayout: vi.fn() };
    const ref = {};
    expect(ScrollView(props, ref)).toEqual({
      type: native,
      props: { ...props, ref },
    });
  },
);
