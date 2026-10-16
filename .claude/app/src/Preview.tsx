// The edit itself: the renderer's StyleEdit composition (remotion/src) in a <Player>, fed the plan the timeline
// makes (GET /api/plan), so what plays here is what renders. The safe zone overlay is formats.tsx's.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { AbsoluteFill } from "remotion";
import { Player, PlayerRef } from "@remotion/player";
import { StyleEdit } from "../../remotion/src/StyleEdit";
import { SafeZone } from "../../remotion/src/formats";
import { getState, setState, useStore } from "./store";

const Comp: React.FC<any> = (p) => (
  <AbsoluteFill style={{ backgroundColor: "#000" }}>
    <StyleEdit {...p} />
    {p.__safe ? <SafeZone format={p.format} /> : null}
  </AbsoluteFill>
);

export const Preview: React.FC = () => {
  const plan = useStore((s) => s.plan);
  const showSafe = useStore((s) => s.showSafe);
  const seekReq = useStore((s) => s.seek);
  const ref = useRef<PlayerRef>(null);
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 640, h: 360 });

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth - 28, h: el.clientHeight - 28 }));   // inside .stage's padding
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // the Player's own clock drives the playhead while it plays
  useEffect(() => {
    const p = ref.current;
    if (!p) return;
    const onFrame = (e: { detail: { frame: number } }) => setState({ frame: e.detail.frame });
    const onPlay = () => setState({ playing: true });
    const onPause = () => setState({ playing: false });
    p.addEventListener("frameupdate", onFrame as any);
    p.addEventListener("play", onPlay);
    p.addEventListener("pause", onPause);
    return () => {
      p.removeEventListener("frameupdate", onFrame as any);
      p.removeEventListener("play", onPlay);
      p.removeEventListener("pause", onPause);
    };
  }, [plan?.width, plan?.height, plan?.fps, !!plan]);

  // the timeline asks for a frame (click, drag, keys)
  useEffect(() => {
    const p = ref.current;
    if (p && p.getCurrentFrame() !== getState().frame) p.seekTo(getState().frame);
  }, [seekReq]);

  // play / pause from the keyboard and the transport
  useEffect(() => {
    const onToggle = () => { const p = ref.current; if (p) (p.isPlaying() ? p.pause() : p.play()); };
    window.addEventListener("ai-editor:toggle", onToggle);
    return () => window.removeEventListener("ai-editor:toggle", onToggle);
  }, []);

  const props = useMemo(() => (plan ? { ...plan, __safe: showSafe } : null), [plan, showSafe]);
  if (!plan || !props) {
    return <div className="stage" ref={box}><div className="empty">Nothing to play yet. Drop a video into the bin or onto the timeline.</div></div>;
  }
  const w = plan.width || 1080, h = plan.height || 1920;
  const k = Math.min(size.w / w, size.h / h);
  return (
    <div className="stage" ref={box}>
      <div className="frame" style={{ width: Math.max(1, w * k), height: Math.max(1, h * k) }}>
        <Player
          ref={ref}
          key={`${w}x${h}@${plan.fps}`}
          component={Comp}
          inputProps={props}
          durationInFrames={Math.max(1, plan.durationInFrames || 1)}
          compositionWidth={w}
          compositionHeight={h}
          fps={plan.fps || 30}
          style={{ width: "100%", height: "100%" }}
          controls={false}
          clickToPlay={false}
          doubleClickToFullscreen
          spaceKeyToPlayOrPause={false}
          initialFrame={Math.min(getState().frame, Math.max(0, (plan.durationInFrames || 1) - 1))}
          acknowledgeRemotionLicense
        />
      </div>
    </div>
  );
};
