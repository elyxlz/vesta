# Ashby job boards (jobs.ashbyhq.com)

Ashby career pages are SPAs, so `WebFetch` returns an empty shell with only the page title and a
live posting looks like it is gone. No browser is needed: Ashby publishes the whole board as a
public JSON API.

For a posting URL `jobs.ashbyhq.com/<company>/<id>`:

```bash
curl "https://api.ashbyhq.com/posting-api/job-board/<company>?includeCompensation=true"
```

Returns every live posting with `descriptionPlain` in full, plus compensation when the company
publishes it. Match on the posting id from the URL, or on the title. No auth. A bad company slug
returns an error rather than a plausible-looking empty board, so a failure is distinguishable from
a company with no openings.

A posting's `location` is only its PRIMARY city. Other cities the role is open to sit in
`secondaryLocations` (a list of `{location, address}`), so read both before saying where a role is
based or that it is not open in a given city; the posting page shows them joined
("New York City; London; San Francisco"). The same holds for the board-wide listing.
