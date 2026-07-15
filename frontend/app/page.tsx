"use client";
import { useCallback, useState, useEffect } from "react";
import { apiClient, type LogEntry, type MarketReading, type Stats, type Trade } from "@/lib/api";
import { clearConnection } from "@/lib/connection";
import type { CalendarEvent } from "@/lib/dashboardData";
import Activation from "@/screens/Activation";
import Dashboard from "@/screens/Dashboard";
import SettingsScreen from "@/screens/Settings";

type Screen = "activation" | "dashboard" | "settings";

const ACTIVATION_ENABLED = true;

export default function App() {
  const [screen, setScreen] = useState<Screen>(ACTIVATION_ENABLED ? "activation" : "dashboard");
  const [running, setRunning] = useState(false);
  const [connected, setConnected] = useState(false);
  const [server, setServer] = useState("");
  const [pingMs, setPingMs] = useState<number | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [calendarEvents, setCalendarEvents] = useState<CalendarEvent[]>([]);
  const [marketReadings, setMarketReadings] = useState<MarketReading[]>([]);

  const tryConnectMt5 = useCallback(async () => {
    const start = performance.now();
    try {
      const r = await apiClient.connectMt5();
      if (r.ok) {
        setConnected(true);
        setServer(r.server ?? "");
        setPingMs(Math.round(performance.now() - start));
      }
    } catch {}
  }, []);

  useEffect(() => {
    if (screen === "activation") return;
    const pollStats = async () => {
      try {
        const s = await apiClient.getStats();
        setStats(s);
        setRunning(s.running);
      } catch {}
    };
    const pollLog = async () => {
      try { setLog(await apiClient.getLog()); } catch {}
    };
    const pollTrades = async () => {
      try { setTrades(await apiClient.getTrades()); } catch {}
    };
    const pollMarket = async () => {
      try { setMarketReadings(await apiClient.getMarket()); } catch {}
    };

    pollStats();
    pollLog();
    pollTrades();
    pollMarket();
    apiClient.getCalendar().then(setCalendarEvents).catch(() => {});

    const statsTimer = setInterval(pollStats, 5000);
    const logTimer = setInterval(pollLog, 5000);
    const tradesTimer = setInterval(pollTrades, 15000);
    const marketTimer = setInterval(pollMarket, 5000);
    return () => {
      clearInterval(statsTimer);
      clearInterval(logTimer);
      clearInterval(tradesTimer);
      clearInterval(marketTimer);
    };
  }, [screen]);

  const handleStartBot = useCallback(async () => {
    try {
      const r = await apiClient.startBot();
      setRunning(r.running);
    } catch {}
  }, []);

  const handleStopBot = useCallback(async () => {
    try {
      const r = await apiClient.stopBot();
      setRunning(r.running);
    } catch {}
  }, []);

  const handleRestartBot = useCallback(async () => {
    const r = await apiClient.restartBot();
    setRunning(r.running);
  }, []);

  const handleDisconnect = useCallback(() => {
    clearConnection();
    setConnected(false);
    setServer("");
    setPingMs(null);
    setScreen("activation");
  }, []);

  if (screen === "activation") {
    return (
      <div className="full-viewport">
        <Activation
          onActivated={() => { setScreen("dashboard"); tryConnectMt5(); }}
          doValidate={(key) => apiClient.validateLicense(key)}
        />
      </div>
    );
  }

  if (screen === "settings") {
    return (
      <div className="full-viewport dark-scroll" style={{ overflowY: "auto", background: "var(--dash-bg)", color: "var(--dash-text)" }}>
        <div style={{ maxWidth: 760, margin: "0 auto", padding: 20, display: "flex", flexDirection: "column", gap: 16 }}>
          <button
            onClick={() => setScreen("dashboard")}
            style={{
              alignSelf: "flex-start",
              background: "transparent",
              border: "none",
              color: "var(--dash-text-muted)",
              fontSize: 12,
              fontWeight: 600,
              cursor: "pointer",
              fontFamily: "inherit",
              padding: 0,
            }}
          >
            ← Back to Dashboard
          </button>
          <SettingsScreen
            onSave={async (data) => { await apiClient.saveSettings(data); await tryConnectMt5(); }}
            doLoad={() => apiClient.getSettings()}
            connected={connected}
            server={server}
            pingMs={pingMs}
            running={running}
            onRestartBot={handleRestartBot}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="full-viewport">
      <Dashboard
        running={running}
        log={log}
        stats={stats}
        trades={trades}
        calendarEvents={calendarEvents}
        marketReadings={marketReadings}
        onOpenSettings={() => setScreen("settings")}
        onDisconnect={handleDisconnect}
        onStartBot={handleStartBot}
        onStopBot={handleStopBot}
      />
    </div>
  );
}
