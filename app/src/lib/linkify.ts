const URL_RE = /https?:\/\/[^\s<>"'`)\]},;*]+/g;
const BOLD_RE = /\*\*(.+?)\*\*/g;
const ITALIC_RE = /(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g;
const CODE_RE = /`([^`]+)`/g;

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

export function linkify(text: string): string {
  let out = escapeHtml(text);
  out = out.replace(URL_RE, (url) => `<a href="${url}" target="_blank" rel="noopener">${url}</a>`);
  out = out.replace(CODE_RE, (_, code) => `<code>${code}</code>`);
  out = out.replace(BOLD_RE, (_, inner) => `<strong>${inner}</strong>`);
  out = out.replace(ITALIC_RE, (_, inner) => `<em>${inner}</em>`);
  return out;
}
