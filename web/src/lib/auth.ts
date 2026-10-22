// Where the login token is kept in the browser.
//
// sessionStorage lives as long as the tab: close the tab and you are signed out. That is simple and fine for
// a demo, but any script running on the page could read it (cross-site scripting). A production app would
// keep the token in an httpOnly cookie that JavaScript cannot read. Every access is wrapped in try/catch
// because browsers can block storage (private windows, strict settings).

const KEY = "freightlens_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null; // during server rendering there is no browser
  try {
    return window.sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    window.sessionStorage.setItem(KEY, token);
  } catch {
    // storage blocked: the user has to sign in again on the next page load
  }
}

export function clearToken(): void {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // nothing to clear
  }
}
