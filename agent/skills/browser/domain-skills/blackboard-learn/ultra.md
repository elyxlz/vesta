# Blackboard Learn Ultra: reading courses, content, and announcements

Hosts look like `https://<institution-learn-host>/ultra/...`. Everything below was verified on a
live Ultra deployment signed in through institutional SSO.

## Sign in

A signed-in session often lands on the public welcome page (`/`) with a "Login to Learn" link
instead of the course list. Click it: when the institution's SSO cookies are still valid in the
session profile, it completes with no user input and lands on `/ultra/course`.

```python
goto_url("https://<host>/")
wait_for_load()
js("""[...document.querySelectorAll("a,button")].find(e=>/Login to Learn/i.test(e.innerText||""))?.click()""")
# wait a few seconds, then check
signed_in = "Sign Out" in js("document.body.innerText")
```

Not signed in after the click means the SSO session expired: ask for a handover.

## Read data through the REST API, not the page

Ultra wraps `window.fetch`, so `fetch()` from `js()` fails with `TypeError: Failed to fetch`.
Navigate the tab to the endpoint instead and parse `document.body.innerText` as JSON; the session
cookies authenticate it.

```python
import json
goto_url("https://<host>/learn/api/public/v1/users/me/courses?expand=course&limit=100")
wait_for_load()
data = json.loads(js("document.body.innerText"))
for m in data["results"]:
    c = m["course"]
    print(c["id"], c["courseId"], c["name"])   # id looks like _123456_1
```

Useful endpoints (all GET, JSON, paged with `limit` + `paging.nextPage`):
- `/learn/api/public/v1/users/me/courses?expand=course`: enrolments with course names and ids
- `/learn/api/public/v1/courses/<id>/contents`: top-level course content; each item has `id`,
  `title`, `hasChildren`
- `/learn/api/public/v1/courses/<id>/contents/<contentId>/children`: one folder level down
- `/learn/api/public/v1/courses/<id>/announcements`: course announcements (if the role allows)

## Traps

- The course-list page renders tiles whose names do not appear in `innerText`
  (`.courseUnavailable` placeholders), so scraping the grid returns nothing useful. Use the
  enrolments endpoint above.
- The enrolments list also includes self-enrol training modules (library skills, integrity,
  data protection); filter on the term code in `courseId` to get the real courses.
- A course's own page is `/ultra/courses/<id>/outline`.
- The Learn calendar exposes a per-user iCal feed (Calendar, settings, "Get external calendar
  link"). Subscribing to it in the user's calendar is simpler than scraping deadlines.

## Class Collaborate recordings

Students get no permanent recording link: "Watch now" mints a one-time `eu.bbcollab.com/launch/...`
URL that expires in about 5 minutes, and the player URL carries no recording id. Hand the user the
path instead of a link.

- Shortcut: `/ultra/courses/<id>/outline/collab/launchRecordings` opens the course's recordings
  panel directly (slow first load, 10 to 20 seconds).
- Manual path: course outline, "Details & Actions" panel, the three-dot menu next to
  "Class Collaborate", "View all recordings", pick the recording, "Watch now" (opens a new tab).
- Recordings are "Course members only", so the viewer must be signed in as a member.
- Week pages may show a "Recordings" heading whose links render as `undefined`; ignore them and use
  the Collaborate panel.

## Deadlines can live only in a content title

A content folder's own title can carry a deadline ("Mid-term presentations (due by 23:59 on
Monday 26th October)") that appears in no announcement and no calendar entry. Before concluding a
deadline does not exist, list the titles from the contents endpoint above, one level down where
`hasChildren` is true, not just the announcements and the calendar feed.

## Discussion prompts

A "Discussion Board" item in the outline is a course link. Read its target to find the forum,
then read the forum's topic, whose `body` holds the prompt text (HTML). The Ultra page route for a
discussion often 404s; the REST path works.

```python
import json
def get(path):
    goto_url(f"https://<host>{path}"); wait_for_load()
    return json.loads(js("document.body.innerText"))
link = get(f"/learn/api/public/v1/courses/{cid}/contents/{item_id}")["contentHandler"]
# courselink -> {"targetId": ...}; read the target, whose handler is the forumlink
target = get(f"/learn/api/public/v1/courses/{cid}/contents/{link['targetId']}")["contentHandler"]
topic = get(f"/learn/api/public/v1/courses/{cid}/discussions/{target['discussionId']}")["topic"]
print(topic["body"])
```

## Downloading attachments (slides, lecture videos)

File links sit inside a document item's `body` HTML: each attachment is an `<a>` with a
`/bbcswebdav/...xid-...` href plus a `data-bbfile` JSON (file name, size, MIME type). The signed
query string on the href is not enough on its own: a plain `curl` returns 401. Export the session
cookies with a raw DevTools call into a file (never print them), pass them to `curl`, then delete
the file. This handles large files (a 100 MB lecture video) that are too big to pull through `js()`.

```python
r = cdp("Network.getCookies", urls=["https://<host>/"])
open("/tmp/learn_cookies.txt", "w").write("; ".join(f"{c['name']}={c['value']}" for c in r["cookies"]))
```

```bash
curl -sL -H "Cookie: $(cat /tmp/learn_cookies.txt)" -o slides.pdf '<bbcswebdav href, &amp; unescaped to &>'
rm -f /tmp/learn_cookies.txt
```
