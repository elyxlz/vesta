import { vi } from "vitest";

// jsdom lacks ResizeObserver, which Radix primitives (e.g. ScrollArea) call on mount. Stub it so
// component tests can render those primitives.
class ResizeObserverStub {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}

vi.stubGlobal("ResizeObserver", ResizeObserverStub);

// jsdom lacks matchMedia, which useMediaQuery (via useIsMobile/useFillHeight) reads on mount.
// Stub a non-matching query so components that branch on breakpoints render their default layout.
vi.stubGlobal("matchMedia", (query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  addListener: vi.fn(),
  removeListener: vi.fn(),
  dispatchEvent: () => false,
}));
