"use client";
import { useState, useEffect, useCallback } from "react";
import { mockApi, type Stats, type Trade, type Settings, type LogEntry } from "@/lib/api";
import Activation   from "@/screens/Activation";
import Dashboard    from "@/screens/Dashboard";
import Trades       from "@/screens/Trades";
import Performance  from "@/screens/Performance";
import SettingsPage from "@/screens/Settings";
import Toast        from "@/components/Toast";

type Screen = "activation" | "dashboard" | "trades" | "performance" | "settings";

const NAV: { id: Exclude<Screen, "activation">; label: string; disabled?: boolean }[] = [
  { id: "dashboard",   label: "Dashboard"   },
  { id: "trades",      label: "Trades"      },
  { id: "performance", label: "Performance", disabled: true },
  { id: "settings",    label: "Settings"    },
];

export default function App() {
  const [screen,    setScreen]    = useState<Screen>("dashboard");
  const [running,   setRunning]   = useState(false);
  const [stats,     setStats]     = useState<Stats | null>(null);
  const [log,       setLog]       = useState<LogEntry[]>([]);
  const [trades,    setTrades]    = useState<Trade[]>([]);
  const [toast,     setToast]     = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [server,    setServer]    = useState("");
  const [tFilter,   setTFilter]   = useState<"all" | "win" | "loss">("all");
  const [range,     setRange]     = useState<"7D" | "30D" | "All">("30D");
  const [menuOpen,  setMenuOpen]  = useState(false);

  const showToast = useCallback((msg: string) => {
    setToast(null);
    setTimeout(() => setToast(msg), 10);
  }, []);

  useEffect(() => {
    mockApi.connectMt5().then(r => {
      if (r.ok) { setConnected(true); setServer(r.server ?? ""); }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    const pollStats = async () => {
      try {
        const s = await mockApi.getStats();
        setStats(s);
        setRunning(s.running);
        setConnected(s.connected);
      } catch {}
    };

    const pollLog = async () => {
      try {
        const entries = await mockApi.getLog();
        setLog(entries);
      } catch {}
    };

    pollStats();
    pollLog();

    const statsTimer = setInterval(pollStats, 5000);
    const logTimer   = setInterval(pollLog,   3000);
    return () => { clearInterval(statsTimer); clearInterval(logTimer); };
  }, []);

  const handleActivated = useCallback(async () => {
    try {
      const r = await mockApi.connectMt5();
      if (r.ok) {
        setConnected(true);
        setServer(r.server ?? "");
      } else {
        showToast(r.error ?? "MT5 connection failed — check MetaTrader is open");
      }
    } catch {
      showToast("Backend not reachable — run: python server.py");
    }
    setScreen("dashboard");
  }, [showToast]);

  const handleToggleBot = useCallback(async () => {
    try {
      const r = running ? await mockApi.stopBot() : await mockApi.startBot();
      setRunning(r.running);
      showToast(r.running ? "Bot started" : "Bot stopped");
    } catch {
      showToast("Failed — is python server.py running?");
    }
  }, [running, showToast]);

  const handleLoadSettings = useCallback(() => mockApi.getSettings(), []);

  const handleSaveSettings = useCallback(async (data: Settings) => {
    try {
      const r = await mockApi.saveSettings(data);
      showToast(r.ok ? "Settings saved" : "Save failed");
    } catch { showToast("Save failed"); }
  }, [showToast]);

  const goTo = useCallback((s: Screen) => {
    setScreen(s);
    setMenuOpen(false);
    if (s === "trades") mockApi.getTrades().then(setTrades).catch(() => {});
  }, []);

  const inApp = screen !== "activation";

  return (
    <>
    <div className="app-root" style={{ background: "#F9FAFB" }}>

      {/* ── Title bar ───────────────────────────────────────────────────────── */}
      <div className="flex-shrink-0 flex items-center justify-between px-4 select-none"
           style={{ height: 40, background: "var(--nav-bg)", transition: "background 0.2s ease" }}>

        {/* Desktop: icon + brand on the left (hidden on activation screen) */}
        <div className="mob-hide-inline flex items-center gap-2 text-[13px] font-semibold" style={{ color: "var(--nav-text)" }}>
          {inApp && (
            <>
              <PulseIcon />
              AR-InvestTech
              <span className="flex items-center gap-1.5 ml-0.5">
                <span className="rounded-full" style={{
                  width: 8, height: 8,
                  ...(running
                    ? { background: "#22C55E", boxShadow: "0 0 0 3px #22C55E33" }
                    : { background: "#9CA3AF" }),
                }} />
                <span className="text-[11px] font-normal" style={{ color: "var(--nav-text-dim)" }}>
                  {running ? "Running" : "Stopped"}
                </span>
              </span>
            </>
          )}
        </div>

        {/* Mobile: burger on the left */}
        {inApp && (
          <button className="burger-btn" onClick={() => setMenuOpen(o => !o)} aria-label="Menu">
            <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <line x1="3" y1="6"  x2="21" y2="6"  />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
        )}

        {/* Mobile: brand on the right (hidden on activation screen) */}
        {inApp && (
          <div className="desk-hide items-center gap-2 text-[13px] font-semibold" style={{ marginRight: 16, color: "var(--nav-text)" }}>
            <span className="flex items-center gap-1.5 mr-1">
              <span className="rounded-full" style={{
                width: 8, height: 8,
                ...(running
                  ? { background: "#22C55E", boxShadow: "0 0 0 3px #22C55E33" }
                  : { background: "#9CA3AF" }),
              }} />
              <span className="text-[11px] font-normal" style={{ color: "var(--nav-text-dim)" }}>
                {running ? "Running" : "Stopped"}
              </span>
            </span>
            AR-InvestTech
          </div>
        )}
      </div>

      {/* ── Activation ──────────────────────────────────────────────────────── */}
      {screen === "activation" && (
        <Activation
          onActivated={handleActivated}
          doValidate={k  => mockApi.validateLicense(k)}
          doValidate2={k => mockApi.validateActivation(k)}
        />
      )}

      {/* ── App shell ───────────────────────────────────────────────────────── */}
      {inApp && (
        <div className="app-shell">

          {/* Sidebar */}
          <aside className="sidebar-nav flex flex-col flex-shrink-0" style={{ width: 180, background: "var(--nav-bg)", color: "var(--nav-text)", padding: "16px 0", transition: "background 0.2s ease, color 0.2s ease" }}>

            {/* Brand */}
            <div className="flex items-center gap-2 px-4"
                 style={{ paddingBottom: 18, borderBottom: "1px solid var(--nav-border)", marginBottom: 10 }}>
              <PulseIcon size={20} />
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--nav-text)", textTransform: "uppercase", letterSpacing: ".04em" }}>
                  AR-InvestTech
                </div>
                <div style={{ fontSize: 9, color: "var(--nav-text-dim)", textTransform: "uppercase", letterSpacing: ".05em" }}>
                  v1.0.0
                </div>
              </div>
            </div>

            {/* Nav */}
            {NAV.map(n => {
              const active = screen === n.id;
              return (
                <button key={n.id}
                  onClick={() => !n.disabled && goTo(n.id)}
                  title={n.disabled ? "Coming soon — being redesigned" : undefined}
                  className="flex items-center gap-2.5 text-[13px] font-semibold text-left w-full"
                  style={{
                    padding: active ? "10px 16px 10px 13px" : "10px 16px",
                    borderLeft: `3px solid ${active ? "var(--nav-active-border)" : "transparent"}`,
                    background: active ? "var(--nav-active-bg)" : "transparent",
                    color: n.disabled ? "var(--nav-disabled)" : active ? "var(--nav-text)" : "var(--nav-item-text)",
                    transition: "background .12s",
                    cursor: n.disabled ? "not-allowed" : "pointer",
                    opacity: n.disabled ? 0.5 : 1,
                  }}>
                  <NavIcon id={n.id} />
                  {n.label}
                </button>
              );
            })}

            <div className="flex-1" />

            {/* Bot status */}
            <div style={{ padding: "12px 16px", borderTop: "1px solid var(--nav-border)" }}>
              <div style={{ fontSize: 10, color: "var(--nav-text-dim)", textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 6 }}>
                Bot Status
              </div>
              <div className="flex items-center gap-1.5 font-semibold"
                   style={{ fontSize: 12, color: running ? "#22C55E" : "var(--nav-item-text)", marginBottom: 8 }}>
                <span className="rounded-full" style={{
                  width: 7, height: 7,
                  ...(running
                    ? { background: "#22C55E", boxShadow: "0 0 0 3px #22C55E33" }
                    : { background: "var(--nav-text-dim)" }),
                }} />
                {running ? "Running" : "Stopped"}
              </div>
              {running ? (
                <button onClick={handleToggleBot}
                  className="w-full flex items-center justify-center gap-1.5 rounded-md font-semibold"
                  style={{ background: "var(--nav-stop-bg)", border: "1px solid var(--nav-stop-border)", color: "var(--nav-stop-text)", fontSize: 12, padding: "8px 0", cursor: "pointer" }}>
                  <svg width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                    <rect x="6" y="6" width="12" height="12" />
                  </svg>
                  Stop Bot
                </button>
              ) : (
                <button onClick={handleToggleBot}
                  className="w-full flex items-center justify-center gap-1.5 rounded-md font-bold"
                  style={{ background: "var(--nav-start-bg)", color: "var(--nav-start-text)", fontSize: 12, padding: "8px 0", cursor: "pointer" }}>
                  <svg width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                    <polygon points="5 3 19 12 5 21 5 3" />
                  </svg>
                  Start Bot
                </button>
              )}
            </div>

            <div style={{ padding: "10px 16px 0", fontSize: 9, color: "var(--nav-text-dim)", letterSpacing: ".04em" }}>
              Developed by DippsDev
            </div>
          </aside>

          {/* Main */}
          <main className="app-main">
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {screen === "dashboard"   && <Dashboard running={running} log={log} stats={stats} />}
              {screen === "trades"      && <Trades trades={trades} filter={tFilter} onFilter={setTFilter} />}
              {screen === "performance" && <Performance range={range} onRange={setRange} />}
              {screen === "settings"    && (
                <SettingsPage
                  onSave={handleSaveSettings}
                  doLoad={handleLoadSettings}
                  connected={connected}
                  server={server}
                />
              )}
            </div>
          </main>
        </div>
      )}

      <Toast message={toast} onDone={() => setToast(null)} />
    </div>

    {/* ── Drawer + overlay — rendered OUTSIDE app-root so overflow-x:hidden cannot clip them ── */}
    {inApp && (
      <>
        {menuOpen && <div className="drawer-overlay" onClick={() => setMenuOpen(false)} />}

        <div className="mobile-drawer" style={{ transform: menuOpen ? "translateX(0)" : "translateX(-100%)", color: "var(--nav-text)" }}>

          {/* Brand */}
          <div className="flex items-center gap-2 px-4"
               style={{ paddingBottom: 18, borderBottom: "1px solid var(--nav-border)", marginBottom: 10 }}>
            <PulseIcon size={20} />
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, color: "var(--nav-text)", textTransform: "uppercase", letterSpacing: ".04em" }}>
                AR-InvestTech
              </div>
              <div style={{ fontSize: 9, color: "var(--nav-text-dim)", textTransform: "uppercase", letterSpacing: ".05em" }}>v1.0.0</div>
            </div>
          </div>

          {/* Nav items */}
          {NAV.map(n => {
            const active = screen === n.id;
            return (
              <button key={n.id}
                onClick={() => !n.disabled && goTo(n.id)}
                title={n.disabled ? "Coming soon — being redesigned" : undefined}
                className="flex items-center gap-2.5 text-[13px] font-semibold text-left w-full"
                style={{
                  padding: active ? "10px 16px 10px 13px" : "10px 16px",
                  borderLeft: `3px solid ${active ? "var(--nav-active-border)" : "transparent"}`,
                  background: active ? "var(--nav-active-bg)" : "transparent",
                  color: n.disabled ? "var(--nav-disabled)" : active ? "var(--nav-text)" : "var(--nav-item-text)",
                  cursor: n.disabled ? "not-allowed" : "pointer",
                  opacity: n.disabled ? 0.5 : 1,
                }}>
                <NavIcon id={n.id} />
                {n.label}
              </button>
            );
          })}

          <div style={{ flex: 1 }} />

          {/* Bot status */}
          <div style={{ padding: "12px 16px", borderTop: "1px solid var(--nav-border)" }}>
            <div style={{ fontSize: 10, color: "var(--nav-text-dim)", textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 6 }}>Bot Status</div>
            <div className="flex items-center gap-1.5 font-semibold"
                 style={{ fontSize: 12, color: running ? "#22C55E" : "var(--nav-item-text)", marginBottom: 8 }}>
              <span className="rounded-full" style={{
                width: 7, height: 7,
                ...(running ? { background: "#22C55E", boxShadow: "0 0 0 3px #22C55E33" } : { background: "var(--nav-text-dim)" }),
              }} />
              {running ? "Running" : "Stopped"}
            </div>
            {running ? (
              <button onClick={handleToggleBot}
                className="w-full flex items-center justify-center gap-1.5 rounded-md font-semibold"
                style={{ background: "var(--nav-stop-bg)", border: "1px solid var(--nav-stop-border)", color: "var(--nav-stop-text)", fontSize: 12, padding: "8px 0", cursor: "pointer" }}>
                <svg width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                  <rect x="6" y="6" width="12" height="12" />
                </svg>
                Stop Bot
              </button>
            ) : (
              <button onClick={handleToggleBot}
                className="w-full flex items-center justify-center gap-1.5 rounded-md font-bold"
                style={{ background: "var(--nav-start-bg)", color: "var(--nav-start-text)", fontSize: 12, padding: "8px 0", cursor: "pointer" }}>
                <svg width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                  <polygon points="5 3 19 12 5 21 5 3" />
                </svg>
                Start Bot
              </button>
            )}
          </div>
        </div>
      </>
    )}
    </>
  );
}

function PulseIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  );
}

function NavIcon({ id }: { id: string }) {
  if (id === "dashboard")
    return <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>;
  if (id === "trades")
    return <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>;
  if (id === "performance")
    return <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"/></svg>;
  return <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M2 12h3m14 0h3M12 2v3m0 14v3"/></svg>;
}
