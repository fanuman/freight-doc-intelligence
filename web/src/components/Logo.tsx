/**
 * The FreightLens mark: a container seen end-on (its corrugated ribs) through a magnifying lens.
 * Hull-navy tile, hi-vis yellow ring and handle, white ribs. The same drawing is in src/app/icon.svg (the favicon).
 */
export function LogoMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label="FreightLens" className="logo-mark">
      <rect width="32" height="32" rx="7" fill="#0E2A43" />
      <circle cx="15" cy="15" r="8.5" fill="none" stroke="#F4B71A" strokeWidth="2.6" />
      <path d="M11.5 11.5v7M15 11.5v7M18.5 11.5v7" stroke="#FFFFFF" strokeWidth="1.8" strokeLinecap="round" />
      <path d="m21.2 21.2 5 5" stroke="#F4B71A" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

/** Mark + name. `onDark` switches the name to white for the navy bars. */
export function Wordmark({ size = 32, onDark = false }: { size?: number; onDark?: boolean }) {
  return (
    <span className={onDark ? "wordmark wordmark-dark" : "wordmark"}>
      <LogoMark size={size} />
      <span className="wordmark-text">FreightLens</span>
    </span>
  );
}
