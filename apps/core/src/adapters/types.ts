// The platform seam. Web supplies the browser AppState signal; mobile supplies Expo's.
export interface ForegroundSignal {
  isForeground: () => boolean
  subscribe: (listener: (foreground: boolean) => void) => () => void
}
