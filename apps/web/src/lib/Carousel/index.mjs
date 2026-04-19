"use client";
import { jsx } from "react/jsx-runtime";
import { wheel } from "motion-plus-dom";
import {
  useMotionValue,
  useTransform,
  useMotionValueEvent,
  JSAnimation,
  clamp,
  animate,
} from "motion/react";
import { useRef, useState, useEffect } from "react";
import { Ticker } from "../Ticker/index.mjs";
import { useTicker } from "../Ticker/context.mjs";
import { getLayoutStrategy } from "../Ticker/utils/layout-strategy.mjs";
import { CarouselContext } from "./context.mjs";
import { calcCurrentPage } from "./utils/calc-current-page.mjs";
import { calcPageInsets } from "./utils/calc-page-insets.mjs";
import { findNextPageInset } from "./utils/find-next-page.mjs";
import { findPrevPageInset } from "./utils/find-prev-page.mjs";

function CarouselView({
  children,
  offset,
  targetOffset,
  tugOffset,
  loop = true,
  transition,
  tickerRef,
  axis = "x",
  snap = "page",
}) {
  /**
   * When this boolean is true, the rendered offset will be "attached" to
   * the target offset, allowing for direct manipulation. When it's false,
   * we're animating the offset to the target offset. This allows things
   * like pagination and pagination progress to be optionally coupled to
   * the target offset.
   */
  const isOffsetAttachedToTarget = useRef(true);
  /**
   * Calculate pagination and inset limits based on the measured
   * ticker and item dimensions.
   */
  const {
    clampOffset,
    totalItemLength,
    itemPositions,
    containerLength,
    gap,
    maxInset,
    direction,
  } = useTicker();
  const wrapInset = totalItemLength + gap;
  const pagination =
    snap === "item"
      ? {
          insets: itemPositions.map((p) => p.start),
          visibleLength: containerLength,
        }
      : calcPageInsets(itemPositions, containerLength, maxInset);
  const totalPages = pagination.insets.length;
  const { sign } = getLayoutStrategy(axis, direction);
  /**
   * Helper function to calculate pagination state based on target offset
   */
  const calculatePaginationState = (targetOffsetValue) => {
    const current = calcCurrentPage(
      targetOffsetValue * sign,
      pagination.insets,
      wrapInset,
      maxInset,
    );
    const isNextActive = loop ? true : targetOffsetValue * -sign < maxInset;
    const isPrevActive = loop ? true : targetOffsetValue * -sign > 0;
    return { current, isNextActive, isPrevActive };
  };
  // Initialize pagination state with current target offset
  const [paginationState, setPaginationState] = useState(() =>
    calculatePaginationState(targetOffset.get()),
  );
  // Update the pagination state when the measured ticker dimensions change
  useEffect(() => {
    updatePaginationState();
  }, [containerLength, totalItemLength]);
  const updatePaginationState = () => {
    /**
     * We derive the current page from the target offset, not the currently-rendered
     * offset. This ensures that if we're paginating discretely, the page indicator
     * updates immediately, and if we're jumping many pages that any indicator like a dots
     * indicator doesn't appear to animate through many dots as the carousel animates.
     */
    const newPaginationState = calculatePaginationState(targetOffset.get());
    // Only update state if something has changed
    if (
      newPaginationState.current !== paginationState.current ||
      newPaginationState.isNextActive !== paginationState.isNextActive ||
      newPaginationState.isPrevActive !== paginationState.isPrevActive
    ) {
      setPaginationState(newPaginationState);
    }
  };
  /**
   * Handle changes to the target offset.
   * - Update the rendered offset.
   * - Update pagination state.
   */
  useMotionValueEvent(targetOffset, "change", (latest) => {
    offset.set(latest);
    updatePaginationState();
  });
  /**
   * Attach the rendered offset to the target offset.
   */
  const currentAnimation = useRef(null);
  const stopOffsetAnimation = () => {
    if (!currentAnimation.current) return;
    currentAnimation.current.stop();
    currentAnimation.current = null;
  };
  /**
   * Add a custom handler to the offset motion value. We link offset to targetOffset
   * and only update targetOffset from pagination/gestures. When offset is attached
   * to targetOffset, changes are passed straight through to offset. When it's not
   * attached, we animate offset to the latest targetOffset value.
   */
  useEffect(() => {
    offset.attach((v, onUpdate) => {
      stopOffsetAnimation();
      if (isOffsetAttachedToTarget.current) {
        onUpdate(v);
      } else {
        currentAnimation.current = new JSAnimation({
          keyframes: [offset.get(), v],
          velocity: clamp(-2e3, 2000, offset.getVelocity()),
          ...transition,
          onUpdate,
          onComplete: () => {
            currentAnimation.current = null;
          },
        });
      }
      isOffsetAttachedToTarget.current = true;
    }, stopOffsetAnimation);
  }, []);
  /**
   * Discrete pagination. Support (and pass via context) next/prev/goto
   * functions.
   */
  const stepOffset = (newOffset) => {
    const clampedOffset = clampOffset(newOffset);
    targetOffset.stop();
    isOffsetAttachedToTarget.current = false;
    targetOffset.set(clampedOffset * sign);
  };
  const paginate = (findPageInset, direction) => {
    const offset = -findPageInset(
      -targetOffset.get() * sign,
      pagination.visibleLength,
      itemPositions,
      gap,
    );
    const clamped = clampOffset(offset);
    if (clamped * sign === targetOffset.get()) {
      animate(tugOffset, 0, {
        velocity: direction * sign * 400,
        ...limitSpring,
      });
    } else {
      stepOffset(clamped);
    }
  };
  const nextPage = () => {
    if (snap === "item") {
      const next = Math.min(paginationState.current + 1, totalPages - 1);
      if (next !== paginationState.current) gotoPage(next);
      return;
    }
    paginate(findNextPageInset, -1);
  };
  const prevPage = () => {
    if (snap === "item") {
      const prev = Math.max(paginationState.current - 1, 0);
      if (prev !== paginationState.current) gotoPage(prev);
      return;
    }
    paginate(findPrevPageInset, 1);
  };
  const gotoPage = (i) => {
    const iteration = loop
      ? Math.floor((-targetOffset.get() * sign) / wrapInset)
      : 0;
    const transformOffset = iteration * -wrapInset;
    stepOffset(-pagination.insets[i] + transformOffset);
  };
  const snapToNearest = () => {
    const current = -targetOffset.get() * sign;
    let closestInset = pagination.insets[0];
    let closestDist = Math.abs(current - closestInset);
    for (let i = 1; i < pagination.insets.length; i++) {
      const dist = Math.abs(current - pagination.insets[i]);
      if (dist < closestDist) {
        closestDist = dist;
        closestInset = pagination.insets[i];
      }
    }
    stepOffset(-closestInset);
  };
  const wheelCallbacks = useRef({
    snapToNearest,
    maxInset,
  });
  useEffect(() => {
    wheelCallbacks.current = {
      snapToNearest,
      maxInset,
    };
  }, [snapToNearest, maxInset]);
  useEffect(() => {
    const element = tickerRef.current;
    if (!element) return;
    let snapTimeoutId = null;
    const wheelCleanup = wheel(element, {
      axis,
      onWheel: (delta) => {
        const { maxInset: mi } = wheelCallbacks.current;
        let newOffset = offset.get() + delta;
        if (mi !== null) newOffset = clamp(-mi, 0, newOffset);
        targetOffset.jump(newOffset);
        if (snap) {
          if (snapTimeoutId) clearTimeout(snapTimeoutId);
          snapTimeoutId = setTimeout(() => {
            wheelCallbacks.current.snapToNearest();
            snapTimeoutId = null;
          }, 150);
        }
      },
    });
    return () => {
      if (snapTimeoutId) clearTimeout(snapTimeoutId);
      wheelCleanup();
    };
  }, [axis, snap, offset, sign]);
  return jsx(CarouselContext.Provider, {
    value: {
      currentPage: paginationState.current,
      isNextActive: paginationState.isNextActive,
      isPrevActive: paginationState.isPrevActive,
      totalPages,
      nextPage,
      prevPage,
      gotoPage,
      targetOffset,
    },
    children: children,
  });
}
function Carousel({
  children,
  loop = true,
  transition = defaultTransition,
  axis = "x",
  snap = "page",
  ...props
}) {
  const ref = useRef(null);
  const targetOffset = useMotionValue(0);
  const offset = useMotionValue(0);
  const tugOffset = useMotionValue(0);
  const renderedOffset = useTransform(() => tugOffset.get() + offset.get());
  return jsx(Ticker, {
    role: "region",
    "aria-roledescription": "carousel",
    offset: renderedOffset,
    loop: loop,
    ref: ref,
    axis: axis,
    drag: axis,
    _dragX: axis === "x" ? targetOffset : false,
    _dragY: axis === "y" ? targetOffset : false,
    snap: snap,
    pageTransition: transition,
    ...props,
    children: jsx(CarouselView, {
      tickerRef: ref,
      loop: loop,
      offset: offset,
      tugOffset: tugOffset,
      targetOffset: targetOffset,
      transition: transition,
      snap: snap,
      axis: axis,
      children: children,
    }),
  });
}
const defaultTransition = {
  type: "spring",
  stiffness: 200,
  damping: 40,
};
const limitSpring = {
  type: "spring",
  stiffness: 80,
  damping: 10,
};

export { Carousel };
