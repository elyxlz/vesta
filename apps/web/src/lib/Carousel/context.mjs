import { invariant } from "motion-utils";
import { useContext, createContext } from "react";

const CarouselContext = /** @__PURE__ */ createContext(null);
function useCarousel() {
  const context = useContext(CarouselContext);
  invariant(
    Boolean(context),
    "useCarousel must be used within a Carousel component",
  );
  return context;
}

export { CarouselContext, useCarousel };
