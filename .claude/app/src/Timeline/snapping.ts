// Snapping: a dragged edge lands on the playhead, the start, or any other item's edge when it comes within
// SNAP_PX on screen. Which tracks an item may move to: footage among footage, cards among cards, sound among sound.
import type { Project } from "../types";

export const SNAP_PX = 8;

export function snapPoints(doc: Project, exclude: Set<string>, playhead: number): number[] {
  const pts = new Set<number>([0, playhead]);
  for (const t of doc.tracks) for (const it of t.items) {
    if (exclude.has(it.id)) continue;
    pts.add(it.from);
    pts.add(it.from + it.durationInFrames);
  }
  return [...pts];
}

/** The nearest snap point to frame within SNAP_PX on screen, else frame itself. */
export function snap(frame: number, points: number[], ppf: number, on = true): { frame: number; hit: number | null } {
  if (!on) return { frame, hit: null };
  let best: number | null = null, dist = SNAP_PX / ppf;
  for (const p of points) {
    const d = Math.abs(p - frame);
    if (d <= dist) { dist = d; best = p; }
  }
  return best === null ? { frame, hit: null } : { frame: best, hit: best };
}

const GROUP: Record<string, string> = { main: "footage", broll: "footage", generated: "footage", cards: "cards",
  music: "sound", sfx: "sound", zooms: "zooms", captions: "captions" };
export const groupOf = (role: string) => GROUP[role] ?? role;
export const canMoveTo = (fromRole: string, toRole: string) => groupOf(fromRole) === groupOf(toRole);
