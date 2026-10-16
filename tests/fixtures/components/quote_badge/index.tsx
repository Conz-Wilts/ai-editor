import React from "react";
import { useTl, dropIn, exitUp, textCase, type TP } from "../../component-api";

// A sample user component: the quote on a badge in the design system's ink or accent, dropping in and leaving up.
const QuoteBadge: React.FC<TP> = ({ p, w, h, look, m, fonts, dur }) => {
  const accent = p.tone === "accent";
  const ref = useTl((tl, q) => {
    dropIn(tl, q(".qb")[0], 0, m, h * 0.2);
    exitUp(tl, q(".qb")[0], m, dur, h * 0.2);
  }, [p.text, p.tone, w, h, dur, m.name]);
  return (
    <div ref={ref} style={{ position: "relative", width: w, height: h, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className="qb" style={{ padding: `${h * 0.12}px ${h * 0.3}px`, borderRadius: h, opacity: 0,
        background: accent ? look.accent : look.ink, color: accent ? look.accent_ink : look.ground,
        fontFamily: fonts.body, fontWeight: look.weight, fontSize: h * 0.32, whiteSpace: "nowrap" }}>
        {textCase(String(p.text ?? ""), look)}
      </div>
    </div>
  );
};
export default QuoteBadge;
