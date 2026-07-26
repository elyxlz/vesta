---
name: sign-service
description: Let the user hand-draw a signature in their browser, then stamp it onto a PDF field. Use when someone needs to sign a PDF (tax form, contract, waiver) but can't or won't edit the PDF themselves, especially on a laptop where phone markup isn't an option.
---

# sign-service

A tiny "DocuSign-style" flow you host yourself, no third-party account:

1. **Serve a signature pad.** A public web page with a canvas the user draws on (mouse, trackpad, or touch) and hits Submit.
2. **Capture the signature.** On submit the page POSTs the drawn PNG (transparent background, ink only) to the output path and drops an interrupt notification (`type=signature_received`).
3. **Stamp it onto the PDF.** Place the signature image into the right field on the right page, render a preview, and let the user eyeball it before anything is sent.

## When to use
- User says "I can't sign a PDF", "make it easy to sign", "isn't there a docusign type thing", or is on a laptop.
- Any PDF that needs a handwritten signature in a known spot.

## Pieces
- `sign_server.py`: stdlib HTTP server. `GET /` serves the pad; `POST .../submit` saves the PNG and fires the notification. Path-agnostic so it works behind vestad's `/agents/<name>/<service>/` reverse proxy. Run: `python3 sign_server.py <PORT> [OUTPUT_PNG]` (output defaults to `/tmp/sign-service/signature.png`).
- `stamp.py`: uses PyMuPDF to find a label on the target page and drop the signature into the box just below it, then optionally render a page preview. Takes all inputs as CLI arguments (`--help` for the full list), so nothing is hardcoded.

## Run it
```bash
# 1. Register a PUBLIC service with vestad to get a port + tunnel URL
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services \
  -H "X-Agent-Token: $AGENT_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"sign","public":true}' | python3 -c "import sys,json;print(json.load(sys.stdin)['port'])")
screen -dmS sign-service /root/agent/.venv/bin/python3 ~/agent/skills/sign-service/sign_server.py $PORT /tmp/sign-service/signature.png
# 2. Send the user:  $VESTAD_TUNNEL/agents/$AGENT_NAME/sign/
# 3. On the signature_received notification, stamp + preview:
uv run --with PyMuPDF python3 ~/agent/skills/sign-service/stamp.py \
  --signature /tmp/sign-service/signature.png \
  --outdir /tmp/sign-service/signed \
  --label "FIRMA del CONTRIBUENTE" --label "FIRMA DEL CONTRIBUENTE" \
  --page 2 --preview \
  "/tmp/sign-service/form.pdf"
# 4. Send the user the signed PDF(s) for visual approval, THEN deliver on their OK.
```

## Placing the signature (stamp.py)
`stamp.py` locates the field by searching the page text for a label (for example "FIRMA del CONTRIBUENTE") and places the image in a box just below it, `keep_proportion=True` so it never distorts. For a new document: open the PDF, find which page and which label mark the signature line (render the page to PNG and look), then pass the `--page` index (zero-based, so page 3 is `--page 2`) and one or more `--label` values. Tune `--width`, `--height`, and `--gap` (all in points) if the box needs nudging, and `--x-min`/`--x-max` to constrain the label-word fallback to one column. ALWAYS render a preview and get the user to approve before sending anything; placement is best-effort.

## Safety
- The signed document is legally the user's. Never deliver or email it anywhere until the user has seen the stamped preview and explicitly says go.
- The signature PNG is personal; keep it under `/tmp` so it gets pruned nightly. Don't persist it or commit it.
- Tear the service down when done (`screen -S sign-service -X quit`) and drop any TEMP guard line from the restart skill.
