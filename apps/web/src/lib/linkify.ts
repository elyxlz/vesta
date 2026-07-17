const NUL = "\x00";
const URL_RE = /https?:\/\/[^\s<>"'`)\]},;*]+/g;
const PLACEHOLDER_RE = new RegExp(`${NUL}URL(\\d+)${NUL}`, "g");
const BOLD_RE = /\*\*(.+?)\*\*/g;
const ITALIC_RE = /(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g;
const CODE_RE = /`([^`]+)`/g;

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function linkify(text: string): string {
  const urls: string[] = [];
  const stripped = text.replace(URL_RE, (url) => {
    urls.push(url);
    return `${NUL}URL${String(urls.length - 1)}${NUL}`;
  });

  let out = escapeHtml(stripped);

  out = out.replace(PLACEHOLDER_RE, (match, i: string) => {
    const url = urls[Number(i)];
    // Input text can itself contain "\x00URL<n>\x00"; only replace our own placeholders.
    if (url === undefined) return match;
    const display = escapeHtml(url);
    return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${display}</a>`;
  });

  out = out.replace(CODE_RE, (_, code: string) => `<code>${code}</code>`);
  out = out.replace(BOLD_RE, (_, inner: string) => `<strong>${inner}</strong>`);
  out = out.replace(ITALIC_RE, (_, inner: string) => `<em>${inner}</em>`);
  return out;
}
