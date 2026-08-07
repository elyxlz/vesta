export { default } from "../../../node_modules/react-native-reanimated/lib/module/index";
export * from "../../../node_modules/react-native-reanimated/lib/module/index";

const noTransition = {
  duration: () => undefined,
};

export const FadeIn = noTransition;
export const FadeInDown = noTransition;
export const FadeOut = noTransition;
export const FadeOutUp = noTransition;
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
