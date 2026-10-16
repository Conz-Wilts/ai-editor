// Ruler ticks and time labels for any zoom: the step is the smallest that leaves MIN_PX between labels.
const MIN_PX = 72;
const STEPS_S = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800];

/** Frames between labelled ticks, and between the small ticks under them. */
export function tickStep(ppf: number, fps: number): { major: number; minor: number } {
  for (const f of [1, 2, 5, 10, 15]) if (f * ppf >= MIN_PX && f < fps) return { major: f, minor: Math.max(1, Math.round(f / 5)) };
  for (const s of STEPS_S) {
    const f = s * fps;
    if (f * ppf >= MIN_PX) return { major: f, minor: Math.max(1, Math.round(f / (s === 1 ? 2 : 5))) };
  }
  return { major: 3600 * fps, minor: 600 * fps };
}

/** m:ss, or m:ss.ff (frames) when the zoom shows single frames. */
export function timecode(frame: number, fps: number, frames = false): string {
  const s = Math.floor(frame / fps);
  const base = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  return frames ? `${base}.${String(Math.round(frame % fps)).padStart(2, "0")}` : base;
}
