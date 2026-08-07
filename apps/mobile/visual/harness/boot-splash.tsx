import { useEffect } from "react";
import * as SplashScreen from "expo-splash-screen";

export function BootSplash({
  onHandoff,
  onReveal,
  onFinish,
}: {
  onHandoff: () => void;
  onReveal: () => void;
  onFinish: () => void;
}) {
  useEffect(() => {
    void SplashScreen.hideAsync().catch(() => undefined);
    onReveal();
    onHandoff();
    onFinish();
  }, [onFinish, onHandoff, onReveal]);

  return null;
}
