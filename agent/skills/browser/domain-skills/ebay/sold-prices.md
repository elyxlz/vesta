# eBay UK: sold / completed listings

- `LH_Sold=1&LH_Complete=1` search URLs redirect to signin.ebay.co.uk when not signed in (observed Nov 2026), so sold prices are not readable anonymously. Plain WebFetch of ebay.co.uk returns 403.
- Active listings ARE readable signed-out: `https://www.ebay.co.uk/sch/i.html?_nkw=<query>&LH_ItemCondition=3000&_ipg=60` (3000 = used). Results are `li.s-item, li.s-card`; read each `innerText`. Those are asking prices, label them so.
- For a used-price estimate without sign-in, HifiShark (`hifishark.com/model/<brand>-<model>`) shows an estimated median from listings plus recent listing prices across eBay and classifieds; it renders in the browser.
