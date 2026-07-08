import type { LogEntry } from "./api";

export type DisplayLogEntry = LogEntry & { synthetic?: boolean };

interface ReactionRule {
  from: string;
  tag: string;
  reactor: string;
  text: string;
}

// Every rule fires only in response to a tag backend/bridge.py's TAG_MAP
// actually emits (see _BotLogHandler) — this never invents an event, it
// only adds one deterministic, second-persona aside reacting to an event
// that already happened, so the feed reads as a conversation instead of a
// one-way broadcast. Same trigger always produces the same aside.
const RULES: ReactionRule[] = [
  { from: "Trader", tag: "[ENTRY]", reactor: "Risk", text: "Sized within today's risk cap." },
  { from: "Trader", tag: "[BE]", reactor: "Grader", text: "Noted — stop moved to breakeven." },
  { from: "Trader", tag: "[TRAIL]", reactor: "Grader", text: "Trailing the winner." },
  { from: "Trader", tag: "[EXIT]", reactor: "Grader", text: "Grading this one now." },
  { from: "Risk", tag: "[RISK]", reactor: "Boss", text: "Copy — standing down." },
  { from: "News Guard", tag: "[NEWS]", reactor: "Boss", text: "Pausing entries until the window clears." },
  { from: "Boss", tag: "[HALT]", reactor: "Risk", text: "Confirmed — all positions flat." },
  { from: "Scanner", tag: "[ERR]", reactor: "Boss", text: "Keep watching, retry next cycle." },
];

export function withReactions(log: LogEntry[]): DisplayLogEntry[] {
  const out: DisplayLogEntry[] = [];
  for (const entry of log) {
    const rule = RULES.find(r => r.from === entry.speaker && r.tag === entry.tag);
    if (rule) {
      out.push({
        t: entry.t,
        tag: entry.tag,
        k: entry.k,
        x: rule.text,
        speaker: rule.reactor,
        synthetic: true,
      });
    }
    out.push(entry);
  }
  return out;
}
