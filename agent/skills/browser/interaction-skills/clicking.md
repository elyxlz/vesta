# When a click does nothing

Two causes account for most of it, and each is one call to diagnose. Check them before any theory
about validation, stale refs, or anti-bot.

## 1. A JS click carries no user activation, so gated actions silently do nothing

`element.click()` from `browser js` dispatches an **untrusted** event: `isTrusted === false`, and it
grants no user activation. Firefox refuses anything gated on a real gesture, and refuses it
**silently**, with no error in the console you are reading.

Gated on user activation, therefore broken by a JS click:

- `window.open` and any `target="_blank"` navigation (**popup blocker**)
- clipboard writes, fullscreen requests, file pickers, notification and media permission prompts

`browser click <ref>` and `browser click --at X Y` go through `input.performActions`, which is real
input from the browser's point of view. They work.

**The tell**: a new tab appears and stays `about:blank` forever, or no tab appears at all, while the
click "succeeds" and the DOM says nothing is wrong. Hooking `window.open`, polling tabs, injecting
`<base target="_self">` and restarting the browser are all wasted on this, because the site is not
fighting automation and the popup blocker is not aimed at you. The click is fake.

A JS click is still fine, often preferable, for ordinary in-page handlers (dropdown options, list
items, accept buttons). React and friends do not care about `isTrusted`. Reach for a real click when
the action **navigates, opens, uploads, or writes outside the page**.

Note that a JS click failing does not by itself mean user activation: a site may also swallow a
synthetic event in its own framework handler, or want a full pointer/mouse chain rather than a bare
`click`. See `domain-skills/github/repo-actions.md` and `domain-skills/framer/editor.md` for those.
A real click fixes all three, which is why it is the right first move rather than the diagnosis.

## 2. An overlay intercepting the click

`browser click <ref>` checks this for you. When something else is topmost at the point it clicks,
it says so and names it:

```
# e14 is covered by <div.modal-wrap>, which took the click instead.
```

The click is still dispatched, because taking it is sometimes what you want; the line tells you
where it went. When you see it, dismiss the overlay (below) and click again. Nothing else is worth
trying first: every retry, every coordinate fallback and every theory about validation is wasted
while something is on top.

A modal can be invisible in `innerText` because it renders above the fold, and still sit over an
enabled button that reports `disabled=false` with no validation error, no unticked checkbox and no
missing required field. Upsell and confirmation dialogs on checkout flows do this repeatedly within
one flow, so read the line each time rather than assuming one page has one modal.

**`--at X Y` does not report this**, because there is no ref to compare against; a coordinate click
lands on whatever is topmost exactly as a ref click does, so it is not a way around an overlay
either. To check a point by hand, or to check a button you have not clicked yet:

```js
(() => { const b = /* the button */; const r = b.getBoundingClientRect();
         const hit = document.elementFromPoint(r.x + r.width/2, r.y + r.height/2);
         return hit === b || b.contains(hit) ? 'clear' : hit.tagName + '.' + hit.className; })()
```

A button that does nothing with no such line is a different problem: go to the field-hunting
checklist in SKILL.md's stuck-form paragraph, which is good advice for a form that rejects you and
useless for a form you are not reaching.

### Dismissing the overlay once you have found it

`dialogs.md` covers NATIVE prompts (`alert`, `confirm`, `beforeunload`) via
`browsingContext.handleUserPrompt`. It will not touch a React modal, which is just a div. What works:

```js
// find the modal's own control by its exact label, take the LAST match (modals mount late,
// so earlier matches are usually the page underneath), then real-click its rect centre
(() => { const m = document.querySelector('.modal-wrap') || document;
         const els = [...m.querySelectorAll('button,div,span,a')]
           .filter(e => e.offsetParent !== null && /^Continue$/i.test((e.innerText||'').trim()));
         const r = els[els.length-1].getBoundingClientRect();
         return Math.round(r.x+r.width/2) + ' ' + Math.round(r.y+r.height/2); })()
```

then `browser click --at <x> <y>`. Two traps: the control is often a `div`, not a `button`, so query
broadly and filter on exact text; and it may sit BELOW the fold, where a click lands on nothing.
`scrollIntoView({block:'center'})` first, then re-read the rect, because the coordinates move.

Order that works:

1. Did `browser click <ref>` report a cover? Dismiss it (above), then click again.
2. Does the action need a real gesture (opens, uploads, navigates)? Use `browser click`, not JS.
3. Only then consider stale rects, shadow DOM, cross-origin iframes, or a genuine validation error.
