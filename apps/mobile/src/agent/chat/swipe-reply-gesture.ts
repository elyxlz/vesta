// Pure math for swipe-to-reply on a chat row. Every function is a worklet so the pan handler runs
// it on the UI thread; in node the directive is inert and the suite exercises the same code.

// How far the row must travel right before release arms a reply.
export const SWIPE_REPLY_TRIGGER_PX = 64;
// Past the trigger the row follows the finger at this fraction, so it stops short of the screen edge.
const SWIPE_REPLY_RESISTANCE = 0.25;

export function swipeReplyOffset(translationX: number): number {
  "worklet";
  if (translationX <= 0) return 0;
  if (translationX <= SWIPE_REPLY_TRIGGER_PX) return translationX;
  return (
    SWIPE_REPLY_TRIGGER_PX +
    (translationX - SWIPE_REPLY_TRIGGER_PX) * SWIPE_REPLY_RESISTANCE
  );
}

export function swipeReplyArmed(offset: number): boolean {
  "worklet";
  return offset >= SWIPE_REPLY_TRIGGER_PX;
}

export function swipeReplyProgress(offset: number): number {
  "worklet";
  return Math.min(1, offset / SWIPE_REPLY_TRIGGER_PX);
}
