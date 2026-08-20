import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // null=loading, false=guest, obj=user

  useEffect(() => {
    let alive = true;
    api
      .get("/auth/me")
      .then((r) => { if (alive) setUser(r.data.user); })
      .catch(() => { if (alive) setUser(false); });
    return () => { alive = false; };
  }, []);

  const login = useCallback(async (email, password) => {
    const r = await api.post("/auth/login", { email, password });
    setUser(r.data.user);
    return r.data.user;
  }, []);

  const register = useCallback(async (email, password, name) => {
    const r = await api.post("/auth/register", { email, password, name });
    setUser(r.data.user);
    return r.data.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } catch (error) {
      console.error("Logout request failed:", error);
    }
    setUser(false);
  }, []);

  return <AuthCtx.Provider value={{ user, login, register, logout }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
