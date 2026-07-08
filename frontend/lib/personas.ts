// Each persona owns one real subsystem of the bot's decision-making — see
// backend/bridge.py's _BotLogHandler.TAG_MAP, which is what actually assigns
// a "speaker" to a log line. Nothing here is fabricated dialogue: it's just
// styling for real events, grouped by who made the call.
export interface Persona {
  name: string;
  color: string;
  role: string;
  skin: string;
  hair: string;
  longHair?: boolean;
  // Shown on the persona card before that role has ever logged anything.
  idleNote: string;
}

export const PERSONAS: Record<string, Persona> = {
  Boss: {
    name: "Boss", color: "#EAB308", role: "Session control",
    skin: "#E8B48C", hair: "#9CA3AF",
    idleNote: "Waiting on MT5 connection and bot start.",
  },
  Trader: {
    name: "Trader", color: "#22C55E", role: "Entries & exits",
    skin: "#C68642", hair: "#1C1310",
    idleNote: "No trades yet — waiting for a Silver Bullet setup.",
  },
  Risk: {
    name: "Risk", color: "#F97316", role: "Loss & drawdown limits",
    skin: "#F2D0A9", hair: "#6B4226",
    idleNote: "No limits tested yet today.",
  },
  "News Guard": {
    name: "News Guard", color: "#EF4444", role: "Macro news halts",
    skin: "#8D5524", hair: "#0D0D0D",
    idleNote: "No news-day halt active.",
  },
  Grader: {
    name: "Grader", color: "#8B5CF6", role: "Trade grading",
    skin: "#D2986C", hair: "#7A3B2E", longHair: true,
    idleNote: "No closed trades to grade yet.",
  },
  Scanner: {
    name: "Scanner", color: "#3B82F6", role: "Market & session state",
    skin: "#F5D6B4", hair: "#C9A227",
    idleNote: "Warming up.",
  },
};

export const PERSONA_ORDER = ["Boss", "Trader", "Risk", "News Guard", "Grader", "Scanner"];

export function personaFor(speaker: string): Persona {
  return PERSONAS[speaker] ?? {
    name: speaker, color: "#6B7280", role: "", skin: "#E8B48C", hair: "#6B7280", idleNote: "",
  };
}
