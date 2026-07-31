// @ts-expect-error The harness bypasses the package export map to avoid its Metro alias.
export { default } from "../../../node_modules/react-native-reanimated/lib/module/index";
// @ts-expect-error The runtime module is typed by the public package in app code.
export * from "../../../node_modules/react-native-reanimated/lib/module/index";

const noTransition = {
  duration: () => undefined,
};

export const FadeIn = noTransition;
export const FadeOut = noTransition;
export const SlideInDown = noTransition;
