# 1Password share links (share.1password.com), reading a shared credential

Field-tested 2026-08-30. A 1Password one-time **share link** (`https://share.1password.com/s#<fragment>`)
is how a user hands you a single login/secret without pasting it in plaintext chat. The item is
decrypted client-side from the key in the URL `#fragment`, so it renders only in a real browser
(the page is a JS SPA; `http_get` returns a shell). The link is view-limited (expiry is printed on
the page, e.g. "You can view this item until <date>").

## The one non-obvious part: the password is not in the DOM

Visible fields (username, website, name) come out of `document.body.innerText` fine. The **password
renders as literal bullet characters** (`••••••••••`), NOT CSS-masked text, so its real value is
never in the visible DOM and there is no reveal toggle. The value is only handed to the OS clipboard
when you click its **Copy** button. And `navigator.clipboard.readText()` is blocked headless
("Clipboard read request was blocked due to lack of user activation").

**Solution, intercept the clipboard WRITE, then click Copy.** Override `writeText` to capture the
argument the page passes it:

```python
# after browser open "<share link>" and the page has rendered (~2s):
val = js(r"""
(async () => {
  window.__cap = null;
  navigator.clipboard.writeText = (t) => { window.__cap = t; return Promise.resolve(); };
  // copy buttons appear in field order: username, password, then any extra fields
  const btns = [...document.querySelectorAll('button')].filter(b => /copy/i.test(b.textContent||''));
  btns[1].click();                              // index 1 = password (0 = username)
  await new Promise(r => setTimeout(r, 400));
  return window.__cap;
})()
""")
```

`btns[1]` is the password on a standard Login item (username is `btns[0]`). Confirm the field order
from `innerText` first if the item has an unusual shape (e.g. an API-key item with no username).

## Rendering note

`browser open` on the share link may report `0 interactive refs` and no text on the first snapshot
(heavy SPA fires `load` late). Do not read that as a block: wait ~2s and read
`document.body.innerText` / run the JS above; the content is there.

## Security

The captured secret is a real user credential. Use it for the task at hand, never echo it back to
the user or into any visible surface, and let the nightly `dream` redaction scrub it from history.
Do not persist it to disk unless the user asked you to store it (then use the `1password` skill /
their vault, not a plaintext file).
