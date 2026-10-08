"use client";

import {
  AlertTriangle, CheckCircle2, CircleGauge, HardDrive, Link2,
  LoaderCircle, Plus, RefreshCw, Server, ShieldCheck, XCircle,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { OttHeader } from "@/components/ott-header";

type Storage = {
  id: string; label: string; totalBytes: number; usedBytes: number;
  availableBytes: number; mounted: boolean; healthy?: boolean;
};
type ManualImport = { title: string; season: number; episode?: number | null; state: string; message: string };
type StatusPayload = {
  manualImports?: ManualImport[];
  connected: boolean; storage: Storage[];
  queue?: { downloading: number; seeding: number; paused: number };
};
type AddPayload = {
  queued: boolean; storageFull?: boolean; storageUsagePercent?: number; message?: string;
};
type Series = { tvdbId: number; title: string; year?: number };
type ApiError = { error?: string; detail?: string };

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), 4);
  const value = bytes / 1024 ** index;
  return `${value.toFixed(value >= 100 || index === 0 ? 0 : value >= 10 ? 1 : 2)} ${units[index]}`;
}

function usagePercent(storage: Storage) {
  return storage.totalBytes ? Math.min(100, Math.max(0, storage.usedBytes / storage.totalBytes * 100)) : 100;
}

async function readJson<T>(response: Response): Promise<T> {
  const data = (await response.json().catch(() => ({}))) as T & ApiError;
  if (!response.ok) throw new Error(data.detail || data.error || "Request failed");
  return data;
}

