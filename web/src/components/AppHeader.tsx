"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getMe, isUnauthorized, signOut } from "@/lib/api";
import { initials } from "@/lib/format";
import type { MeResponse } from "@/lib/types";
import { Wordmark } from "./Logo";

/** The navy bar at the top of every signed-in page: the logo, who you are, and Sign out. */
export function AppHeader() {
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((value) => {
        if (!cancelled) setMe(value);
      })
      .catch((err) => {
        if (!cancelled && isUnauthorized(err)) router.replace("/login");
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  function handleSignOut() {
    signOut();
    router.push("/login");
  }

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link href="/" className="topbar-brand" aria-label="FreightLens, all documents">
          <Wordmark onDark />
        </Link>
        <div className="topbar-user">
          {me && (
            <>
              <span className="avatar" aria-hidden="true">
                {initials(me.tenant_name)}
              </span>
              <span className="topbar-who">
                <strong>{me.tenant_name}</strong>
                <span>{me.email}</span>
              </span>
            </>
          )}
          <button type="button" className="btn btn-quiet-dark" onClick={handleSignOut}>
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
