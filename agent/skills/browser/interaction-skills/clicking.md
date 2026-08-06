# When a click does nothing

The most-used mechanic in this skill had no page of its own until 6 Aug 2026, which is why the same
root cause is recorded three separate times in domain files and never once named:
`domain-skills/tiktok/upload.md:104` ("JS `.click()` doesn't work on TikTok's time picker items"),
`domain-skills/github/repo-actions.md:35` ("Synthetic `.click()` does not persist the star"),
`domain-skills/framer/editor.md:30` ("A plain `element.click()` is not enough"). Three agents hit one
bug, wrote three site-specific workarounds, and none of them generalised it.

## 1. A JS click carries no user activation, so gated actions silently do nothing

`element.click()` from `browser js` dispatches an **untrusted** event: `isTrusted === false`, and it
grants no user activation. Firefox refuses anything gated on a real gesture, and refuses it
**silently**, with no error in the console you are reading.

Gated on user activation, therefore broken by a JS click:
- `window.open` and any `target="_blank"` navigation (**popup blocker**)
- clipboard writes, fullscreen requests, file pickers, notification and media permission prompts

`browser click <ref>` and `browser click --at X Y` go through `input.performActions`
(`cli/src/vesta_browser/helpers.py:211-215`), which is real input from the browser's point of view.
They work.

**The tell**: a new tab appears and stays `about:blank` forever, or no tab appears at all, while the
click "succeeds" and the DOM says nothing is wrong. Burned 6 Aug 2026 on a trip.com flight checkout:
~40 minutes of hooking `window.open`, polling tabs, injecting `<base target="_self">` and restarting
the browser, all to work around a popup blocker that a real click never triggers. The site was never
fighting automation. The click was fake.

Corollary worth keeping straight: a JS click is still fine, often preferable, for ordinary in-page
handlers (dropdown options, list items, accept buttons). React and friends do not care about
`isTrusted`. Reach for a real click when the action **navigates, opens, uploads, or writes outside
the page**.

## 2. If a button does nothing, ask what is actually under the cursor

```js
(() => { const b = /* the button */; const r = b.getBoundingClientRect();
         const hit = document.elementFromPoint(r.x + r.width/2, r.y + r.height/2);
         return hit === b || b.contains(hit) ? 'clear' : hit.tagName + '.' + hit.className; })()
```

One call. If the answer is not your button, you are clicking an overlay and every retry, every
coordinate fallback and every theory about validation is wasted.

Burned the same day: a "Next" button on trip.com read `disabled=false`, had no validation errors, no
unticked checkbox and no missing required field, and did nothing for ~20 minutes. `elementFromPoint`
named the cause immediately: a `.ift-modal-wrap` **"Duplicate Bookings"** dialog, invisible in
`innerText` because it rendered above the fold, sitting over the button. The same trap appeared twice
more in the same flow (a baggage upsell, then an insurance upsell), and each time the one-call check
found it in seconds.

Run this check **before** the field-hunting checklist in SKILL.md's stuck-form paragraph. That
checklist is good advice for a form that rejects you, and useless for a form you are not reaching.

## 3. Ref clicks, coordinate clicks and overlays

`interaction-skills/authed-onboarding-forms.md` suggests falling back to a coordinate click when a
ref click no-ops. That helps for stale geometry, and **does not help here**: a coordinate click lands
on the overlay just as a ref click does. Diagnose first, then choose the fallback.

### Dismissing the overlay once you have found it

`dialogs.md` covers NATIVE prompts (`alert`, `confirm`, `beforeunload`) via
`browsingContext.handleUserPrompt`. It will not touch a React modal, which is just a div. What works:

```js
// find the modal's own control by its exact label, take the LAST match (modals mount late,
// so earlier matches are usually the page underneath), then real-click its rect centre
(() => { const m = document.querySelector('.ift-modal-wrap') || document;
         const els = [...m.querySelectorAll('button,div,span,a')]
           .filter(e => e.offsetParent !== null && /^Continue booking$/i.test((e.innerText||'').trim()));
         const r = els[els.length-1].getBoundingClientRect();
         return Math.round(r.x+r.width/2) + ' ' + Math.round(r.y+r.height/2); })()
```

then `browser click --at <x> <y>`. Two traps, both hit on 6 Aug: the control is often a `div`, not a
`button`, so query broadly and filter on exact text; and it may sit BELOW the fold, where a click
lands on nothing. `scrollIntoView({block:'center'})` first, then re-read the rect, because the
coordinates move.

Order that actually works:
1. `elementFromPoint` on the target's centre. Overlay? Dismiss it (above), then click.
2. Does the action need a real gesture (opens, uploads, navigates)? Use `browser click`, not JS.
3. Only then consider stale rects, shadow DOM, cross-origin iframes, or a genuine validation error.
