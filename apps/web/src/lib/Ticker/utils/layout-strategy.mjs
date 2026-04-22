const ltrStrategy = (
  insetProp,
  lengthProp,
  viewportLengthProp,
  paddingStartProp,
  direction,
) => {
  return {
    sign: 1,
    direction,
    lengthProp,
    viewportLengthProp,
    paddingStartProp,
    measureItem: (item) => {
      return {
        start: item[insetProp],
        end: item[insetProp] + item[lengthProp],
      };
    },
    getCumulativeInset: (element) => {
      let offset = 0;
      let el = element;
      while (el) {
        offset += el[insetProp];
        el = el.offsetParent;
      }
      return offset;
    },
  };
};
const xStrategy = ltrStrategy(
  "offsetLeft",
  "offsetWidth",
  "innerWidth",
  "paddingLeft",
  "right",
);
const yStrategy = ltrStrategy(
  "offsetTop",
  "offsetHeight",
  "innerHeight",
  "paddingTop",
  "bottom",
);
function offsetRight(element, container) {
  const containerWidth = container?.offsetWidth ?? window.innerWidth;
  return containerWidth - (element.offsetLeft + element.offsetWidth);
}
const xRtlStrategy = {
  ...xStrategy,
  sign: -1,
  direction: "left",
  paddingStartProp: "paddingRight",
  measureItem: (item, container) => {
    const length = item.offsetWidth;
    const start = offsetRight(item, container);
    return { start, end: start + length };
  },
  getCumulativeInset: (element) => {
    let offset = 0;
    let el = element;
    while (el) {
      offset += offsetRight(el, el.offsetParent);
      el = el.offsetParent;
    }
    return offset;
  },
};
function getLayoutStrategy(axis, direction) {
  return axis === "y"
    ? yStrategy
    : direction === "ltr"
      ? xStrategy
      : xRtlStrategy;
}

export { getLayoutStrategy };
