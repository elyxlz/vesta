export function calendarDayKey(isoTs: string | undefined): string | null {
  if (!isoTs) return null;
  const d = new Date(isoTs);
  if (Number.isNaN(d.getTime())) return null;
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

export function formatChatDayStampLabel(
  isoTs: string,
  reference = new Date(),
): string {
  const d = new Date(isoTs);
  if (Number.isNaN(d.getTime())) return "";
  const sameYear = d.getFullYear() === reference.getFullYear();
  return d.toLocaleDateString(
    "en-US",
    sameYear
      ? { month: "short", day: "numeric" }
      : { month: "short", day: "numeric", year: "numeric" },
  );
}
