import { invariant } from "motion-utils";
import { useContext } from "react";
import { TickerItemContext } from "./TickerItemContext.mjs";

function useTickerItem() {
  const itemContext = useContext(TickerItemContext);
  invariant(
    Boolean(itemContext),
    "useTickerItem must be used within a TickerItem",
  );
  return itemContext;
}

export { useTickerItem };
