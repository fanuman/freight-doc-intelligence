// Small display helpers. No React in here, so they are easy to test and reuse.

const FALLBACK_DIGITS = 2;

/** 219000 + "USD" -> "$2,190.00". The API sends integers in minor units; the number of decimals depends on the currency. */
export function formatMoney(minor: number | null | undefined, currency: string | null | undefined): string {
  if (minor === null || minor === undefined) return "—";
  const code = currency && /^[A-Za-z]{3}$/.test(currency) ? currency.toUpperCase() : null;
  if (code) {
    try {
      const formatter = new Intl.NumberFormat("en-US", { style: "currency", currency: code });
      const digits = formatter.resolvedOptions().maximumFractionDigits ?? FALLBACK_DIGITS;
      return formatter.format(minor / 10 ** digits);
    } catch {
      // an unknown currency code: fall through to the plain format below
    }
  }
  const plain = (minor / 10 ** FALLBACK_DIGITS).toFixed(FALLBACK_DIGITS);
  return code ? `${plain} ${code}` : plain;
}

/** Like formatMoney, but a difference always shows its sign: "+$5.00" or "-$12.50". */
export function formatVariance(minor: number | null | undefined, currency: string | null | undefined): string {
  if (minor === null || minor === undefined) return "—";
  const text = formatMoney(minor, currency);
  return minor > 0 ? `+${text}` : text;
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

/** "invoice.PDF" -> "PDF". Anything we do not know is shown as "DOC". */
export function fileKind(filename: string): "PDF" | "XLS" | "EML" | "DOC" {
  const extension = filename.split(".").pop()?.toLowerCase();
  if (extension === "pdf") return "PDF";
  if (extension === "xlsx" || extension === "xls") return "XLS";
  if (extension === "eml") return "EML";
  return "DOC";
}

/** "2 minutes ago", "yesterday", "3 Oct 2026" (older than a week). */
export function formatRelative(iso: string, now: number = Date.now()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const seconds = Math.round((then - now) / 1000); // negative = in the past
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  const abs = Math.abs(seconds);
  if (abs < 45) return "just now";
  if (abs < 3600) return formatter.format(Math.round(seconds / 60), "minute");
  if (abs < 86400) return formatter.format(Math.round(seconds / 3600), "hour");
  if (abs < 7 * 86400) return formatter.format(Math.round(seconds / 86400), "day");
  return new Date(then).toLocaleDateString("en", { day: "numeric", month: "short", year: "numeric" });
}

/** Up to two capital letters for an avatar: "Saltmarsh Trade Co." -> "ST". */
export function initials(name: string): string {
  const words = name.split(/\s+/).filter((word) => /^[A-Za-z0-9]/.test(word));
  if (words.length === 0) return "?";
  return (words.length === 1 ? words[0].slice(0, 2) : words[0][0] + words[1][0]).toUpperCase();
}

/** "needs_review" -> "needs review" */
export function humanize(value: string): string {
  return value.replace(/_/g, " ");
}

/** "needs_review" -> "Needs review" */
export function sentence(value: string): string {
  const text = humanize(value);
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Statuses where the server is still working, so a page should keep asking for news. */
const BUSY = new Set(["uploaded", "processing"]);

export function isBusy(status: string): boolean {
  return BUSY.has(status);
}

export type Tone = "good" | "warn" | "bad" | "busy" | "neutral";

export function statusTone(status: string): Tone {
  switch (status) {
    case "processed":
    case "ok":
    case "reviewed":
    case "clean":
      return "good";
    case "needs_review":
    case "has_discrepancies":
      return "warn";
    case "failed":
    case "rejected":
      return "bad";
    case "uploaded":
    case "processing":
      return "busy";
    default:
      return "neutral";
  }
}
