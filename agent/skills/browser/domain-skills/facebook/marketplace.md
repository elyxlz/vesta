# Facebook Marketplace: listing an item and watching it

Field-tested on facebook.com (UK, Sep 2026) in a signed-in chromium session.

## Privacy first

The account you drive may belong to someone other than the person you work for (a partner's
account used to sell a shared item). Treat everything outside the listing flow as private:

- `https://www.facebook.com/messages/...` opens the account holder's PERSONAL Messenger: the chat
  list, and often a private conversation auto-opens. Never navigate there to look for buyers.
- `https://www.facebook.com/marketplace/inbox/` and `/messages/marketplace/` return "This content
  isn't available at the moment" (dead routes). `messenger.com` needs its own login.
- To watch a listing, read only the selling page (below). If buyer messages need reading, ask
  first, then open only the Marketplace buyer threads for that listing.

## Creating a listing

`https://www.facebook.com/marketplace/create/item`. The form has: photos (a file input; set files
with `upload_file(selector, path)`), Title, Price (currency follows the account), Category,
Condition, then "More details": Colour, Description, Availability, Product tags (up to 20), SKU
(seller-only), Location (pick from the suggestion list until a green tick shows), and Meetup
preferences.

- The meetup checkboxes ("Public meetup", "Door pick-up", "Door drop-off") are not
  `input[type=checkbox]`, so a query for those returns nothing; click the square with a real
  coordinate click and verify with a screenshot.
- A small viewport hides most of the form; enlarge it with CDP
  `Emulation.setDeviceMetricsOverride` (e.g. 1600x1400) before screenshots.
- "Next" leads to the audience step ("List publicly", "List in your groups"), then "Publish".
  Nothing is public until "Publish" is clicked, so stop before it until the user approves.

## Watching the listing

`https://www.facebook.com/marketplace/you/selling` shows each listing card with status ("Active",
"This listing is being reviewed" right after publishing), "N clicks on listing", and actions. A
card with no message indicator is not proof there are no buyer messages; say so rather than
reporting "no buyers".
