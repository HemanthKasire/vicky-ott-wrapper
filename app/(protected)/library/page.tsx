"use client";

import { OttHeader } from "@/components/ott-header";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Clapperboard, Film, LoaderCircle, RefreshCw, Search, Star, Tv, XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type LibraryItem = {
  id: string; title: string; type: "movie" | "show";
  year?: number | null; rating?: number | null; genres?: string[]; imageTag?: string;
};
type LibraryPayload = {
  connected: boolean; items: LibraryItem[];
  counts: { all: number; movies: number; shows: number };
  checkedAt?: string;
};
type Filter = "all" | "movie" | "show";

async function readJson(response: Response) {
  const data = await response.json().catch(() => ({})) as LibraryPayload & { error?: string; detail?: string };
  if (!response.ok) throw new Error(data.detail || data.error || "Could not load the Jellyfin catalog");
  return data;
}

export default function LibraryPage() {
  const [catalog, setCatalog] = useState<LibraryPayload | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [visibleCount, setVisibleCount] = useState(60);
  const [loadPosters, setLoadPosters] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const catalogRequest = useRef<AbortController | null>(null);
  const hasCatalog = useRef(false);

  const loadCatalog = useCallback(async (background = false) => {
    if (background && catalogRequest.current) return;
    catalogRequest.current?.abort();
    const controller = new AbortController();
    catalogRequest.current = controller;
    if (!background) { setLoading(true); setError(""); }
    const timeout = window.setTimeout(() => controller.abort(), 40_000);
    try {
      const response = await fetch("/api/library", { cache: "no-store", signal: controller.signal });
      const data = await readJson(response);
      if (catalogRequest.current !== controller) return;
      hasCatalog.current = true;
      setCatalog(data);
      setError("");
    } catch (reason) {
      if (catalogRequest.current !== controller) return;
      if (!background || !hasCatalog.current) {
        setError(reason instanceof Error && reason.name === "AbortError"
          ? "The library request timed out. Try refreshing the catalog."
          : reason instanceof Error ? reason.message : "Could not load the Jellyfin catalog");
      }
    } finally {
      window.clearTimeout(timeout);
      if (catalogRequest.current === controller) {
        catalogRequest.current = null;
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    const initial = window.setTimeout(() => void loadCatalog(), 0);
    const refreshVisible = () => {
      if (document.visibilityState === "visible") void loadCatalog(true);
    };
    const interval = window.setInterval(refreshVisible, 60_000);
    document.addEventListener("visibilitychange", refreshVisible);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", refreshVisible);
      const request = catalogRequest.current;
      catalogRequest.current = null;
      request?.abort();
    };
  }, [loadCatalog]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return (catalog?.items || []).filter((item) => {
      if (filter !== "all" && item.type !== filter) return false;
      if (!needle) return true;
      return `${item.title} ${item.year || ""} ${(item.genres || []).join(" ")}`.toLocaleLowerCase().includes(needle);
    });
  }, [catalog, query, filter]);

  const filters: Array<{ id: Filter; label: string; count: number }> = [
    { id: "all", label: "All", count: catalog?.counts.all || 0 },
    { id: "movie", label: "Movies", count: catalog?.counts.movies || 0 },
    { id: "show", label: "Shows", count: catalog?.counts.shows || 0 },
  ];

  return (
    <main className="min-h-screen bg-[#070b12] text-slate-100 selection:bg-amber-300 selection:text-slate-950">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_18%_-5%,rgba(245,158,11,0.11),transparent_32%),radial-gradient(circle_at_90%_10%,rgba(56,189,248,0.07),transparent_25%)]" />
      <OttHeader connected={catalog?.connected} />

      <section className="relative mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 lg:py-12">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div><p className="flex items-center gap-2 text-sm font-semibold text-amber-300"><Clapperboard className="size-4" />Jellyfin catalog</p><h1 className="mt-2 text-3xl font-bold tracking-[-0.035em] text-white sm:text-5xl">Movies and shows</h1><p className="mt-3 text-base text-slate-400">Search everything currently available in Vicky OTT.</p></div>
          <button type="button" onClick={() => void loadCatalog()} disabled={loading} className="inline-flex h-11 items-center justify-center gap-2 self-start rounded-xl border border-white/[0.1] bg-white/[0.035] px-4 text-sm font-semibold text-slate-300 transition hover:border-white/[0.18] hover:text-white disabled:opacity-50"><RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />Refresh catalog</button>
        </div>

        <div className="mt-8 rounded-3xl border border-white/[0.09] bg-[#0d131e]/85 p-4 sm:p-5">
          <label className="relative block"><Search className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-slate-500" /><span className="sr-only">Search movies and shows</span><input value={query} onChange={(event) => { setQuery(event.target.value); setVisibleCount(60); }} placeholder="Search titles, years or genres" className="h-12 w-full rounded-2xl border border-white/[0.09] bg-[#080d15] pl-12 pr-4 text-base text-white outline-none transition placeholder:text-slate-600 focus:border-amber-400/50 focus:ring-4 focus:ring-amber-400/[0.06]" /></label>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            {filters.map((item) => <button key={item.id} type="button" onClick={() => { setFilter(item.id); setVisibleCount(60); }} className={`rounded-xl px-4 py-2 text-sm font-semibold transition ${filter === item.id ? "bg-amber-400 text-slate-950" : "bg-white/[0.045] text-slate-400 hover:bg-white/[0.08] hover:text-white"}`}>{item.label}<span className={`ml-2 text-xs ${filter === item.id ? "text-slate-700" : "text-slate-600"}`}>{item.count}</span></button>)}
            <label className="ml-auto flex cursor-pointer items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.035] px-3 py-2 text-sm font-semibold text-slate-300 transition hover:border-white/[0.16] hover:text-white">
              <Checkbox checked={loadPosters} onCheckedChange={(checked) => setLoadPosters(checked === true)} className="border-white/25 data-[state=checked]:border-amber-400 data-[state=checked]:bg-amber-400 data-[state=checked]:text-slate-950" />
              <span>Load posters</span>
              <span className={`text-xs ${loadPosters ? "text-amber-300" : "text-slate-600"}`}>{loadPosters ? "On" : "Off"}</span>
            </label>
          </div>
        </div>

        {error && <div className="mt-6 flex items-start gap-3 rounded-2xl border border-rose-400/20 bg-rose-400/[0.07] p-4 text-rose-200"><XCircle className="mt-0.5 size-5 shrink-0" /><div><p className="font-semibold">Library unavailable</p><p className="mt-1 text-sm text-rose-200/75">{error}</p></div></div>}

        {loading ? <div className="mt-12 flex items-center justify-center gap-3 text-slate-400"><LoaderCircle className="size-5 animate-spin text-amber-300" />Loading Jellyfin library…</div> : !error && <>
          <div className="mt-7 flex items-center justify-between gap-4"><p className="text-sm text-slate-500"><strong className="font-semibold text-slate-200">{filtered.length}</strong> {filtered.length === 1 ? "title" : "titles"}</p>{catalog?.checkedAt && <p className="hidden text-xs text-slate-600 sm:block">Live catalog</p>}</div>

          {filtered.length ? <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">{filtered.slice(0, visibleCount).map((item, index) => {
            const palette = ["from-amber-400/20 to-orange-500/5", "from-sky-400/20 to-indigo-500/5", "from-emerald-400/20 to-cyan-500/5", "from-fuchsia-400/20 to-violet-500/5"];
            return <article key={item.id || `${item.title}-${index}`} className="group overflow-hidden rounded-2xl border border-white/[0.08] bg-[#0d131e]/90 transition hover:-translate-y-0.5 hover:border-white/[0.16]">
              <div className={`relative aspect-[2/3] overflow-hidden bg-gradient-to-br ${palette[index % palette.length]}`}>
                <span className="absolute inset-0 flex items-center justify-center text-5xl font-black text-white/80">{item.title.charAt(0).toUpperCase()}</span>
                {/* Poster images are streamed through the authenticated Jellyfin proxy. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                {loadPosters && item.imageTag && <img src={`/api/library/poster?id=${encodeURIComponent(item.id)}&tag=${encodeURIComponent(item.imageTag)}`} alt={`${item.title} poster`} loading="lazy" decoding="async" className="absolute inset-0 h-full w-full object-cover" onError={(event) => { event.currentTarget.style.display = "none"; }} />}
              </div>
              <div className="p-4"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><h2 className="truncate text-base font-bold text-white" title={item.title}>{item.title}</h2><p className="mt-1 text-sm text-slate-500">{item.year || "Year unavailable"}</p></div><span className="shrink-0 rounded-lg bg-white/[0.05] p-2 text-slate-400">{item.type === "movie" ? <Film className="size-4" /> : <Tv className="size-4" />}</span></div>
              <div className="mt-4 flex min-h-5 items-center justify-between gap-2 text-xs"><span className="truncate text-slate-600">{item.genres?.length ? item.genres.join(" · ") : item.type === "movie" ? "Movie" : "TV show"}</span>{item.rating != null && <span className="flex shrink-0 items-center gap-1 text-amber-300"><Star className="size-3 fill-current" />{item.rating}</span>}</div></div>
            </article>;
          })}</div> : <div className="mt-6 rounded-3xl border border-dashed border-white/[0.1] bg-white/[0.02] px-6 py-16 text-center"><Search className="mx-auto size-7 text-slate-600" /><p className="mt-4 font-semibold text-slate-300">No matching titles</p><p className="mt-1 text-sm text-slate-600">Try another title, year or genre.</p></div>}

          {visibleCount < filtered.length && <div className="mt-7 text-center"><button type="button" onClick={() => setVisibleCount((count) => count + 60)} className="h-11 rounded-xl border border-white/[0.1] bg-white/[0.035] px-5 text-sm font-semibold text-slate-300 transition hover:border-white/[0.18] hover:text-white">Show more</button></div>}
        </>}
      </section>
    </main>
  );
}
