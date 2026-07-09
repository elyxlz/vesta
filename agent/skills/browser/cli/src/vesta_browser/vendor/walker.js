// In-page accessibility snapshot walker. Reconstructs the numbered-ref (e1, e2, ...)
// snapshot that the CDP Accessibility.getFullAXTree path produced, but from the DOM
// using the vendored W3C accname/role algorithm (dom-accessibility-api). BiDi has no
// native AX-tree export, so we compute role + accessible name in-page and keep a
// realm-lived ref -> element map for coordinate resolution at action time.
import { getRole, computeAccessibleName, isInaccessible, isDisabled } from "dom-accessibility-api";

const INTERACTIVE_ROLES = new Set([
  "button", "link", "textbox", "searchbox", "combobox", "listbox", "menuitem",
  "menuitemcheckbox", "menuitemradio", "checkbox", "radio", "switch", "slider",
  "spinbutton", "tab", "treeitem", "option", "cell", "columnheader", "rowheader",
]);

const CONTAINER_ROLES = new Set([
  "main", "navigation", "banner", "contentinfo", "complementary", "region", "form",
  "search", "article", "dialog", "alertdialog", "menu", "menubar", "tablist",
  "tabpanel", "tree", "grid", "table", "list", "listitem", "heading", "figure",
  "section",
]);

const STATE_ATTRS = [
  ["checked", "aria-checked"],
  ["expanded", "aria-expanded"],
  ["selected", "aria-selected"],
  ["pressed", "aria-pressed"],
];

function ariaFlag(el, attr) {
  const v = el.getAttribute(attr);
  return v === "true" || v === "mixed";
}

function elementRole(el) {
  const role = getRole(el);
  return role || "";
}

function elementName(el) {
  try {
    return (computeAccessibleName(el) || "").trim();
  } catch {
    return "";
  }
}

function elementValue(el) {
  const tag = el.tagName.toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") {
    return (el.value || "").trim();
  }
  return "";
}

function ownText(el) {
  let text = "";
  for (const node of el.childNodes) {
    if (node.nodeType === 3) text += node.textContent;
  }
  return text.trim().replace(/\s+/g, " ");
}

function emit(el, role, name, value, ref) {
  const parts = [role || el.tagName.toLowerCase()];
  if (name) parts.push(`"${name}"`);
  if (value && value !== name) parts.push(`value="${value}"`);
  for (const [flag, attr] of STATE_ATTRS) {
    if (ariaFlag(el, attr)) parts.push(`[${flag}]`);
  }
  if (isDisabled(el)) parts.push("[disabled]");
  const level = el.getAttribute("aria-level");
  if (level) parts.push(`level=${level}`);
  if (ref) parts.push(`[ref=${ref}]`);
  return parts.join(" ");
}

function makeWalker(opts, refs, counter) {
  const interactiveOnly = !!opts.interactive_only;
  const maxDepth = opts.max_depth || 50;

  function walkChildren(el, depth, lines) {
    let produced = false;
    for (const child of el.children) {
      if (walk(child, depth, lines)) produced = true;
    }
    return produced;
  }

  function walk(el, depth, lines) {
    if (depth > maxDepth) return false;
    if (isInaccessible(el)) return false;

    const role = elementRole(el);
    const interactive = INTERACTIVE_ROLES.has(role);
    const container = CONTAINER_ROLES.has(role);

    if (interactiveOnly && !interactive) {
      return walkChildren(el, depth, lines);
    }

    const name = elementName(el);
    const value = elementValue(el);
    const text = ownText(el);

    let ref = null;
    if (interactive) {
      const rect = el.getBoundingClientRect();
      if (rect.width > 0 || rect.height > 0 || el.offsetParent !== null) {
        counter.n += 1;
        ref = "e" + counter.n;
        refs[ref] = { el, role, name };
      }
    }

    const indent = "  ".repeat(depth);
    const childLines = [];
    const refsBefore = Object.keys(refs).length;
    const producedChildren = walkChildren(el, depth + 1, childLines);
    const producedAny = producedChildren || Object.keys(refs).length > refsBefore;

    const hasVisibleContent = !!(name || value) || interactive;
    if (interactive || (container && (hasVisibleContent || producedAny))) {
      lines.push(`${indent}- ${emit(el, role, name, value, ref)}`);
      for (const l of childLines) lines.push(l);
      return true;
    }
    if (!container && !interactive && text && !producedAny) {
      lines.push(`${indent}- ${text}`);
      return true;
    }
    if (producedAny) {
      for (const l of childLines) lines.push(l);
      return true;
    }
    return false;
  }

  return walk;
}

function snapshot(opts) {
  opts = opts || {};
  const refs = {};
  const counter = { n: 0 };
  const walk = makeWalker(opts, refs, counter);
  const lines = [];
  if (document.body) walk(document.body, 0, lines);

  const refMeta = {};
  for (const ref of Object.keys(refs)) {
    refMeta[ref] = { role: refs[ref].role, name: refs[ref].name };
  }
  globalThis.__vestaRefs = refs;
  return {
    text: lines.join("\n"),
    refs: refMeta,
    ref_count: Object.keys(refs).length,
    url: location.href,
    title: document.title,
  };
}

function centerBox(el) {
  el.scrollIntoView({ block: "center", inline: "center" });
  const rect = el.getBoundingClientRect();
  return {
    found: true,
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2,
    w: rect.width,
    h: rect.height,
  };
}

function resolveRef(ref) {
  const refs = globalThis.__vestaRefs || {};
  const entry = refs[ref];
  if (!entry || !entry.el || !entry.el.isConnected) return { found: false };
  return centerBox(entry.el);
}

function focusRef(ref) {
  const refs = globalThis.__vestaRefs || {};
  const entry = refs[ref];
  if (!entry || !entry.el || !entry.el.isConnected) return { found: false };
  entry.el.focus();
  return { found: true };
}

globalThis.__vestaSnapshot = snapshot;
globalThis.__vestaResolveRef = resolveRef;
globalThis.__vestaFocusRef = focusRef;
