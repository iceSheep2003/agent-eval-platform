import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { getSession, portalLogin, portalLogout, type PortalSession } from './api/portal';

interface SessionState {
  loading: boolean;
  session: PortalSession | null;
  login: (identifier: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [session, setSession] = useState<PortalSession | null>(null);

  const refresh = useCallback(async () => {
    try {
      setSession(await getSession());
    } catch {
      // 未登录是正常状态，不弹错
      setSession(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<SessionState>(
    () => ({
      loading,
      session,
      login: async (identifier, password) => {
        setSession(await portalLogin(identifier, password));
      },
      logout: async () => {
        await portalLogout();
        setSession(null);
      },
    }),
    [loading, session],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionState {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error('useSession 必须在 SessionProvider 内使用');
  }
  return value;
}
