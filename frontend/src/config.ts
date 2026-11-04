// Mocked authentication (Requirement 1): dummy credentials checked in the
// browser. This is NOT a security boundary and there is no Cognito; it only
// gates the demo flow. Override with VITE_* variables (see .env.example).
const env = import.meta.env;

export const DEMO_CREDENTIALS = {
  org: { user: env.VITE_ORG_USER ?? "demo", password: env.VITE_ORG_PASSWORD ?? "demo123" },
  staff: { user: env.VITE_STAFF_USER ?? "staff", password: env.VITE_STAFF_PASSWORD ?? "staff123" },
};

export function checkCredentials(role: "org" | "staff", user: string, password: string): boolean {
  const c = DEMO_CREDENTIALS[role];
  return user.trim() === c.user && password === c.password;
}

export const sessionStore = {
  get<T>(key: string, fallback: T): T {
    try {
      const value = window.sessionStorage.getItem(key);
      return value ? (JSON.parse(value) as T) : fallback;
    } catch {
      return fallback;
    }
  },
  set(key: string, value: unknown) {
    try {
      window.sessionStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* storage unavailable: state stays in memory */
    }
  },
  remove(key: string) {
    try {
      window.sessionStorage.removeItem(key);
    } catch {
      /* ignore */
    }
  },
};

export const storage = {
  get<T>(key: string, fallback: T): T {
    try {
      const v = window.localStorage.getItem(key);
      return v ? (JSON.parse(v) as T) : fallback;
    } catch {
      return fallback;
    }
  },
  set(key: string, value: unknown) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* storage unavailable: state stays in memory */
    }
  },
  remove(key: string) {
    try {
      window.localStorage.removeItem(key);
    } catch {
      /* ignore */
    }
  },
};
