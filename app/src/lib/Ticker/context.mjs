import { invariant } from 'motion-utils';
import { useContext, createContext } from 'react';

const TickerContext = /** @__PURE__ */ createContext(null);
function useTicker() {
    const context = useContext(TickerContext);
    invariant(Boolean(context), "useTicker must be used within a Ticker component");
    return context;
}

export { TickerContext, useTicker };
