export interface Book {
  label: string;
  cash: number;
  value: number;
  todayChange: number;
  todayChangePct: number;
  data: number[];
  color: string;
}

export interface CalendarEvent {
  day: number;
  weekday: string;
  month: string;
  title: string;
  tag?: string;
  tagColor?: string;
  detail: string;
}

// Shown before the first /stats response lands.
export const topStory = {
  headline: "Waiting for the bot to report in…",
  sub: "Connecting to the backend",
  date: "",
  time: "",
  marketStatus: "--" as const,
};

// Shown before the first /calendar response lands (or if it's empty).
export const calendarEvents: CalendarEvent[] = [];
