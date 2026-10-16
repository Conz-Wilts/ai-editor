import React from "react";
import { AbsoluteFill, Img, OffthreadVideo, Sequence, staticFile, useCurrentFrame, useVideoConfig } from "remotion";

// The main track as the project timeline has it (project_convert.to_plan "clips"): each clip plays source frames
// [trimIn, trimIn + durationInFrames) from frame `from` of the edit. Frames are at the plan's fps.
// fit: cover (default, fills the frame), contain (whole picture, black bars), reframe (cover, following the
// speaker: keyframes [{f, cx, cy}] in clip frames, % of the source, from reframe.py over face.json).
export type Keyframe = { f: number; cx: number; cy: number };
export type Clip = {
  src: string;
  from: number;
  durationInFrames: number;
  trimIn?: number;
  volume?: number;
  fit?: "cover" | "contain" | "reframe";
  reframe?: Keyframe[];
};
// A b-roll or generated item (seconds, like every other plan list): full frame, or in box [x, y, w, h] % of the frame.
export type Overlay = {
  src: string;
  start: number;
  end: number;
  trimIn?: number;
  box?: [number, number, number, number];
  props?: { volume?: number; fit?: "cover" | "contain"; muted?: boolean };
};

const IMAGE = /\.(png|jpe?g|webp|gif|svg|avif)$/i;
const smooth = (x: number) => x * x * (3 - 2 * x);

/** Where the frame looks at clip frame f: eased between keyframes, held before the first and after the last. */
export const reframeAt = (kf: Keyframe[] | undefined, f: number): [number, number] => {
  if (!kf?.length) return [50, 50];
  if (f <= kf[0].f) return [kf[0].cx, kf[0].cy];
  for (let i = 1; i < kf.length; i++) {
    if (f <= kf[i].f) {
      const a = kf[i - 1], b = kf[i];
      const p = smooth((f - a.f) / Math.max(1, b.f - a.f));
      return [a.cx + (b.cx - a.cx) * p, a.cy + (b.cy - a.cy) * p];
    }
  }
  const z = kf[kf.length - 1];
  return [z.cx, z.cy];
};

const ClipView: React.FC<{ c: Clip; style?: React.CSSProperties }> = ({ c, style }) => {
  const f = useCurrentFrame();   // frames into this clip (the Sequence's own clock)
  const fit = c.fit ?? "cover";
  // object-position x% puts the source's x% at the frame's x%: the face stays in shot however the crop falls
  const [cx, cy] = fit === "reframe" ? reframeAt(c.reframe, f) : [50, 50];
  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <OffthreadVideo src={staticFile(c.src)} trimBefore={c.trimIn || 0} volume={c.volume ?? 1}
        style={{ width: "100%", height: "100%", ...style, objectFit: fit === "contain" ? "contain" : "cover",
          objectPosition: `${cx}% ${cy}%` }} />
    </AbsoluteFill>
  );
};

/** The footage under everything: the plan's single `video`, or its `clips` when the timeline has several. */
export const Footage: React.FC<{ video?: string; clips?: Clip[]; style?: React.CSSProperties }> = ({ video, clips, style }) => {
  if (!clips?.length) {
    return video ? <OffthreadVideo src={staticFile(video)} style={{ width: "100%", height: "100%", ...style }} /> : null;
  }
  return (
    <>
      {clips.map((c, i) => (
        <Sequence key={`${c.src}${c.from}${i}`} from={c.from} durationInFrames={Math.max(1, c.durationInFrames)}>
          <ClipView c={c} style={style} />
        </Sequence>
      ))}
    </>
  );
};

const OverlayView: React.FC<{ o: Overlay }> = ({ o }) => {
  const { width, height } = useVideoConfig();
  const fit = o.props?.fit ?? "cover";
  const media = IMAGE.test(o.src)
    ? <Img src={staticFile(o.src)} style={{ width: "100%", height: "100%", objectFit: fit }} />
    : <OffthreadVideo src={staticFile(o.src)} trimBefore={Math.round((o.trimIn ?? 0))} muted={o.props?.muted}
        volume={o.props?.volume ?? 1} style={{ width: "100%", height: "100%", objectFit: fit }} />;
  if (!o.box) return <AbsoluteFill style={{ backgroundColor: "#000" }}>{media}</AbsoluteFill>;
  const [x, y, w, h] = o.box;
  return (
    <div style={{ position: "absolute", left: (x / 100) * width, top: (y / 100) * height, width: (w / 100) * width,
      height: (h / 100) * height, overflow: "hidden", borderRadius: Math.min(width, height) * 0.02 }}>{media}</div>
  );
};

/** B-roll and generated clips over the footage, each on its own stretch of the timeline. */
export const Overlays: React.FC<{ items?: Overlay[] }> = ({ items }) => {
  const { fps } = useVideoConfig();
  return (
    <>
      {(items ?? []).map((o, i) => {
        const from = Math.round(o.start * fps), dur = Math.max(1, Math.round((o.end - o.start) * fps));
        return (
          <Sequence key={`${o.src}${o.start}${i}`} from={from} durationInFrames={dur}>
            <OverlayView o={o} />
          </Sequence>
        );
      })}
    </>
  );
};
