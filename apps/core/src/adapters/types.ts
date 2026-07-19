// The platform seam: interfaces only in this stage. Web supplies localStorage
// plus the native bridge; mobile supplies SecureStore/AsyncStorage, AppState,
// and Expo push. Implementations land with the app migrations.
export interface StorageAdapter {
  get: (key: string) => Promise<string | null>
  set: (key: string, value: string) => Promise<void>
  remove: (key: string) => Promise<void>
}

export interface ForegroundSignal {
  isForeground: () => boolean
  subscribe: (listener: (foreground: boolean) => void) => () => void
}

export interface PushTokenProvider {
  token: () => Promise<string | null>
}
