// jsdom lacks ResizeObserver, which Radix primitives (e.g. ScrollArea) call on mount. Stub it so
// component tests can render those primitives.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver =
    ResizeObserverStub as unknown as typeof ResizeObserver;
}

// jsdom lacks matchMedia, which useMediaQuery (via useIsMobile/useFillHeight) reads on mount.
// Stub a non-matching query so components that branch on breakpoints render their default layout.
if (!globalThis.matchMedia) {
  globalThis.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent() {
      return false;
    },
  })) as unknown as typeof window.matchMedia;
}
