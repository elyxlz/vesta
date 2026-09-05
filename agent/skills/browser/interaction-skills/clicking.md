# When a click does nothing

Two causes account for most of it, and each is one call to diagnose. Check them before any theory
about validation, timing, or anti-bot.

## 1. A JS click carries no user activation, so gated actions silently do nothing

`element.click()` from `js(...)` dispatches an **untrusted** event: `isTrusted === false`, and it
grants no user activation. The browser refuses anything gated on a real gesture, and refuses it
**silently**, with no error in the console you are reading.

Gated on user activation, therefore broken by a JS click:

- `window.open` and any `target="_blank"` navigation (**popup blocker**)
- clipboard writes, fullscreen requests, file pickers, notification and media permission prompts

`click_at_xy(x, y)` dispatches real input from the browser's point of view. It works.

**The tell**: a new tab appears and stays `about:blank` forever, or no tab appears at all, while the
click "succeeds" and the DOM says nothing is wrong. Hooking `window.open`, polling tabs, injecting
`<base target="_self">` and restarting the browser are all wasted on this, because the site is not
fighting automation and the popup blocker is not aimed at you. The click is fake.

A JS click is still fine, often preferable, for ordinary in-page handlers (dropdown options, list
items, accept buttons). React and friends do not care about `isTrusted`. Reach for a real click when
the action **navigates, opens, uploads, or writes outside the page**.

A JS click that fails does not by itself prove user activation is the cause: a site may swallow a
synthetic event in its own framework handler, or want a full pointer chain rather than a bare
`click`. See `domain-skills/github/repo-actions.md` and `domain-skills/framer/editor.md` for those.
A real click fixes all three, which is why it is the right first move rather than the diagnosis.

## 2. An overlay intercepting the click

A click lands on whatever is topmost at that point, so an invisible overlay takes it and the button
underneath never fires. Ask the page which element owns the point before you click it:

```python
hit = js("""(() => { const b = document.querySelector('#submit');
         const r = b.getBoundingClientRect();
         const el = document.elementFromPoint(r.x + r.width/2, r.y + r.height/2);
         return el === b || b.contains(el) ? 'clear' : el.tagName + '.' + el.className; })()""")
print(hit)
```

Anything but `clear` names the interceptor. Dismiss it (below) and click again. Nothing else is
worth trying while something is on top: every retry, every coordinate fallback and every theory
about validation is wasted.

A modal can be invisible in `innerText` because it renders above the fold, and still sit over an
enabled button that reports `disabled=false` with no validation error, no unticked checkbox and no
missing required field. Upsell and confirmation dialogs on checkout flows do this repeatedly within
one flow, so re-read the point each time rather than assuming one page has one modal.

### Dismissing the overlay once you have found it

`dialogs.md` covers NATIVE prompts (`alert`, `confirm`, `beforeunload`). Those need the engine's own
call. A React modal is just a div, and this is what works:

```python
# find the modal's own control by its exact label, take the LAST match (modals mount late,
# so earlier matches are usually the page underneath), then real-click its rect centre
point = js("""(() => { const m = document.querySelector('.modal-wrap') || document;
         const els = [...m.querySelectorAll('button,div,span,a')]
           .filter(e => e.offsetParent !== null && /^Continue$/i.test((e.innerText||'').trim()));
         const r = els[els.length-1].getBoundingClientRect();
         return {x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)}; })()""")
click_at_xy(point["x"], point["y"])
```

Two traps: the control is often a `div`, not a `button`, so query broadly and filter on exact text;
and it may sit BELOW the fold, where a click lands on nothing. `scrollIntoView({block:'center'})`
first, then re-read the rect, because the coordinates move.

Order that works:

1. Does `elementFromPoint` name a cover? Dismiss it (above), then click again.
2. Does the action need a real gesture (opens, uploads, navigates)? Use `click_at_xy`, not JS.
3. Only then consider stale rects, shadow DOM, cross-origin iframes, or a genuine validation error.
