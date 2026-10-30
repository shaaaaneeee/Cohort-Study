export function formatCount(n: number | null | undefined): string {
  return n === null || n === undefined ? "–" : n.toLocaleString("en-GB");
}

export function formatNumber(x: number | null | undefined, digits = 2): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "–";
  return x.toLocaleString("en-GB", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function formatP(p: number | null | undefined): string {
  if (p === null || p === undefined) return "–";
  return p < 0.001 ? "p < 0.001" : `p = ${p.toFixed(3)}`;
}

export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

export function timeOfDay(date: Date): string {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
