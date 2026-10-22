"use client";

import { useEffect } from "react";
import { CheckIcon, XIcon } from "./Icons";

/**
 * A short message that slides in, confirms what just happened, and goes away by itself.
 * `onClose` must be stable (useCallback) or the timer would restart on every render.
 */
export function Toast({ message, onClose, durationMs = 6000 }: { message: string; onClose: () => void; durationMs?: number }) {
  useEffect(() => {
    const timer = setTimeout(onClose, durationMs);
    return () => clearTimeout(timer);
  }, [message, onClose, durationMs]);

  return (
    <div className="toast" role="status">
      <span className="toast-icon">
        <CheckIcon size={16} />
      </span>
      <span>{message}</span>
      <button type="button" className="toast-close" onClick={onClose} aria-label="Dismiss message">
        <XIcon size={16} />
      </button>
    </div>
  );
}
