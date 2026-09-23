/** Axis helpers shared by the journey charts. */
export function niceTicks(max: number, count: number): number[] {
  const raw = max / count;
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const candidates = [1, 2, 2.5, 5, 10].map((m) => m * magnitude);
  const step =
    candidates.find((c) => c >= raw) ?? candidates[candidates.length - 1];
  const ticks: number[] = [];
  for (let v = 0; v <= max; v += step) ticks.push(Number(v.toFixed(6)));
  return ticks;
}
