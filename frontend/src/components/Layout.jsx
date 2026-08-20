import React from "react";
import Sidebar from "@/components/Sidebar";

export default function Layout({ title, subtitle, actions, children }) {
  return (
    <div className="flex bg-neutral-100 min-h-screen">
      <Sidebar />
      <main className="flex-1 min-w-0">
        <header className="bg-white border-b border-neutral-200 sticky top-0 z-30">
          <div className="px-8 py-5 flex items-center justify-between">
            <div>
              <div className="text-[11px] uppercase tracking-[0.25em] text-neutral-500">Rudaya Powers Pvt. Ltd.</div>
              <h1 className="font-heading text-2xl font-bold tracking-tight text-neutral-900" data-testid="page-title">{title}</h1>
              {subtitle && <div className="text-sm text-neutral-500 mt-0.5">{subtitle}</div>}
            </div>
            <div className="flex items-center gap-3">{actions}</div>
          </div>
        </header>
        <div className="p-8 rudaya-scroll">{children}</div>
      </main>
    </div>
  );
}
