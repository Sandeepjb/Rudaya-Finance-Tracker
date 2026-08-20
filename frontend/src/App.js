import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/lib/auth";
import { Toaster } from "@/components/ui/sonner";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import Transactions from "@/pages/Transactions";
import ProjectPnl from "@/pages/ProjectPnl";
import Monthly from "@/pages/Monthly";
import Forecast from "@/pages/Forecast";
import SalesForecast from "@/pages/SalesForecast";
import Settings from "@/pages/Settings";

function Protected({ children }) {
  const { user } = useAuth();
  if (user === null) return <div className="min-h-screen flex items-center justify-center text-sm text-neutral-500">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function GuestOnly({ children }) {
  const { user } = useAuth();
  if (user === null) return <div className="min-h-screen flex items-center justify-center text-sm text-neutral-500">Loading…</div>;
  if (user) return <Navigate to="/" replace />;
  return children;
}

function App() {
  return (
    <div className="App">
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<GuestOnly><Login mode="login" /></GuestOnly>} />
            <Route path="/register" element={<GuestOnly><Login mode="register" /></GuestOnly>} />
            <Route path="/" element={<Protected><Dashboard /></Protected>} />
            <Route path="/transactions" element={<Protected><Transactions /></Protected>} />
            <Route path="/project-pnl" element={<Protected><ProjectPnl /></Protected>} />
            <Route path="/monthly" element={<Protected><Monthly /></Protected>} />
            <Route path="/forecast" element={<Protected><Forecast /></Protected>} />
            <Route path="/sales-forecast" element={<Protected><SalesForecast /></Protected>} />
            <Route path="/settings" element={<Protected><Settings /></Protected>} />
          </Routes>
          <Toaster position="top-right" />
        </BrowserRouter>
      </AuthProvider>
    </div>
  );
}

export default App;
