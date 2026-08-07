# CoverManager availability (covermanager.com)

The CoverManager booking module answers plain `curl` with a normal desktop UA, so never open a
browser to check a table. Fetch
`https://www.covermanager.com/reservation/module_restaurant/<slug>/english` and read the widget's
own config variables rather than inferring behaviour by clicking through:

- `max_people`: the online booking ceiling.
- `groupRequestHoldOnCard` and `groupRequestCancelPolicy`: both `0` means no card hold and no
  cancellation charge, so a backup booking costs nothing to drop.

**The trap: a wrong slug returns HTTP 200 with a plausible sentence**, e.g. "The booking module is
temporarily disabled". That reads as "this venue is unavailable" when it is really a typo, and a
truncated slug is easy to produce when scraping one out of a restaurant's own site. Check the
response size: a real module is ~136KB while the bad-slug reply is ~42 bytes. A 200 with prose in
it is not proof the request was understood.
