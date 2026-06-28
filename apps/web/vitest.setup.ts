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
