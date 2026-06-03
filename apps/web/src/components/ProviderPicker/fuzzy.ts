export function fuzzyMatch(query: string, target: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === "") return true;
  const t = target.toLowerCase();
  let i = 0;
  for (let j = 0; j < t.length && i < q.length; j++) {
    if (t[j] === q[i]) i++;
  }
  return i === q.length;
}
