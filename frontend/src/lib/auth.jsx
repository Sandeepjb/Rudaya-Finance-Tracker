import React, { createContext, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // null=loading, false=guest, obj=user
  useEffect(() => {
    api.get("/auth/me")
      .then((r) => setUser(r.data.user))
      .catch(() => setUser(false));
  }, []);
  const login = async (email, password) => {
    const r = await api.post("/auth/login", { email, password });
    if (r.data.token) localStorage.setItem("token", r.data.token);
    setUser(r.data.user);
    return r.data.user;
  };
  const register = async (email, password, name) => {
    const r = await api.post("/auth/register", { email, password, name });
    if (r.data.token) localStorage.setItem("token", r.data.token);
    setUser(r.data.user);
    return r.data.user;
  };
  const logout = async () => {
    try { await api.post("/auth/logout"); } catch {}
    localStorage.removeItem("token");
    setUser(false);
  };
  return <AuthCtx.Provider value={{ user, login, register, logout }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
