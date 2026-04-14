/// <reference types="vite/client" />

declare const __APP_VERSION__: string;

declare module "@/lib/Carousel/index.mjs" {
  import type { ComponentProps, ReactNode } from "react";
  import type { motion } from "motion/react";

  interface CarouselProps extends ComponentProps<typeof motion.div> {
    items: ReactNode[];
    axis?: "x" | "y";
    gap?: number;
    align?: "start" | "center" | "end";
    loop?: boolean;
    snap?: "page" | "item" | false;
    overflow?: boolean;
    itemSize?: "auto" | "fill";
    fade?: number | string;
    fadeTransition?: { duration: number; ease: string };
  }

  export function Carousel(props: CarouselProps): ReactNode;
}

declare module "@/lib/Ticker/use-ticker-item.mjs" {
  import type { MotionValue } from "motion/react";

  export function useTickerItem(): {
    start: number;
    end: number;
    offset: MotionValue<number>;
    projection: MotionValue<number>;
    itemIndex: number;
    cloneIndex?: number;
    props: Record<string, unknown>;
  };
}

declare module "@/lib/Carousel/context.mjs" {
  import type { MotionValue } from "motion/react";

  export function useCarousel(): {
    currentPage: number;
    totalPages: number;
    nextPage: () => void;
    prevPage: () => void;
    gotoPage: (index: number) => void;
    isNextActive: boolean;
    isPrevActive: boolean;
    targetOffset: MotionValue<number>;
  };
}
