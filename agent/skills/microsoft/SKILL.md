---
name: microsoft
description: This skill should be used when the user asks about "email", "emails", "inbox", "messages", "calendar", "schedule", "scheduling", "meetings", "appointments", "events", "outlook", or needs to read/send emails, manage calendar events, or handle time-based tasks via Microsoft/Outlook. IMPORTANT — this skill requires a background daemon. Before doing anything, immediately make sure the daemon is running. Read this skill to learn how.
---

# Microsoft — CLI: microsoft

**Setup**: See [SETUP.md](SETUP.md)
**Background**: `screen -dmS microsoft microsoft serve --notifications-dir ~/vesta/notifications`
**Account**: lucio@pascarelli.com
**Permissions**: read-only email, read/write calendar

## Email

```bash
microsoft email list --account lucio@pascarelli.com
microsoft email get --account lucio@pascarelli.com --id <email_id>
microsoft email send --account lucio@pascarelli.com --to bob@example.com --subject "Hello" --body "Message"
microsoft email reply --account lucio@pascarelli.com --id <email_id> --body "Thanks!"
microsoft email search --account lucio@pascarelli.com --query "project update"
```

## Calendar

```bash
microsoft calendar list --account lucio@pascarelli.com --user-timezone "Europe/Rome"
microsoft calendar create --account lucio@pascarelli.com --subject "Standup" --start "2025-11-15T10:00:00" --end "2025-11-15T10:30:00" --timezone "Europe/Rome"
microsoft calendar respond --account lucio@pascarelli.com --id <event_id> --response accept
```

## Notes
- `--account` required for all email/calendar commands (find with: `microsoft auth list`)
- `--timezone` required for calendar create/update (IANA names like "Europe/London")
- `--response` choices: accept / decline / tentativelyAccept
- `--to`/`--cc`/`--attendees` accept multiple space-separated values
- `--no-cancellation` on delete skips notifying attendees
- `--no-details` on calendar list returns compact output (no body/attendees)
- `--user-timezone` on calendar list converts times to the given IANA timezone
- `--folder` on email list/search filters by folder (default "inbox")
- `--no-attachments` on email get skips attachment metadata
- `--save-to` on email get saves the full email JSON to a file
- `--categories` on email update accepts multiple space-separated category names

### Contact Communication Styles

**English (international academics) — formal, warm:**
- Mark Altaweel (m.altaweel@ucl.ac.uk) — UCL Professor, SARDUS PI; close working relationship, light humor ok ("Love the welsh 😊"), short replies fine
- Eric Cline (ehcline@gmail.com) — GWU Professor, keynote speaker; professional, polite
- Emily Holt — Cardiff University; participant, professional
- Andrea Squitieri — Padova; participant, professional
- Juan Luis Bernal Wormull — Basel; participant, professional
- Jesse Millek — Leiden; participant, professional
- Luca Lai — UNC Charlotte; participant, professional
- Andrea Columbu — Pisa; participant, professional

**Italian (partners/vendors) — informal-professional:**
- Antonello Gregorini (a.gregorini59@gmail.com) — NURNET president, co-coordinator; "Ciao Antonello", close colleague
- Simone Ollanu (simoneollanu@gmail.com) — Is Perdas resort / NurTime; "Ciao Simone", logistics partner
- Claudio Ollanu (claudioollanu@gmail.com) — Is Perdas resort / NurTime
- Roberto Masiero (masiero@community.iuav.it) — IUAV Venice, SARDUS collaborator
- Silvano Tagliagambe (sil.tagliagambe@gmail.com) — philosopher/academic, SARDUS
- Ilaria Sau / LIVE Studio (ilaria@livestudio.it) — translation service provider; "Ciao Ilaria", vendor
- Donatella Pichinon (donatella@pichinon.com / donatella.pichinon@fao.org) — wife; works at FAO Rome

**Family:**
- Teresa Pascarelli (teresa@pascarelli.com) — family (likely wife or sister); organizes "Fumbles Talk" meetings
- Elio Pascarelli (elio@pascarelli.com) — brother; Audiogen project
- Emilio Pascarelli (emilio@pascarelli.com) — brother; Audiogen project

**Ignore:**
- Rufo Guerreschi / trustlesscomputing.org — do not surface anything from or about him

### Email Preferences

- **Language**: Italian with Italian contacts, English with international contacts, switches fluently
- **English sign-off**: "Kind regards, / Lucio Pascarelli / NURNET APS - La Rete dei Nuraghi / WhatsApp/Tel: +39 348 3826189"
- **Italian sign-off**: "Grazie" / "Lucio Pascarelli" (shorter for casual, with org footer for formal)
- **Greeting EN**: "Dear [First Name],"
- **Greeting IT**: "Ciao [First Name]," (casual) / "Gentile [First Name]," (formal/institutional)
- **Length**: Concise but complete. Short acknowledgments ("Thank you all also on behalf of Nurnet. Lucio"). Bullet-pointed logistics when coordinating.
- **Tone**: Professional and warm. Occasional humor with close collaborators (Mark). No slang. Full sentences.
- **Mobile sends**: Sometimes sends very short replies from Outlook for Android ("Can you talk now?")
- **Email is read-only** — cannot send/reply via the CLI. Present drafts for Lucio to send manually.

### Scheduling Preferences

- **Timezone**: Europe/Rome (CET/CEST, UTC+1/+2)
- **Travel cadence**: Based in Gavoi/central Sardinia; travels to Cagliari and Rome regularly; international for conferences
- **Flight hub**: Uses Olbia airport (OLB) for Sardinia connections, then FCO (Fiumicino) for Rome
- **Calendar style**: Creates detailed events including flights, medical appointments, vendor meetings

### Regular Events

- **Fumbles Talk** — recurring meeting organized by Teresa Pascarelli, Google Meet link; attendees include Francesco Centemeri (fcentemeri@geico-spa.com, GEICO)
- **NURNET / SARDUS coordination calls** — ad hoc with Mark Altaweel and European consortium
- **Audiogen transition** — family business meetings with Elio and Emilio Pascarelli via Zoom

### Active Projects

1. **June 2026 Sardinia Workshop** (June 12-14) — Lucio is logistics coordinator; venue: Is Perdas resort, Gergei/Villanovaforru area; ~10 international academics invited; coordinating travel, accommodation, translation services
2. **SARDUS ERC Synergy Grant** — passed Step 1 (March 2026); Step 2 result expected July 2026; consortium: UCL, Duke, UChicago, CRS4, UniSassari, UniCagliari, Argonne
3. **MOIRA EU Project** — Stage 2 submitted; consortium of ~20 institutions across EU; NURNET is a partner
4. **Audiogen** — family business transition; meetings with brothers Elio and Emilio

### Upcoming (as of March 19, 2026)

- **March 22**: Flight OLB→FCO (Volotea V7 1134), ref T572FY — Rome trip
- **March 23**: Helicobacter test (stool sample) — "portare a Roma" (bring to Rome)
- **March 24**: Flight FCO→OLB (Volotea V7 1133), ref T572FY — return to Sardinia
- **March 25**: Haircut at Sestosenso1978, Gavoi
