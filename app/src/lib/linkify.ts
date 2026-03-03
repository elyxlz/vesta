const URL_RE = /https?:\/\/[^\s<>"'`)\]},;*]+/g;
const BOLD_RE = /\*\*(.+?)\*\*/g;
const ITALIC_RE = /(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g;
const CODE_RE = /`([^`]+)`/g;

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

export function linkify(text: string): string {
  const urls: string[] = [];
  let stripped = text.replace(URL_RE, (url) => {
    urls.push(url);
    return `\x00URL${urls.length - 1}\x00`;
  });

  let out = escapeHtml(stripped);

  out = out.replace(/\x00URL(\d+)\x00/g, (_, i) => {
    const url = urls[Number(i)];
    const display = escapeHtml(url);
    return `<a href="${url}" target="_blank" rel="noopener">${display}</a>`;
  });

  out = out.replace(CODE_RE, (_, code) => `<code>${code}</code>`);
  out = out.replace(BOLD_RE, (_, inner) => `<strong>${inner}</strong>`);
  out = out.replace(ITALIC_RE, (_, inner) => `<em>${inner}</em>`);
  return out;
}
