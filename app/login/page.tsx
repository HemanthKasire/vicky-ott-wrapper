"use client";

import { Film, LoaderCircle, LockKeyhole, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

export default function LoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!password || loading) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ password }),
      });
      const data = await response.json().catch(() => ({})) as { error?: string };
      if (!response.ok) throw new Error(data.error || "Sign-in failed");
      router.replace("/");
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Sign-in failed");
      setLoading(false);
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-[#070b12] px-4 py-12 text-slate-100 selection:bg-amber-300 selection:text-slate-950">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_50%_-10%,rgba(245,158,11,0.15),transparent_38%),radial-gradient(circle_at_95%_90%,rgba(56,189,248,0.06),transparent_28%)]" />
      <section className="relative w-full max-w-md overflow-hidden rounded-3xl border border-white/[0.09] bg-[#0d131e]/95 p-6 shadow-2xl shadow-black/35 sm:p-8">
        <div className="flex items-center gap-3">
          <span className="grid size-11 place-items-center rounded-2xl bg-amber-400 text-slate-950"><Film className="size-6" /></span>
          <div><p className="text-lg font-bold text-white">Vicky OTT</p><p className="text-xs uppercase tracking-[0.18em] text-slate-500">Private request console</p></div>
        </div>

        <div className="mt-8"><p className="flex items-center gap-2 text-sm font-semibold text-amber-300"><ShieldCheck className="size-4" />Family access</p><h1 className="mt-2 text-3xl font-bold tracking-[-0.035em] text-white">Enter the portal</h1><p className="mt-2 text-sm leading-6 text-slate-400">Use the access password shared by the server owner.</p></div>

        <form onSubmit={submit} className="mt-7">
          <label className="block text-sm font-semibold text-slate-300" htmlFor="portal-password">Access password</label>
          <div className="relative mt-2"><LockKeyhole className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-slate-600" /><input id="portal-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" autoFocus required className="h-12 w-full rounded-2xl border border-white/[0.09] bg-[#080d15] pl-12 pr-4 text-base text-white outline-none transition placeholder:text-slate-700 focus:border-amber-400/50 focus:ring-4 focus:ring-amber-400/[0.06]" placeholder="Enter password" /></div>
          {error && <p className="mt-3 text-sm text-rose-300" role="alert">{error}</p>}
          <button type="submit" disabled={loading || !password} className="mt-5 inline-flex h-12 w-full items-center justify-center gap-2 rounded-2xl bg-amber-400 px-5 text-sm font-bold text-slate-950 transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-50">{loading ? <LoaderCircle className="size-4 animate-spin" /> : <LockKeyhole className="size-4" />}{loading ? "Checking access…" : "Sign in"}</button>
        </form>

        <p className="mt-6 text-center text-xs text-slate-600">Protected access · Credentials are never sent to Jellyfin or qBittorrent</p>
      </section>
    </main>
  );
}
