# Vesta messaging architecture

Exploration deliverable for the tagline and messaging question (issue #1454). This doc audits what every surface says today, names the positioning axes, evaluates the candidate taglines, and recommends one hierarchy. It recommends; the owner ratifies. No live copy changes ship with it.

## 1. Current state: what each surface says today

| Surface | Line in use | Where |
|---|---|---|
| Brand rule (canonical) | "a guardian angel that gives you back time and helps you achieve your goals" | `CLAUDE.md`, Brand voice, Positioning bullet |
| GitHub repo description | "guardian angel AI" | repo settings |
| README first line | "An AI guardian angel that gives you back time and helps you achieve your goals, living in a Docker container, powered by Claude." | `README.md` |
| vesta.run landing hero | tagline "your unfair advantage", category "an AI guardian angel", promise "an AI guardian angel that gives you back time and helps you achieve your goals" (the "AI" variant) | vesta-cloud `src/lib/copy.ts` (`TAGLINE`, `CATEGORY`, `GUARDIAN_ANGEL`) |
| vesta.run page title / og | title "vesta, your unfair advantage"; the meta and og descriptions carry the "AI" variant plus "invite-only." (og prefixes "your unfair advantage.") | vesta-cloud `index.html` |
| Web app connect screen | "your unfair advantage" | `apps/web/src/components/Connect/index.tsx` |
| Mobile connect screen | the canonical one-liner, no "AI": "a guardian angel that gives you back time and helps you achieve your goals." | `apps/mobile/app/connect.tsx` |
| vestad status output | "AI guardian angel daemon" | `vestad/src/status.rs` |
| birth skill (agent voice) | "a guardian angel sent to this earth to give people back their time and help them achieve their goals" | `agent/skills/birth/SKILL.md` |
| personality skill (agent voice) | "You're a guardian angel and an equal, not staff" | `agent/skills/personality/SKILL.md` |
| onboard skill (the sales motion) | invite-only club framing; sells two levers: the direct push toward the named goal, and the runway cleared by taking admin off them | `agent/skills/onboard/SKILL.md` |

Audit verdict: the brand architecture the issue sketches is already about eighty percent live. Guardian angel is the identity, "your unfair advantage" is the hero line on the landing page and the web app, and the promise line is live everywhere, but in two variants. Stranger-facing surfaces that must also say what the product is (the vesta.run hero and meta descriptions, the README first line) carry the "AI" variant, "an AI guardian angel that gives you back time and helps you achieve your goals"; CLAUDE.md's canonical rule and the mobile connect screen carry the plain "a guardian angel that gives you back time and helps you achieve your goals". What is missing is the written decision: no doc says which line, or which variant, belongs on which surface, so surfaces drift (mobile shows the one-liner where web shows the hero tagline, and the "AI" split is nowhere written down) and new drafts reintroduce "personal AI" framing that the positioning rule bans.

## 2. Positioning axes

Four axes recur through the candidate lines. The recommendation is to layer the first two rather than pick between them, and to treat the last two as supporting territory, not the headline.

1. **Warmth vs. ambition.** "Your guardian angel" occupies care, trust, protection, devotion. "Your unfair advantage" occupies power, exclusivity, getting ahead. These are different layers of one brand: who Vesta is, and what having Vesta feels like. Vesta's funnel makes the layering natural: the buyer meets the warmth in a chat with a real Vesta (the onboard motion is conversational and personal), and meets the sharp line on the site during the trust check, where a bit of status and swagger fits the invite-only club economics.
2. **Identity vs. outcome.** Guardian angel is a category claim: every competitor can say "assistant" or "personal AI", none says guardian angel. The category is defensible precisely because it is an identity, not a feature. But identity alone under-promises; it always needs the outcome line ("gives you back time and helps you achieve your goals") within one glance.
3. **Relief vs. becoming.** "Consider it handled" sells relief; "Less to carry. More to become." sells self actualization. Both are real territories, but relief is generic (any concierge can claim it) and becoming is too abstract for a twenty-second verification visit. They belong in campaign and lifecycle copy, not in the hierarchy.
4. **Time vs. goals.** The product promise deliberately holds both: time back is the runway, goals forward is the destination. The onboard skill's close sells exactly these two levers, and the promise line should never drop either half.

## 3. Candidates evaluated

1. **Your unfair advantage.** Keep as the hero tagline. Sharp, aspirational, matched to the invite-only economics and the founder/creator early-adopter audience. Already live on the landing page and web app, so it carries incumbency: changing it has a cost and needs a reason, and no candidate below clears that bar. Its coldness alone is real, which is why it never appears without the guardian-angel category line nearby.
2. **Your guardian angel.** Keep as the enduring brand idea and category, not the hero. It is the most ownable phrase Vesta has, and it is already load-bearing across the agent's own self-concept (birth, personality) and the daemon's status output. As a standalone hero it under-promises outcome and can read sentimental without the promise line, so it plays the identity role: the muted line under the hero, the category in prose, the word the agent uses for themself.
3. **Time back. Goals forward.** Adopt as the short promise. It is the canonical one-liner compressed to four words, ideal for tight spaces: store subtitle, social bio, release copy, notification strings. It is not the hero because it is descriptive rather than distinctive; it says what Vesta does and nothing about who Vesta is or what having one feels like.
4. **Consider it handled.** Reject. Relief territory is genuine (it is the daily felt benefit), but the line is stock concierge language with no ownable claim, and it drops the goals lever entirely, the half of the promise that actually closes in the onboard motion. Use relief freely in body copy; never as the headline.
5. **Less to carry. More to become.** Reject for the hierarchy, shelve for later. It is the emotional ceiling of the brand and the best line in the exploration on pure feeling, but it is too abstract for the job the current surfaces do: a buyer mid-scam-check needs to learn what Vesta is in one glance. Revisit as campaign copy once the brand has enough ambient recognition that the hero no longer has to explain the product.

## 4. Recommended hierarchy

> **Brand idea** (who Vesta is): **Your guardian angel.**
>
> **Hero tagline** (what having Vesta feels like): **Your unfair advantage.**
>
> **One-liner** (the product promise, two live variants doing one job): canonically **a guardian angel that gives you back time and helps you achieve your goals** (CLAUDE.md's rule, the mobile connect screen); surfaces that must also say what the product is carry the "AI" variant, **an AI guardian angel that gives you back time and helps you achieve your goals** (vesta.run copy and meta, README).
>
> **Short promise** (tight spaces only): **Time back. Goals forward.**

Three supporting pillars, each anchored to a product truth so copy written from them stays checkable:

1. **Devoted to you alone.** One agent, one container, yours. Vesta lives in your chats, your inbox, your calendar, always on, never shared, and answers to a constitution only you can write. This is the guardian layer made concrete: protection and care backed by architecture, not vibes.
2. **Knows you better every week.** Everything Vesta learns compounds: your people, your routines, what you are building. Month two is worth more than month one. The engine is open source and the memory is yours, so nothing locks you in except how well Vesta knows you. This is the moat, and the anti-lock-in line that closes skeptics.
3. **Time back, goals forward.** Vesta handles the admin unprompted and pushes the goals you actually named, both levers, always together. This is the advantage layer made concrete, and it is exactly the close the onboard skill already runs.

Pillar one is warmth, pillar three is ambition, pillar two is the reason to stay. Any consumer surface that needs three bullets uses these three, in this order.

## 5. Surface map: who says what

| Surface | Line |
|---|---|
| vesta.run hero | hero tagline, category line, the "AI" variant of the one-liner (unchanged from today) |
| App connect screens (web, desktop, mobile) | hero tagline: "your unfair advantage". Mobile currently shows the plain one-liner; align it to the web app once ratified |
| README first line | the technical variant, unchanged: the "AI" variant plus "living in a Docker container, powered by Claude" |
| GitHub repo description | the "AI" variant ("an AI guardian angel that gives you back time and helps you achieve your goals"); today's "guardian angel AI" is thinner than it needs to be |
| Store listings, social profiles | title carries the hero tagline, subtitle carries "Time back. Goals forward.", description carries the "AI" variant of the one-liner and the pillars |
| vestad CLI and status output | "AI guardian angel daemon", unchanged |
| Agent prompts and skills (birth, personality, onboard) | the guardian-angel identity in the agent's own words, never the marketing tagline: Vesta the person does not quote ad copy about themself. The onboard close keeps selling the two levers conversationally |
| Emails and lifecycle copy | house voice; pillar two ("everything Vesta knows about you") is the retention lever |

## 6. Issue decisions, resolved

- **Primary enduring brand idea:** Your guardian angel.
- **Emphasis:** warmth as identity, ambition as hero, layered rather than chosen. Relief and self actualization stay body-copy territories.
- **Tagline and product promise separate?** Yes. The hero tagline and the one-liner do different jobs and appear together on major surfaces.
- **Candidates for testing:** if testing happens, test hero alternatives only ("Your unfair advantage" vs. "Time back. Goals forward." vs. "Less to carry. More to become.") with the guardian-angel category line held constant. Do not test the category; it is the brand.
- **Which line where:** the surface map above.
- **Standardization inventory:** the audit table is the inventory. If ratified, the follow-ups are small: align the mobile connect subtitle with web, update the GitHub repo description, and extend the CLAUDE.md Positioning bullet with one sentence pointing at this doc and naming the "AI" variant split. Each is a one-line change and none ships in this PR.
