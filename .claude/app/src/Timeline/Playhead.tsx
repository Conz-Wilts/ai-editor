// The playhead line over every track. It alone follows the frame, so playing never re-renders the tracks.
import React from "react";
import { useStore } from "../store";

export const Playhead: React.FC<{ offset: number; ppf: number }> = ({ offset, ppf }) => {
  const frame = useStore((s) => s.frame);
  return <div className="playhead" style={{ left: offset + frame * ppf }}><i /></div>;
};