function StorageCard({ storage }: { storage: Storage }) {
  const used = usagePercent(storage);
  const full = used >= 95;
  return (
    <div className={`rounded-2xl border p-4 ${full ? "border-rose-400/25 bg-rose-400/[0.055]" : "border-white/[0.08] bg-white/[0.025]"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className={`grid size-9 shrink-0 place-items-center rounded-xl ${full ? "bg-rose-400/10 text-rose-300" : "bg-white/[0.05] text-slate-400"}`}><HardDrive className="size-4" /></span>
          <div className="min-w-0"><p className="truncate text-sm font-semibold text-slate-100">{storage.label}</p><p className="mt-0.5 text-xs text-slate-500">{storage.mounted ? `${formatBytes(storage.availableBytes)} free` : "Not mounted"}</p></div>
        </div>
        <span className={`mt-1 size-2 rounded-full ${storage.mounted && !full ? "bg-emerald-400" : "bg-rose-400"}`} />
      </div>
      <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-white/[0.06]"><div className={`h-full rounded-full ${full ? "bg-rose-400" : "bg-amber-400"}`} style={{ width: `${used}%` }} /></div>
      <div className="mt-2 flex justify-between text-[11px] text-slate-500"><span>{used.toFixed(0)}% used</span><span>{formatBytes(storage.usedBytes)} / {formatBytes(storage.totalBytes)}</span></div>
      {full && <p className="mt-3 flex items-start gap-2 text-xs text-rose-200"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" />Requests pause automatically at 95% usage.</p>}
    </div>
  );
}

export default function Home() {
  const [magnet, setMagnet] = useState("");
  const [mediaType, setMediaType] = useState<"movie" | "show">("movie");
  const [showQuery, setShowQuery] = useState("");
  const [tvMode, setTvMode] = useState<"search" | "manual">("search");
  const [manualTitle, setManualTitle] = useState("");
  const [manualSeason, setManualSeason] = useState("1");
  const [manualEpisode, setManualEpisode] = useState("");
  const manualValid = Boolean(manualTitle.trim()) && /^\d{1,3}$/.test(manualSeason) && (manualEpisode === "" || (/^\d{1,4}$/.test(manualEpisode) && Number(manualEpisode) > 0));
  const [series, setSeries] = useState<Series[]>([]);
  const [selectedSeries, setSelectedSeries] = useState<Series | null>(null);
  const tvReady = tvMode === "manual" ? manualValid : Boolean(selectedSeries);
  const [searching, setSearching] = useState(false);
  const [showError, setShowError] = useState("");
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [statusError, setStatusError] = useState("");
  const [statusBusy, setStatusBusy] = useState(false);
  const [addBusy, setAddBusy] = useState(false);
  const [skipConnectionCheck, setSkipConnectionCheck] = useState(false);
  const statusRequest = useRef<AbortController | null>(null);
  const controlsBusy = addBusy || (statusBusy && !skipConnectionCheck);
  const [notice, setNotice] = useState<{ kind: "success" | "error"; text: string } | null>(null);

  const loadStatus = useCallback(async () => {
    statusRequest.current?.abort();
    const controller = new AbortController();
    statusRequest.current = controller;
    setStatusBusy(true);
    const timeout = window.setTimeout(() => controller.abort(), 20_000);
    try {
      const response = await fetch("/api/torrent/status", { cache: "no-store", signal: controller.signal });
      const data = await readJson<StatusPayload>(response);
      if (statusRequest.current !== controller) return;
      setStatus(data);
      setStatusError(data.connected ? "" : "The connection check could not confirm OCI is available.");
    } catch (error) {
      if (statusRequest.current !== controller) return;
      setStatusError(error instanceof Error && error.name === "AbortError"
        ? "The connection check timed out. You can skip it and try adding your torrent."
        : error instanceof Error ? error.message : "Could not reach the OCI bridge");
    } finally {
      window.clearTimeout(timeout);
      if (statusRequest.current === controller) {
        statusRequest.current = null;
        setStatusBusy(false);
      }
    }
  }, []);

  function skipCheck() {
    const request = statusRequest.current;
    statusRequest.current = null;
    request?.abort();
    setStatusBusy(false);
    setSkipConnectionCheck(true);
  }

  useEffect(() => {
    const timer = window.setTimeout(() => void loadStatus(), 0);
    return () => {
      window.clearTimeout(timer);
      statusRequest.current?.abort();
      statusRequest.current = null;
    };
  }, [loadStatus]);

  async function searchShows() {
    setSearching(true);
    setShowError("");
    setSeries([]);
    setSelectedSeries(null);
    try {
      const response = await fetch("/api/torrent/series", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ query: showQuery.trim() }),
      });
      const data = await readJson<{ items: Series[] }>(response);
      setSeries(data.items);
      if (!data.items.length) setShowError("No shows found. Try another title.");
    } catch (error) {
      setShowError(error instanceof Error ? error.message : "Could not search shows");
    } finally { setSearching(false); }
  }

  async function addTorrent() {
    const trimmed = magnet.trim();
    setNotice(null);
    if (!trimmed.toLowerCase().startsWith("magnet:?")) {
      setNotice({ kind: "error", text: "Paste a magnet link beginning with magnet:?" });
      return;
    }
    if (mediaType === "show" && !tvReady) {
      setNotice({ kind: "error", text: "Select a TV show or enter its title and season manually." });
      return;
    }
    if (addBusy) return;
    setAddBusy(true);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 60_000);
    try {
      const response = await fetch("/api/torrent/add", {
        method: "POST",
        signal: controller.signal,
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ magnet: trimmed, mediaType, ...(mediaType === "show" ? tvMode === "manual" ? { manualTV: { title: manualTitle.trim(), season: Number(manualSeason), episode: manualEpisode === "" ? null : Number(manualEpisode) } } : { tvdbId: selectedSeries?.tvdbId } : {}) }),
      });
      const data = await readJson<AddPayload>(response);
      if (data.storageFull || !data.queued) {
        setNotice({ kind: "error", text: data.message || "Storage is 95% full. Please try again later." });
      } else {
        setNotice({ kind: "success", text: data.message || "Torrent request was added to the download queue." });
        setMagnet("");
      }
      if (!skipConnectionCheck) void loadStatus();
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error && error.name === "AbortError"
        ? "No add response arrived in time. The torrent may still have been added. Check qBittorrent before retrying."
        : error instanceof Error ? error.message : "Could not add torrent" });
    } finally {
      window.clearTimeout(timeout);
      setAddBusy(false);
    }
  }

  const storage = status?.storage || [];

  return (
    <main className="min-h-screen bg-[#070b12] text-slate-100 selection:bg-amber-300 selection:text-slate-950">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_18%_-5%,rgba(245,158,11,0.11),transparent_32%),radial-gradient(circle_at_90%_10%,rgba(56,189,248,0.07),transparent_25%)]" />
      <OttHeader connected={status?.connected} />

      <div className="relative mx-auto grid max-w-7xl gap-6 px-4 py-8 sm:px-6 lg:grid-cols-[minmax(0,1fr)_360px] lg:px-8 lg:py-12">
        <section>
          <div className="mb-8 max-w-3xl"><h1 className="text-3xl font-bold tracking-[-0.035em] text-white sm:text-5xl">Add a movie or TV show.</h1><p className="mt-4 max-w-2xl text-sm leading-6 text-slate-400 sm:text-base">Choose a movie or TV show and paste a magnet link. TV episodes are automatically organised into show and season folders after downloading.</p></div>
          <div className="rounded-3xl border border-white/[0.09] bg-[#0d131e]/90 p-5 shadow-[0_30px_80px_rgb(0_0_0/35%)] sm:p-7">
            <fieldset className="mb-5" disabled={controlsBusy || searching}>
              <legend className="mb-2 text-sm font-semibold">What are you adding?</legend>
              <div className="flex gap-3">{([["movie", "Movie"], ["show", "TV Show"]] as const).map(([value, label]) => (
                <label key={value} className="flex cursor-pointer items-center gap-2 rounded-xl border border-white/10 px-4 py-3 text-sm">
                  <input type="radio" name="mediaType" value={value} checked={mediaType === value} onChange={() => { setMediaType(value); setNotice(null); }} className="accent-amber-400" />{label}
                </label>
              ))}</div>
            </fieldset>
            {mediaType === "show" && <fieldset className="mb-5 flex flex-wrap gap-3" disabled={controlsBusy || searching}>
              <legend className="mb-2 text-sm font-semibold">Show details</legend>
              {([["search", "Search for a show"], ["manual", "Enter manually"]] as const).map(([value, label]) => <label key={value} className="flex cursor-pointer items-center gap-2 text-sm text-slate-300"><input type="radio" name="tvMode" checked={tvMode === value} onChange={() => { setTvMode(value); setNotice(null); }} className="accent-amber-400" />{label}</label>)}
            </fieldset>}
            {mediaType === "show" && tvMode === "manual" && <fieldset className="mb-5 space-y-3" disabled={controlsBusy}>
              <div><label htmlFor="manual-title" className="mb-2 block text-sm font-semibold">TV show title</label><input id="manual-title" value={manualTitle} maxLength={120} onChange={(event) => setManualTitle(event.target.value)} placeholder="Example Show (2024)" className="w-full rounded-xl border border-white/10 bg-[#080d15] px-4 py-3 text-sm" /></div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div><label htmlFor="manual-season" className="mb-2 block text-sm font-semibold">Season number</label><input id="manual-season" type="number" min={0} max={999} step={1} value={manualSeason} onChange={(event) => setManualSeason(event.target.value)} className="w-full rounded-xl border border-white/10 bg-[#080d15] px-4 py-3 text-sm" /></div>
                <div><label htmlFor="manual-episode" className="mb-2 block text-sm font-semibold">Episode number <span className="font-normal text-slate-500">(optional)</span></label><input id="manual-episode" type="number" min={1} max={9999} step={1} value={manualEpisode} onChange={(event) => setManualEpisode(event.target.value)} placeholder="Leave blank for multiple episodes" className="w-full rounded-xl border border-white/10 bg-[#080d15] px-4 py-3 text-sm" /></div>
              </div>
              <p className="text-xs leading-5 text-slate-500">Enter an episode number only for a single episode torrent. Leave it blank for a folder or season pack: episode numbers will be read from filenames such as S01E02, E02, or 02 - Title. Files that cannot be matched will be kept for review.</p>
            </fieldset>}
            {mediaType === "show" && tvMode === "search" && <div className="mb-5">
              <label htmlFor="show-search" className="mb-2 block text-sm font-semibold">Find your show</label>
              <div className="flex gap-2">
                <input id="show-search" value={showQuery} disabled={searching || controlsBusy} onChange={(event) => { setShowQuery(event.target.value); setSelectedSeries(null); setSeries([]); }} onKeyDown={(event) => { if (event.key === "Enter" && showQuery.trim().length >= 2 && !searching) void searchShows(); }} placeholder="Enter the show title" maxLength={120} className="min-w-0 flex-1 rounded-xl border border-white/10 bg-[#080d15] px-4 py-3 text-sm" />
                <button type="button" onClick={() => void searchShows()} disabled={searching || controlsBusy || showQuery.trim().length < 2} className="rounded-xl bg-white/10 px-4 text-sm disabled:opacity-40">{searching ? "Searching…" : "Search"}</button>
              </div>
              {showError && <p role="alert" className="mt-2 text-sm text-rose-200">{showError}</p>}
              {series.length > 0 && <div className="mt-3 max-h-56 space-y-2 overflow-y-auto" role="radiogroup" aria-label="Matching shows">{series.map((show) => (
                <label key={show.tvdbId} className={`flex cursor-pointer items-center gap-3 rounded-xl border px-4 py-3 text-sm ${selectedSeries?.tvdbId === show.tvdbId ? "border-amber-400/50 bg-amber-400/10" : "border-white/10"}`}>
                  <input type="radio" name="selectedShow" disabled={controlsBusy} checked={selectedSeries?.tvdbId === show.tvdbId} onChange={() => setSelectedSeries(show)} className="accent-amber-400" />{show.title}{show.year ? ` (${show.year})` : ""}
                </label>
              ))}</div>}
              <p className="mt-2 text-xs text-slate-500">Choose the matching series. Clear episode names such as S01E02 help automatic sorting.</p>
            </div>}
            <label htmlFor="magnet" className="mb-3 flex items-center justify-between gap-3"><span className="flex items-center gap-2 text-sm font-semibold"><Link2 className="size-4 text-amber-300" /> Magnet link</span><span className="text-[11px] text-slate-500">Movies & TV shows · legal content</span></label>
            <textarea id="magnet" value={magnet} onChange={(event) => { setMagnet(event.target.value); setNotice(null); }} placeholder="magnet:?xt=urn:btih:…" rows={4} spellCheck={false} className="w-full resize-none rounded-2xl border border-white/[0.09] bg-[#080d15] px-4 py-4 font-mono text-sm leading-6 text-slate-200 outline-none transition placeholder:text-slate-700 focus:border-amber-400/50 focus:ring-4 focus:ring-amber-400/[0.06]" />
            <div className="mt-4 rounded-xl border border-white/10 bg-white/[0.025] p-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-xs text-slate-400">{skipConnectionCheck ? "Connection check skipped. You can submit and read the server’s response." : statusBusy ? "Checking the OCI connection…" : statusError || status?.connected === false ? "Connection check unavailable. You can still try submitting." : "Connection checks can be skipped if they become unavailable."}</p>
                <button type="button" onClick={skipCheck} disabled={skipConnectionCheck || addBusy} className="shrink-0 rounded-lg border border-amber-400/30 px-3 py-2 text-xs font-semibold text-amber-200 hover:bg-amber-400/10 disabled:opacity-50">{skipConnectionCheck ? "Connection check skipped" : "Skip connection check"}</button>
              </div>
              {skipConnectionCheck && <p className="mt-2 text-xs text-slate-500">The server still checks storage. If the add request times out, check qBittorrent before retrying.</p>}
            </div>
            <div className="mt-4 flex flex-col-reverse items-stretch justify-between gap-3 sm:flex-row sm:items-center"><p className="flex items-center gap-2 text-xs text-slate-500"><ShieldCheck className="size-4 text-emerald-400" />Storage is rechecked before every request.</p><button type="button" onClick={addTorrent} disabled={!magnet.trim() || controlsBusy || searching || (mediaType === "show" && !tvReady)} className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-amber-400 px-5 text-sm font-bold text-slate-950 transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-40">{addBusy ? <LoaderCircle className="size-4 animate-spin" /> : <Plus className="size-4" />}{addBusy ? "Adding torrent…" : "Add torrent"}</button></div>
          </div>
          {notice && <div role="status" aria-live="polite" className={`mt-5 flex items-start gap-3 rounded-2xl border p-4 text-sm ${notice.kind === "success" ? "border-emerald-400/20 bg-emerald-400/[0.07] text-emerald-200" : "border-rose-400/20 bg-rose-400/[0.07] text-rose-200"}`}>{notice.kind === "success" ? <CheckCircle2 className="mt-0.5 size-4 shrink-0" /> : <XCircle className="mt-0.5 size-4 shrink-0" />}<p>{notice.text}</p></div>}
        </section>

        <aside className="space-y-5 lg:pt-[6.8rem]">
          {Boolean(status?.manualImports?.length) && <div className="rounded-3xl border border-white/[0.09] bg-[#0d131e]/80 p-5"><h2 className="text-sm font-semibold">TV sorting</h2><div className="mt-4 space-y-3">{status?.manualImports?.map((item, index) => <div key={`${item.title}-${item.season}-${item.episode}-${index}`} className="rounded-xl bg-white/[0.035] p-3"><p className="text-sm text-slate-200">{item.title} · Season {item.season}{item.episode ? ` · Episode ${item.episode}` : ""}</p><p className={`mt-1 text-xs ${item.state === "needs-review" ? "text-amber-200" : "text-slate-400"}`}>{item.message}</p></div>)}</div></div>}

          <div className="rounded-3xl border border-white/[0.09] bg-[#0d131e]/80 p-5"><div className="flex items-center justify-between"><h2 className="flex items-center gap-2 text-sm font-semibold"><CircleGauge className="size-4 text-amber-300" /> Storage overview</h2><button type="button" onClick={() => { setSkipConnectionCheck(false); void loadStatus(); }} disabled={addBusy || statusBusy} className="grid size-8 place-items-center rounded-lg text-slate-500 hover:text-white" aria-label="Refresh storage"><RefreshCw className={`size-3.5 ${statusBusy ? "animate-spin" : ""}`} /></button></div>{statusError ? <div className="mt-4 rounded-2xl border border-rose-400/15 bg-rose-400/[0.05] p-4"><p className="text-sm font-semibold text-rose-200">Connection check unavailable</p><p className="mt-1 text-xs leading-5 text-slate-500">{statusError}</p></div> : storage.length ? <div className="mt-4 space-y-3">{storage.map((item) => <StorageCard key={item.id} storage={item} />)}</div> : skipConnectionCheck ? <p className="mt-4 text-xs leading-5 text-slate-500">Connection check skipped. Use Refresh storage to check again.</p> : <div className="mt-4 h-28 animate-pulse rounded-2xl bg-white/[0.035]" />}</div>
          <div className="rounded-3xl border border-white/[0.09] bg-[#0d131e]/80 p-5"><h2 className="flex items-center gap-2 text-sm font-semibold"><Server className="size-4 text-sky-300" /> Queue now</h2><div className="mt-4 grid grid-cols-3 gap-2">{[["Active", status?.queue?.downloading ?? "—"], ["Seeding", status?.queue?.seeding ?? "—"], ["Paused", status?.queue?.paused ?? "—"]].map(([label, value]) => <div key={label} className="rounded-xl bg-white/[0.035] px-2 py-3 text-center"><strong className="block text-lg text-white">{value}</strong><span className="text-[10px] uppercase tracking-wider text-slate-600">{label}</span></div>)}</div></div>
        </aside>
      </div>
      <footer className="relative border-t border-white/[0.06] py-6 text-center text-[11px] text-slate-600">Private request portal · Requests stop automatically when storage reaches 95%.</footer>
    </main>
  );
}
