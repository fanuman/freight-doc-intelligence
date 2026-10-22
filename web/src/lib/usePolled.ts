import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { errorMessage, isUnauthorized } from "./api";

/**
 * Load something from the API and keep it fresh while it is still changing.
 *
 * - `fetcher` must be stable (wrap it in useCallback), or the effect would restart on every render.
 * - `keepPolling(value)` says whether the server is still working; if so, ask again after `intervalMs`.
 * - A 401 sends the person to the login page. Any other error is returned as text, and polling stops.
 * - `reload()` fetches again right now (after an upload, a review, a reconcile, or the Retry button).
 */
export function usePolled<T>(fetcher: () => Promise<T>, keepPolling: (value: T) => boolean, intervalMs = 3000) {
  const router = useRouter();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function load() {
      try {
        const value = await fetcher();
        if (cancelled) return;
        setData(value);
        setError(null);
        if (keepPolling(value)) timer = setTimeout(load, intervalMs);
      } catch (err) {
        if (cancelled) return;
        if (isUnauthorized(err)) router.replace("/login");
        else setError(errorMessage(err));
      }
    }

    load();
    return () => {
      cancelled = true; // a later response must not overwrite a newer page
      if (timer) clearTimeout(timer);
    };
  }, [fetcher, keepPolling, intervalMs, router, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { data, error, reload };
}
