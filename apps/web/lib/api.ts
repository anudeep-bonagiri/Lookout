import type { ChartState, CheckResult, CrewState, HistoryItem, Lang, Session, VitalsState } from "./types";

async function send<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers, cache: "no-store" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "";
    throw new Error(detail);
  }
  return data as T;
}

export function getRosa() {
  return send<Session>("/api/demo/rosa");
}

export function setup(body: {
  user_name: string;
  user_phone: string;
  contact_name: string;
  contact_phone: string;
  language: Lang;
}) {
  return send<Session>("/api/setup", { method: "POST", body: JSON.stringify(body) });
}

export function setLanguage(userId: string, language: Lang) {
  return send<Session>(`/api/users/${userId}/language`, {
    method: "PATCH",
    body: JSON.stringify({ language }),
  });
}

export function getIrs(language: Lang) {
  return send<{ text: string }>(`/api/samples/irs?language=${language}`);
}

export function checkPayment(body: {
  user_id: string;
  amount: number;
  recipient: string;
  method: string;
  prompt_text: string;
  image_base64?: string;
  on_call?: boolean;
  pressure_elevated?: boolean;
}) {
  return send<CheckResult>("/api/check", { method: "POST", body: JSON.stringify(body) });
}

export function checkMessage(body: { user_id: string; prompt_text: string; image_base64?: string }) {
  return send<Pick<CheckResult, "score" | "outcome" | "stage" | "reasons" | "label_source">>("/api/message-check", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function friction(attemptId: string, userId: string, onCall: boolean, secret: boolean) {
  return send<CheckResult>(`/api/attempts/${attemptId}/friction`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, on_call: onCall, told_to_keep_secret: secret }),
  });
}

export function askContact(attemptId: string, userId: string) {
  return send<CheckResult>(`/api/attempts/${attemptId}/ask`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  });
}

export function continuePayment(attemptId: string, userId: string) {
  return send<CheckResult>(`/api/attempts/${attemptId}/continue`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  });
}

export function cancelPayment(attemptId: string, userId: string) {
  return send<CheckResult>(`/api/attempts/${attemptId}/cancel`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  });
}

export function getAttempt(attemptId: string, userId: string) {
  return send<CheckResult>(`/api/attempts/${attemptId}?user_id=${encodeURIComponent(userId)}`);
}

export function getCrew(token: string) {
  return send<CrewState>(`/api/crew/${token}`);
}

export function decide(approvalId: string, token: string, decision: "approved" | "denied") {
  return send<CrewState["pending"]>(`/api/approvals/${approvalId}/decide`, {
    method: "POST",
    body: JSON.stringify({ token, decision }),
  });
}

export function getHistory(token: string) {
  return send<{ user_name: string; items: HistoryItem[] }>(`/api/history?token=${encodeURIComponent(token)}`);
}

export function getChart(token: string) {
  return send<ChartState>(`/api/history/chart?token=${encodeURIComponent(token)}`);
}

export function getVitals(userId: string) {
  return send<VitalsState>(`/api/vitals/status?user_id=${encodeURIComponent(userId)}`);
}

export async function playWarning(language: Lang) {
  const response = await fetch("/api/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language }),
  });
  const type = response.headers.get("content-type") || "";
  if (response.ok && type.includes("audio")) {
    const url = URL.createObjectURL(await response.blob());
    await new Audio(url).play();
    return;
  }
  const data = await response.json().catch(() => ({ text: "" }));
  const utterance = new SpeechSynthesisUtterance(data.text || "");
  utterance.lang = language === "es" ? "es-MX" : "en-US";
  utterance.rate = 0.92;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}

export function telHref(phone: string) {
  const digits = phone.replace(/\D/g, "");
  if (digits.length === 10) return `tel:+1${digits}`;
  if (!digits) return "tel:";
  return digits.startsWith("1") ? `tel:+${digits}` : `tel:+${digits}`;
}

export const STORAGE_KEY = "scam-shield-session";
