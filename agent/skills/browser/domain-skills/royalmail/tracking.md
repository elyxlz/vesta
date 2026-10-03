# Royal Mail tracking (royalmail.com/track-your-item)

- Use a standard Chromium session that has visited the site before (cookies kept). A fresh or stealth session loads the tracking SPA but resets to the empty "Your reference number" form, so the result never renders.
- Navigate straight to `https://www.royalmail.com/track-your-item#/tracking-results/<TRACKING_NUMBER>`, click the "Accept all" consent button (find it by its text), then wait about 15 seconds before reading `document.body.innerText`.
- The status block sits just above "Tracking number:". It starts with a state word (e.g. "Pending", "Delivered") and the latest event text.
- "Get more details" does not reliably expand the history; the top status line is the dependable read.
- Royal Mail's own emails (no-reply@royalmail.com: "due to be delivered today", "delivery update") arrive for some events but not all, so a quiet inbox does not mean nothing happened.
- "Unable to deliver ... address was inaccessible" is the carrier's code for access problems (locked communal entrance etc.); recipients have reported it logged with no knock or ring, so ask the recipient before treating it as fact.
