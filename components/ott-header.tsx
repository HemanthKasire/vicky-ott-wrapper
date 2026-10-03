"use client";

import { Clapperboard, Film, LogOut, PlusCircle } from "lucide-react";
import { usePathname } from "next/navigation";

export function OttHeader({ connected }: { connected?: boolean }) {
  const pathname = usePathname();
  const links = [
    { href: "/", label: "Request", icon: PlusCircle },
    { href: "/library", label: "Library", icon: Clapperboard },
  ];

  return (
    <header className="relative border-b border-white/[0.07] bg-[#070b12]/80 backdrop-blur-xl">
      <div className="mx-auto flex min-h-16 max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6 lg:px-8">
        <div className="flex items-center gap-3">
          <span className="grid size-9 place-items-center rounded-xl bg-amber-400 text-slate-950"><Film className="size-5" /></span>
          <div><p className="text-sm font-bold">Vicky OTT</p><p className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Request console</p></div>
        </div>

        <nav className="order-3 flex w-full rounded-xl border border-white/[0.08] bg-white/[0.025] p-1 sm:order-none sm:w-auto" aria-label="Portal sections">
          {links.map(({ href, label, icon: Icon }) => {
            const active = pathname === href;
            return <a key={href} href={href} className={`flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition sm:flex-none ${active ? "bg-amber-400 text-slate-950" : "text-slate-400 hover:bg-white/[0.05] hover:text-white"}`}><Icon className="size-4" />{label}</a>;
          })}
        </nav>

        <div className="flex items-center gap-3">
          {typeof connected === "boolean" && <span className={`hidden items-center gap-2 rounded-full border px-3 py-1.5 text-xs lg:flex ${connected ? "border-emerald-400/20 text-emerald-300" : "border-rose-400/20 text-rose-300"}`}><span className={`size-1.5 rounded-full ${connected ? "bg-emerald-400" : "bg-rose-400"}`} />{connected ? "OCI connected" : "Bridge offline"}</span>}
          <a href="/api/auth/logout" className="grid size-9 place-items-center rounded-xl border border-white/[0.08] text-slate-400 transition hover:border-white/[0.16] hover:text-white" aria-label="Sign out"><LogOut className="size-4" /></a>
        </div>
      </div>
    </header>
  );
}
