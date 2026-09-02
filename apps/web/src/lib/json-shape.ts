// Field readers for JSON that arrived untyped (a response body, a storage entry): each answers
// the typed value or null, so a caller narrows at the boundary instead of asserting a shape.

export function field(value: unknown, key: string): unknown {
  if (typeof value !== "object" || value === null) return undefined;
  return Reflect.get(value, key);
}

export function stringField(value: unknown, key: string): string | null {
  const read = field(value, key);
  return typeof read === "string" ? read : null;
}

export function numberField(value: unknown, key: string): number | null {
  const read = field(value, key);
  return typeof read === "number" && Number.isFinite(read) ? read : null;
}

export function booleanField(value: unknown, key: string): boolean | null {
  const read = field(value, key);
  return typeof read === "boolean" ? read : null;
}
