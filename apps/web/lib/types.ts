export type Lang = "en" | "es";
export type Outcome = "allow" | "verify" | "hold";
export type Method = "ach" | "instant" | "wire" | "gift_card" | "crypto";

export type Session = {
  user_id: string;
  name: string;
  phone: string;
  language: Lang;
  contact_name: string;
  contact_phone: string;
  crew_path: string;
  token: string;
  home_id: string;
};

export type WhyLevel = "high" | "mid" | "low";

export type WhyRank = {
  id: string;
  label: string;
  rank: number;
  of: number;
  level: WhyLevel;
  q: number;
  points: number;
  successes: number;
  disputes: number;
};

export type Looked = {
  id: string;
  name: string;
  sentence: string;
  signal: string;
  heat: number;
};

export type WatcherDesk = {
  id: string;
  name: string;
  signal: string;
  phrases: string[];
  sentence: string;
  builtin: boolean;
};

export type CheckResult = {
  attempt_id: string;
  amount: number;
  recipient: string;
  method: Method;
  score: number;
  outcome: Outcome;
  stage: number;
  reasons: string[];
  signals: Record<string, boolean>;
  status: string;
  label_source: "gemini" | "fallback" | "none";
  approval_id: string | null;
  approval_status: string | null;
  warning: string;
  created_at: string;
  why?: WhyRank | null;
  suggested_why?: WhyRank | null;
  review_note?: string;
  saved_payment?: boolean;
  looked?: Looked[];
};

export type PendingApproval = {
  approval_id: string;
  attempt_id: string;
  status: string;
  fact: string;
  user_report: string;
  inference: string;
  unknown: string;
  action: string;
  amount: number;
  recipient: string;
  score: number;
  stage: number;
  reasons: string[];
};

export type CrewState = {
  contact_name: string;
  user_name: string;
  user_phone: string;
  pending: PendingApproval | null;
};

export type HistoryItem = {
  attempt_id: string;
  amount: number;
  recipient: string;
  method: string;
  status: string;
  outcome: Outcome;
  stage: number;
  score: number;
  reasons: string[];
  created_at: string;
};

export type ChartState = {
  tiger: boolean;
  buckets: { bucket: string; attempts: number; holds: number }[];
};

export type VitalsState = {
  baseline_ready: boolean;
  pressure_elevated: boolean;
  pulse: number | null;
  breathing: number | null;
  samples: number;
};
