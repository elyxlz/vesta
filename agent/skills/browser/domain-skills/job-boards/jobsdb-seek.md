---
hosts: jobsdb.com, jobstreet.com, seek.com.au, seek.co.nz
---

# Job Boards: JobsDB (and the SEEK family)

Covers: `hk.jobsdb.com`, `th.jobsdb.com`, `id.jobstreet.com`, `my.jobstreet.com`, `seek.com.au`, `seek.co.nz`

JobsDB, JobStreet and SEEK are one platform behind different domains, so they share a URL grammar
and DOM contract. Learn it once, reuse it across all six.

Verified against `hk.jobsdb.com` on 17 Jul 2026.

---

## Stealth is required, and it is sufficient

`curl` gets **403** on `hk.jobsdb.com` regardless of User-Agent. Camoufox gets **200** first try,
no CAPTCHA and no handover. So: don't waste a turn on `http_get`, and don't conclude the market is
empty because a curl-based scan came back dry. Launch the browser.

```bash
browser launch
```

---

## Do this first: construct search URLs directly

Never type into the site's search box, that is what trips detection. Build the URL and navigate.

```python
from urllib.parse import quote_plus

# Keyword search. Note: /jobs?keywords=... 302s to a slug like /business-development-jobs
goto("https://hk.jobsdb.com/jobs?keywords=" + quote_plus("business development"))
wait_for_load(); wait(2)
```

### URL grammar

| Goal | Pattern |
|---|---|
| Keyword search | `/jobs?keywords=business+development` (302s to `/business-development-jobs`) |
| Recency filter | `&daterange=1` \| `3` \| `7` \| `14` \| `31` (days; **no 5**) |
| Sort by newest | `&sortmode=ListedDate` (default is relevance) |
| Pagination | `&page=2` (30 cards/page) |
| Job detail | `https://hk.jobsdb.com/job/{data-job-id}` (clean, stable, no redirect) |

**Don't reach for `sortmode=ListedDate` on a recurring scan.** It makes page 1 mean "whatever
posted in the last hour", relevance be damned, and a payroll job outranked everything for a
"business development" query. Default relevance sort + `daterange=7` is the combination that
actually surfaces good matches. Filter to your true window locally on `jobListingDate`.

**Keyword matching is loose full-text** and hits job descriptions, not just titles, so expect
off-target rows and filter titles locally.

---

## DOM contract

Cards are `article[data-card-type="JobCard"]`, each carrying `data-job-id`. Fields hang off
`data-automation` attributes, which are stable and semantic, so prefer them to CSS classes.

| Field | Selector |
|---|---|
| Card | `article[data-card-type="JobCard"]` |
| Title | `[data-automation="jobTitle"]` |
| Company | `[data-automation="jobCompany"]` |
| Location | `[data-automation="jobCardLocation"]` |
| Salary | `[data-automation="jobSalary"]` (present on only ~20% of HK cards) |
| Posted | `[data-automation="jobListingDate"]` (relative, e.g. "3d ago") |
| Classification | `[data-automation="jobClassification"]` |
| Teaser | `[data-automation="jobShortDescription"]` |

Detail pages use `[data-automation="job-detail-title"]`, `[data-automation="advertiser-name"]`,
`[data-automation="jobAdDetails"]`.

```python
rows = js("""
(function(){
  return [...document.querySelectorAll('article[data-card-type="JobCard"]')].map(function(c){
    var g = function(a){ var e = c.querySelector('[data-automation="'+a+'"]'); return e ? e.innerText.trim() : ''; };
    var id = c.getAttribute('data-job-id') || '';
    return {
      id: id,
      url: id ? 'https://hk.jobsdb.com/job/' + id : '',
      title: g('jobTitle'),
      company: g('jobCompany'),
      location: g('jobCardLocation'),
      salary: g('jobSalary'),
      posted: g('jobListingDate')
    };
  }).filter(function(r){ return r.id && r.title; });
})()
""")
```

Detail page:

```python
def jobsdb_detail(job_id, host="hk.jobsdb.com"):
    goto(f"https://{host}/job/{job_id}")
    wait_for_load(); wait(2)
    return js("""(function(){
      var g = function(a){ var e=document.querySelector('[data-automation="'+a+'"]'); return e?e.innerText.trim():''; };
      return {title: g('job-detail-title'), company: g('advertiser-name'), body: g('jobAdDetails')};
    })()""")
```

---

## Gotchas

- **The SEEK JSON API does not work here.** `/api/chalice-search/v4/search` 404s on JobsDB. Scrape
  the DOM.
- **`daterange` has no 5-day option.** Use `7` and filter locally.
- **Salary is usually absent** on HK cards (~20% carry one). Don't treat a missing salary as a
  signal about the role.
- **JobsDB does not cover mainland China.** Hong Kong only. For Shanghai/Shenzhen/Beijing, see below.

---

## Mainland China: the LinkedIn guest API

`linkedin.com/jobs/search` hits an authwall, but the guest endpoint returns JSON-ish HTML with **no
auth** and, unlike most boards, **exact ISO dates**:

```python
# f_TPR is a lookback in seconds: r432000 = 5d, r604800 = 7d
goto("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
     "?keywords=business%20development&location=Shanghai&f_TPR=r432000&start=0")
```

Returns 10 `<li>` cards per call, each with `<time datetime="ISO">`. Detail pages live at
`/jobs-guest/jobs/api/jobPosting/{id}`.

- **Rate limiting is real and it lies to you.** ~20 calls in, it starts returning **429**, which
  renders as *an empty result set, not an error*. A sweep that suddenly reports "no new roles" is
  far more likely throttled than genuinely empty. Space calls ~15s apart, and treat a zero result
  after heavy paging as unknown rather than as a finding.
- **Location matching is loose**: a `Shenzhen` query returns plenty of Hong Kong rows. Filter locally.
