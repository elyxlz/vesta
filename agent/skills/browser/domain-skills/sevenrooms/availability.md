# SevenRooms availability (sevenrooms.com)

The SevenRooms booking widget answers plain `curl` with a normal desktop UA, so never open a
browser to check a table. Take the venue slug from the restaurant's booking link.

```bash
curl "https://www.sevenrooms.com/api-yoa/availability/widget/range?venue=<slug>&time_slot=HH%3AMM&party_size=N&halo_size_interval=64&start_date=MM-DD-YYYY&num_days=1&channel=SEVENROOMS_WIDGET"
```

- `num_days` greater than 1 returns HTTP 400 `invalid num_days`, so query one day at a time.
- **A bad venue slug returns HTTP 400.** So a 200 with an empty availability list is a real
  answer, not a typo signal: the venue exists and that day has nothing bookable.
- A **closed day returns an empty availability list** while an open day returns 40+ slots. That is
  how to establish opening days from the venue's own system rather than from opening hours in a
  search result, which are frequently stale.
- **Every slot carries a `type`, and for a large party that field is the whole answer.** `book`
  means instantly confirmable, `request` means a human must convert it. Hold the date fixed and
  vary `party_size`: if a small party gets `['book','request']` while yours gets `['request']`
  only, that party size cannot be confirmed online at all. A venue's "we are able to accommodate
  you" is the wording an unconverted request produces, and it is not a held table.
