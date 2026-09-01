import { useEffect, type RefObject } from "react";

// Past this much movement a press counts as a drag, so the trailing click is swallowed.
const DRAG_THRESHOLD_PX = 5;

// Mouse click-drag to scroll the carousel; touch already scrolls it natively, so this binds only for
// the mouse. It drives scrollLeft directly and reports the drag so the caller can drop scroll snapping
// for the duration (restored on release to settle on the nearest card), and it swallows the click that
// ends a real drag so releasing never opens the card underneath.
export function useDragScroll(
  ref: RefObject<HTMLElement | null>,
  onDraggingChange: (dragging: boolean) => void,
): void {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let active = false;
    let moved = false;
    let startX = 0;
    let startScroll = 0;

    const onPointerDown = (event: PointerEvent) => {
      if (event.pointerType !== "mouse" || event.button !== 0) return;
      active = true;
      moved = false;
      startX = event.clientX;
      startScroll = el.scrollLeft;
      el.setPointerCapture(event.pointerId);
      onDraggingChange(true);
    };
    const onPointerMove = (event: PointerEvent) => {
      if (!active) return;
      const dx = event.clientX - startX;
      if (Math.abs(dx) > DRAG_THRESHOLD_PX) moved = true;
      el.scrollLeft = startScroll - dx;
    };
    const stop = (event: PointerEvent) => {
      if (!active) return;
      active = false;
      if (el.hasPointerCapture(event.pointerId))
        el.releasePointerCapture(event.pointerId);
      onDraggingChange(false);
    };
    const onClickCapture = (event: MouseEvent) => {
      if (!moved) return;
      moved = false;
      event.preventDefault();
      event.stopPropagation();
    };
    // A drag over a card image/link would otherwise start a native drag-and-drop ghost.
    const onDragStart = (event: Event) => {
      if (active) event.preventDefault();
    };

    el.addEventListener("pointerdown", onPointerDown);
    el.addEventListener("pointermove", onPointerMove);
    el.addEventListener("pointerup", stop);
    el.addEventListener("pointercancel", stop);
    el.addEventListener("click", onClickCapture, { capture: true });
    el.addEventListener("dragstart", onDragStart);
    return () => {
      el.removeEventListener("pointerdown", onPointerDown);
      el.removeEventListener("pointermove", onPointerMove);
      el.removeEventListener("pointerup", stop);
      el.removeEventListener("pointercancel", stop);
      el.removeEventListener("click", onClickCapture, { capture: true });
      el.removeEventListener("dragstart", onDragStart);
    };
  }, [ref, onDraggingChange]);
}
