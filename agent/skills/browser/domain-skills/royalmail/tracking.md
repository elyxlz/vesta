# Royal Mail tracking (royalmail.com/track-your-item)

- Use a standard Chromium session. A session that has never opened royalmail.com does not render
  results from a cold deep link: it loads the tracking SPA but resets to the empty "Your reference
  number" form.
- First visit (observed in a fresh Chromium profile, one run each way): open
  `https://www.royalmail.com/track-your-item`, wait about 8 seconds, click the "Accept all" consent
  button (find it by its text), wait a few seconds, then load the deep link below. The same fresh
  profile sent straight to the deep link, with consent accepted there, showed only the empty form.
  The cookies persist in the profile, so later visits can go straight to the deep link.
- Deep link: `https://www.royalmail.com/track-your-item#/tracking-results/<TRACKING_NUMBER>`. If
  the consent banner shows, click "Accept all", then wait about 15 seconds before reading
  `document.body.innerText`.
- The status block sits just above "Tracking number:". It starts with a state word (e.g.
  "Pending", "Delivered") and the latest event text.
- "Get more details" does not reliably expand the history; the top status line is the dependable
  read.
- Royal Mail's own emails (no-reply@royalmail.com: "due to be delivered today", "delivery update")
  arrive for some events but not all, so a quiet inbox does not mean nothing happened.
- "Unable to deliver ... address was inaccessible" is the carrier's code for access problems
  (locked communal entrance etc.); recipients have reported it logged with no knock or ring, so ask
  the recipient before treating it as fact.
