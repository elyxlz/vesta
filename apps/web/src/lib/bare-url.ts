// remark-gfm only autolinks http(s)/www/email; this catches bare domains too (e.g.
// "linkedin.com/in/x"). A curated TLD list keeps code filenames like `index.ts` from
// linkifying. The lookbehind avoids grabbing an email's domain or a longer token; the
// lookahead keeps a listed TLD from matching inside a longer one ("example.community").
const LINK_TLDS =
  "com|org|net|edu|gov|mil|io|ai|co|dev|app|run|me|info|biz|tv|ly|gg|xyz|so|us|uk|ca|de|fr|it|es|nl|eu|in|jp|au";
const BARE_URL = new RegExp(
  `(?<![\\w@./-])((?:[a-z0-9-]+\\.)+(?:${LINK_TLDS})(?![a-z0-9-])(?:/[^\\s)]*)?)`,
  "gi",
);

export interface MdastNode {
  type: string;
  value?: string;
  url?: string;
  children?: MdastNode[];
}

export function splitTextIntoLinks(value: string): MdastNode[] {
  const out: MdastNode[] = [];
  let last = 0;
  for (const match of value.matchAll(BARE_URL)) {
    const start = match.index;
    const raw = match[1];
    if (raw === undefined) continue;
    if (start > last)
      out.push({ type: "text", value: value.slice(last, start) });
    out.push({
      type: "link",
      url: `https://${raw}`,
      children: [{ type: "text", value: raw }],
    });
    last = start + raw.length;
  }
  if (last < value.length) out.push({ type: "text", value: value.slice(last) });
  return out;
}
