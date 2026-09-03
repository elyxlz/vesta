/**
 * Tracks whether a real quit is underway. On macOS the window's close is turned into hide
 * (keep-in-dock), and that guard must lift once the app is genuinely quitting. quitAndInstall()
 * emits before-quit-for-update, not before-quit, so both events must flip the flag or an update
 * relaunch only hides the window and never installs.
 */
interface QuitLifecycleApp {
  on(
    event: "before-quit" | "before-quit-for-update",
    listener: () => void,
  ): unknown;
}

export function trackQuitIntent(app: QuitLifecycleApp): () => boolean {
  let quitting = false;
  const onQuit = () => {
    quitting = true;
  };
  app.on("before-quit", onQuit);
  app.on("before-quit-for-update", onQuit);
  return () => quitting;
}
