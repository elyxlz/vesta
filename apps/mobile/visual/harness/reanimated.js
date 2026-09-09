export { default } from "../../../node_modules/react-native-reanimated/lib/module/index";
export * from "../../../node_modules/react-native-reanimated/lib/module/index";

// A builder that accepts any chain (duration, easing, delay, springify) and builds an
// animation that changes nothing, so a capture never waits on an entering or exiting effect.
function noAnimation() {
  "worklet";
  return { initialValues: {}, animations: {} };
}
const noTransition = {
  duration: () => noTransition,
  easing: () => noTransition,
  delay: () => noTransition,
  springify: () => noTransition,
  damping: () => noTransition,
  stiffness: () => noTransition,
  build: () => noAnimation,
};

export const FadeIn = noTransition;
export const FadeInDown = noTransition;
export const FadeInUp = noTransition;
export const FadeOut = noTransition;
export const FadeOutUp = noTransition;
export const FadeOutDown = noTransition;
export const SlideInDown = noTransition;

export function withTiming(value, _config, callback) {
  "worklet";
  if (callback) callback(true, value);
  return value;
}

export function withSpring(value, _config, callback) {
  "worklet";
  if (callback) callback(true, value);
  return value;
}

export function withDelay(_delay, animation) {
  "worklet";
  return animation;
}

export function withRepeat(animation) {
  "worklet";
  return animation;
}
