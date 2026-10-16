// Output formats (formats.json, shared with the Python's lib/ai_editor/formats.py): canvas, the platform's UI
// safe zone, keep-outs and export settings. `SafeZone` draws them over a frame for stills (render.mjs stills --safe).
import React from "react";
import { AbsoluteFill, useVideoConfig } from "remotion";
import data from "./formats.json";

type Side = { left: number; top: number; right: number; bottom: number };
type Rect = { x: number; y: number; w: number; h: number };
export type Format = {
  label: string; aspect: string; width: number; height: number; legacyAspect: "9:16" | "16:9";
  safe?: Partial<Side>; safePct?: Side; keepout?: Rect[]; feedCrop?: Rect; maxDurationS?: number;
  export: { codec: string; pixelFormat?: string; colorSpace?: string; crf?: number; maxrate?: string; bufsize?: string;
            audio?: { codec: string; sampleRate?: number; bitrate?: string } };
};

export const FORMATS = (data as unknown as { formats: Record<string, Format> }).formats;

// The plan's format when it names a known one, else the default of its shape (as formats.py for_size).
export const formatFor = (fid: string | undefined, w: number, h: number): string =>
  fid && FORMATS[fid] ? fid : h > w ? "vertical" : w > h ? "youtube" : "square";

// left, top, right, bottom in % of the width / height.
export const safePct = (fid: string): [number, number, number, number] => {
  const f = FORMATS[fid];
  if (f.safePct) return [f.safePct.left, f.safePct.top, f.safePct.right, f.safePct.bottom];
  const s = f.safe || {};
  return [100 * (s.left || 0) / f.width, 100 * (s.top || 0) / f.height, 100 * (s.right || 0) / f.width, 100 * (s.bottom || 0) / f.height];
};

// The top of a vertical frame's safe zone as a fraction of the height (plan.py SAFE["9:16"] top).
export const VERTICAL_SAFE_TOP = safePct("vertical")[1] / 100;

const pct = (r: Rect, f: Format): React.CSSProperties =>
  ({ position: "absolute", left: `${100 * r.x / f.width}%`, top: `${100 * r.y / f.height}%`,
     width: `${100 * r.w / f.width}%`, height: `${100 * r.h / f.height}%` });

// The safe zone (red), the app's keep-outs (orange) and a feed crop (dashed), over the frame.
export const SafeZone: React.FC<{ format?: string }> = ({ format }) => {
  const { width, height } = useVideoConfig();
  const fid = formatFor(format, width, height);
  const f = FORMATS[fid];
  const [l, t, r, b] = safePct(fid);
  const line = Math.max(3, Math.round(Math.min(width, height) / 270));
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div style={{ position: "absolute", left: `${l}%`, top: `${t}%`, right: `${r}%`, bottom: `${b}%`,
                    border: `${line}px solid rgba(255,40,40,0.9)` }} />
      {(f.keepout || []).map((k, i) => <div key={i} style={{ ...pct(k, f), background: "rgba(255,150,0,0.35)",
                                                             border: `${line}px solid rgba(255,150,0,0.9)` }} />)}
      {f.feedCrop ? <div style={{ ...pct(f.feedCrop, f), border: `${line}px dashed rgba(80,200,255,0.9)` }} /> : null}
      <div style={{ position: "absolute", left: `${l}%`, top: `${t}%`, padding: line * 2, font: `600 ${line * 6}px sans-serif`,
                    color: "#fff", background: "rgba(255,40,40,0.9)" }}>{fid}</div>
    </AbsoluteFill>
  );
};
