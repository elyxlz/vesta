Object.defineProperty(exports, "__esModule", { value: true });

const React = require("react");
const NativeScrollView =
  require("../../../node_modules/react-native/Libraries/Components/ScrollView/ScrollView").default;
const { visualSwitch } = require("./launch-query");
const pageScrolling = visualSwitch("visualScroll") === "page";

// Keep native layout, but make each page-capture drag advance one overlapping
// viewport. snapToInterval alone still lets gesture velocity choose how many
// intervals to skip, changing both the pixels and number of captured parts.
const ScrollView = React.forwardRef(function VisualScrollView(props, ref) {
  const nativeRef = React.useRef(null);
  const dragStart = React.useRef(0);
  const target = React.useRef(null);
  if (!pageScrolling || props.horizontal)
    return React.createElement(NativeScrollView, { ...props, ref });
  return React.createElement(NativeScrollView, {
    ...props,
    ref: (value) => {
      nativeRef.current = value;
      if (typeof ref === "function") ref(value);
      else if (ref) ref.current = value;
    },
    decelerationRate: "fast",
    onScrollBeginDrag: (event) => {
      dragStart.current = event.nativeEvent.contentOffset.y;
      target.current = null;
      props.onScrollBeginDrag?.(event);
    },
    onScrollEndDrag: (event) => {
      const { contentOffset, layoutMeasurement, contentSize } =
        event.nativeEvent;
      const direction = Math.sign(contentOffset.y - dragStart.current);
      const step = Math.floor((layoutMeasurement.height * 3) / 4);
      target.current = Math.max(
        0,
        Math.min(
          contentSize.height - layoutMeasurement.height,
          dragStart.current + direction * step,
        ),
      );
      props.onScrollEndDrag?.(event);
      nativeRef.current?.scrollTo({ y: target.current, animated: false });
    },
    onMomentumScrollEnd: (event) => {
      props.onMomentumScrollEnd?.(event);
      // A native fling can race the JS end-drag event. Reapply the same target,
      // never advance again, if it finishes after our nonanimated scroll.
      if (target.current !== null)
        nativeRef.current?.scrollTo({ y: target.current, animated: false });
    },
  });
});
Object.assign(ScrollView, NativeScrollView);
exports.default = ScrollView;
