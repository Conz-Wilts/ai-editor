// What just happened: Claude's edits (with Undo), Claude's proposals (Accept / Reject), and errors.
import React from "react";
import { dismiss, proposal, undo, useStore } from "./store";

export const ChangeToasts: React.FC = () => {
  const toasts = useStore((s) => s.toasts);
  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`}>
          <span>{t.text}</span>
          {t.proposal ? (
            <>
              <button className="primary" onClick={() => proposal(t.proposal!.id, true)}>Accept</button>
              <button onClick={() => proposal(t.proposal!.id, false)}>Reject</button>
            </>
          ) : t.undoAuthor ? (
            <button onClick={() => { undo(t.undoAuthor); dismiss(t.id); }}>Undo</button>
          ) : null}
          <button className="x" aria-label="Dismiss" onClick={() => dismiss(t.id)}>×</button>
        </div>
      ))}
    </div>
  );
};
