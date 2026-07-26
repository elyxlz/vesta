import { useCallback, useEffect, useLayoutEffect, useRef } from "react";
import { AppState } from "react-native";
import { shouldAcceptComposerTextChange } from "./chat-composer-input-model";

export function useChatComposerLifecycle({
  value,
  onChangeText,
  restoreNativeValue,
}: {
  value: string;
  onChangeText: (value: string) => void;
  restoreNativeValue: (value: string) => void;
}) {
  const valueRef = useRef(value);
  const onChangeTextRef = useRef(onChangeText);
  const focusedRef = useRef(false);
  const appInteractiveRef = useRef(AppState.currentState === "active");
  const resumeFramesRef = useRef<number[]>([]);

  const cancelResumeFrames = useCallback(() => {
    for (const frame of resumeFramesRef.current) cancelAnimationFrame(frame);
    resumeFramesRef.current = [];
  }, []);

  const restoreCurrentValue = useCallback(() => {
    restoreNativeValue(valueRef.current);
  }, [restoreNativeValue]);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      cancelResumeFrames();
      appInteractiveRef.current = false;
      restoreCurrentValue();

      if (state !== "active") return;
      const firstFrame = requestAnimationFrame(() => {
        restoreCurrentValue();
        const secondFrame = requestAnimationFrame(() => {
          restoreCurrentValue();
          appInteractiveRef.current = AppState.currentState === "active";
          resumeFramesRef.current = [];
        });
        resumeFramesRef.current.push(secondFrame);
      });
      resumeFramesRef.current.push(firstFrame);
    });

    return () => {
      subscription.remove();
      cancelResumeFrames();
    };
  }, [cancelResumeFrames, restoreCurrentValue]);

  useLayoutEffect(() => {
    valueRef.current = value;
    onChangeTextRef.current = onChangeText;
    restoreNativeValue(value);
  }, [onChangeText, restoreNativeValue, value]);

  const onNativeTextChange = useCallback(
    (nextValue: string) => {
      const currentValue = valueRef.current;
      const interactive =
        focusedRef.current && appInteractiveRef.current === true;
      if (
        !shouldAcceptComposerTextChange(interactive, currentValue, nextValue)
      ) {
        restoreNativeValue(currentValue);
        return;
      }
      onChangeTextRef.current(nextValue);
    },
    [restoreNativeValue],
  );

  const onFocusChange = useCallback((focused: boolean) => {
    focusedRef.current = focused;
  }, []);

  return { onFocusChange, onNativeTextChange };
}
