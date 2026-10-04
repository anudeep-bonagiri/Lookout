"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Frame, HelpLinks, StageTracker } from "@/components/ui";
import { decide, getCrew, telHref } from "@/lib/api";
import { text } from "@/lib/copy";
import type { CrewState, Lang } from "@/lib/types";

export function CrewView({ token }: { token: string }) {
  const [state, setState] = useState<CrewState | null>(null);
  const [language, setLanguage] = useState<Lang>("en");
  const [error, setError] = useState("");
  const seen = useRef("");
  const t = text(language);

  useEffect(() => {
    let stop = false;
    async function pull() {
      try {
        const next = await getCrew(token);
        if (stop) return;
        setState(next);
        const id = next.pending?.approval_id || "";
        if (id && id !== seen.current) {
          seen.current = id;
          navigator.vibrate?.(200);
        }
      } catch {
        if (!stop) setError(text(language).error);
      }
    }
    pull();
    const timer = window.setInterval(pull, 2000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [token, language]);

  async function choose(decision: "approved" | "denied") {
    if (!state?.pending) return;
    await decide(state.pending.approval_id, token, decision);
    setState(await getCrew(token));
  }

  return (
    <Frame tone={state?.pending ? "alarm" : "vault"} language={language}>
      <div className="langs" style={{ marginBottom: "0.8rem" }}>
        <button type="button" className={`choice ${language === "en" ? "on" : ""}`} onClick={() => setLanguage("en")}>{t.english}</button>
        <button type="button" className={`choice ${language === "es" ? "on" : ""}`} onClick={() => setLanguage("es")}>{t.spanish}</button>
      </div>
      {state?.pending ? (
        <section className="stack">
          <h1>{t.heistTitle}</h1>
          <StageTracker stage={state.pending.stage} language={language} />
          <article className="paper stack">
            <p className="kicker">{t.fact}</p>
            <p>{state.pending.fact}</p>
            <p className="kicker">{t.userReport}</p>
            <p>{state.pending.user_report}</p>
            <p className="kicker">{t.inference}</p>
            <p>{state.pending.inference}</p>
            <p className="kicker">{t.unknown}</p>
            <p>{state.pending.unknown}</p>
            <p className="kicker">{t.action}</p>
            <p>{state.pending.action}</p>
          </article>
          <button type="button" className="btn ok" onClick={() => choose("approved")}>{t.approve}</button>
          <button type="button" className="btn danger" onClick={() => choose("denied")}>{t.deny}</button>
          <a className="btn ghost" href={telHref(state.user_phone)}>{t.call(state.user_name)}</a>
        </section>
      ) : (
        <section className="paper stack">
          <h1>{t.noAlarm}</h1>
          <p>{state ? t.noAlarmBody(state.user_name) : t.checking}</p>
        </section>
      )}
      {error ? <p className="error">{error}</p> : null}
      <Link className="btn ghost" href={`/crew/${token}/history`}>{t.history}</Link>
      <HelpLinks language={language} />
    </Frame>
  );
}
