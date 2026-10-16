import React from "react";
import { Audio, Sequence, getInputProps, staticFile, useVideoConfig } from "remotion";

// plan.json "sfx": [{"t": seconds, "src": ".sfx/whoosh-in.wav"}]. Level is baked into each file
// by sfx.py (Remotion clamps <Audio volume> to 1), so every cue plays at volume 1.
type Cue = { t: number; src: string };
type Music = { src: string };

// plan.json "music": {"src": ".sfx/music.wav"}: the bed sfx.py music wrote, levelled and ducked under the speech.
// StyleEdit hands both over as props (a <Player> has no input props); with neither, a render reads them itself.
export const Sfx: React.FC<{ sfx?: Cue[]; music?: Music }> = (given) => {
  const { fps } = useVideoConfig();
  let props: { sfx?: Cue[]; music?: Music } = given;
  if (given.sfx === undefined && given.music === undefined) {
    try {
      props = getInputProps() as typeof props;
    } catch {
      props = {};
    }
  }
  const cues = props.sfx ?? [];
  return (
    <>
      {props.music?.src ? <Audio src={staticFile(props.music.src)} /> : null}
      {cues.filter((c) => c.src).map((c) => (
        <Sequence key={`${c.src}${c.t}`} from={Math.round(c.t * fps)} layout="none">
          <Audio src={staticFile(c.src)} />
        </Sequence>
      ))}
    </>
  );
};
