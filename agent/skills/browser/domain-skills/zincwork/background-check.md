# Zinc (zincwork.com): driving a candidate background check

Field-tested against `app.zincwork.com` on 2026-07-30 and 2026-07-31 across several passes. Zinc is
a UK background-screening provider; a candidate gets a `request-check` link from a recruiter and
fills five gated sections. Every quirk below cost a previous run real time.

## Read the state from the API before touching the UI

This is the single biggest lesson. The SPA's own backend returns the entire persisted check in one
call, which is better evidence than any screenshot and instantly tells you what is already done:

```
GET https://api.zincwork.com/recruitment/request/<request-id>
Authorization: Bearer <localStorage['zinc.accessToken']>
```

Returns `dateOfBirth`, `nameHistory`, `addressHistory`, `currentAddress`, per-check `status` and
`result`, the check criteria, `applicantReady` and `status`. `GET /user` is the user-level mirror.

- The token is **short-lived (~2h) and rotates**. Re-read it from localStorage immediately before
  each call. A **703 `E_INVALID_TOKEN` means stale token**; a **404 means wrong route**. Do not
  confuse the two.
- A brief handed to you can be stale. On 31 Jul a run was dispatched to fill "Confirm your details"
  and found it already complete and server-persisted. Check first, or you risk clobbering correct
  data by re-entering a finished KYC step.

## Page structure

Each check is a **separate top-level Nuxt route**, not a modal:

| Section | Route |
|---|---|
| Confirm your details | `/request-check-confirm-details/<id>/details` |
| Address check | `/request-address-check/<id>/proof` |
| References (employment) | `/request-employment-verification/<id>/instant-verification-questions` |
| Identity check | `/request-id-check/<id>/rtw-nationality-selection` |
| Criminal record check | `/request-criminal-check/<id>/...` |

Navigating to a **completed** flow's route silently redirects back to `/request-check/<id>/details`.
That is a free, non-destructive completeness test.

## Finding elements

- **The section cards are `<div role="button">`, not `<button>`.** `querySelectorAll('button')`
  returns only the Fini chat widget. Query by `[data-testid]` instead: `address-check`,
  `confirm-your-details`, `reference-check`, `identity-check`, `criminal-check`.
- Card state reads off the class: `stone-outline-card` = completed, `pointer-events-none opacity-60`
  = locked, `custom-outline-card cursor-pointer` = actionable.
- The page is SSR'd but **card content hydrates late**. Snapshot too early and you see only the
  heading, which makes a populated page look empty. Allow a 4-6s settle.
- Section order on the landing page is not stable between visits. Do not address cards by position.

## Form quirks that break naive automation

- **"Next" needs TWO clicks**: the first validates, the second advances. Reproduced on every pass.
  This is not a broken button and not anti-bot.
- **A stuck Next is a validation error.** Screenshot and grep the DOM for an empty `[required]`
  field or an error node before concluding anything about bot detection.
- **DOB renders as "required" in red even when visibly prefilled.** Re-enter it.
- **DOB boxes are segmented and mishandle bulk keystrokes.** Backspace on an empty box jumps to the
  PREVIOUS box and eats its value. Reliable method: click a box, press End, press Backspace exactly
  `len(value)` times, then type. With all three boxes empty, typing the digits straight through
  (`DDMMYYYY`) auto-advances correctly.
- **The phone country selector defaults to a UK flag** regardless of the number. Pick the country
  explicitly.
- **Address history takes MM/YYYY only.** The current address's end date is auto-filled and
  disabled, so no fixed end date is ever asserted and the tenancy-type questions never appear.
- Address coverage is checked against a rolling 5 years from today. Short coverage shows as
  "You have N years and M months from K address(es)" **with no Next button at all**, only "Add
  another address". Read that string rather than assuming the button failed to render.
- Zinc canonicalises addresses through a postcode lookup, so what persists may not be the string you
  typed: a flat-and-street form can come back with the building name Royal Mail holds for that
  postcode. Same address, so do not "fix" it.
- **Never click "Submit checks"** on the profile panel while sections are incomplete: it submits the
  check as-is.

## What the sections actually want

- **Confirm your details** persists NOTHING until the whole flow completes. Reloading mid-way loses
  everything except DOB, which comes from the account profile. Do it in one unbroken sitting, and do
  not start without every field in hand.
- **References is not referee names.** It is HMRC employment verification, opening on "Do you have a
  Government Gateway ID?" Yes/No, with an "I cannot get a Government Gateway ID" link as the manual
  fallback. The criteria object states the months to cover and the minimum months per role, and the
  API pre-computes detected employment gaps, which are worth reading before starting.
- **Identity check opens on a citizenship combobox** for right to work, then a document scan and
  selfie through Onfido. The Onfido SDK loads into the profile early.
- **Criminal record check is gated behind identity** and its payload wants a mobile number, which is
  why the number may be absent from the details payload.

## The real automation boundary

Everything up to and including form-fill, address history and account state automates cleanly. The
durable handoff points are the two Onfido steps: **proof-of-address document upload** and
**passport scan + selfie**. Those need a real camera and the physical document, so they belong on
the person's phone. An address check that has already run can sit in `pending-resubmission` with
`matches: 0` while the UI only says "Upload proof of address", so read `result` and
`submissionAttempts` from the API to know whether it failed rather than never ran.

## Session

Profile `~/.browser/zinc`; the session persisted across days with no 2FA. `browsingContext.create`
has timed out at 60s; driving the existing context with `navigate` + `wait:"interactive"` worked
every time.
