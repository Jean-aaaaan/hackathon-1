"use client";

import { useState } from "react";
import { NavBar } from "./navbar";
import { Sidebar } from "./sidebar";
import { HelpAssistant } from "@/components/help/help-assistant";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-white">
      <NavBar onMobileMenuClick={() => setSidebarOpen(o => !o)} />

      {/* Mobile sidebar drawer */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <div className={`
        fixed inset-y-0 left-0 z-50 md:hidden
        transition-transform duration-200
        ${sidebarOpen ? "translate-x-0" : "-translate-x-full"}
      `}>
        <Sidebar onClose={() => setSidebarOpen(false)} />
      </div>

      <main className="flex-1 overflow-y-auto bg-white">
        {children}
      </main>

      <HelpAssistant />
    </div>
  );
}
