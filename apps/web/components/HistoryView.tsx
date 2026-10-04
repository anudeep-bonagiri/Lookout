"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Frame, HelpLinks } from "@/components/ui";
import { getChart, getHistory } from "@/lib/api";
import { text } from "@/lib/copy";
import type { ChartState, HistoryItem, Lang } from "@/lib/types";

export function HistoryView({ token }: { token: string }) {
  const [language, setLanguage] = useState<Lang>("en");
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [chart, setChart] = useState<ChartState | null>(null);
  const [name, setName] = useState("");
  const t = text(language);
  const peak = Math.max(1, ...(chart?.buckets.map((bucket) => bucket.attempts) || [1]));

  useEffect(() => {
    getHistory(token).then((history) => {
      setItems(history.items);
      setName(history.user_name);
    }).catch(() => undefined);
    getChart(token).then(setChart).catch(() => undefined);
  }, [token]);

  return (
    <Frame tone="vault" language={language}>
      <section className="paper stack">
        <h1>{t.history}</h1>
        <p>{name}</p>
        <p className="quiet">{chart?.tiger ? t.tigerOn : t.tigerOff}</p>
        <div className="chart" aria-label={t.chartTitle}>
          {chart?.buckets.map((bucket) => (
            <div key={bucket.bucket}>
              <div className="bar-row">
                <span>{new Date(bucket.bucket).toLocaleString([], { month: "short", day: "numeric", hour: "numeric" })}</span>
                <div className="bar" style={{ width: `${Math.max(8, (bucket.attempts / peak) * 100)}%` }} />
              </div>
              {bucket.holds > 0 ? (
                <div className="bar-row">
                  <span>{t.heistTitle}</span>
                  <div className="bar hold" style={{ width: `${Math.max(8, (bucket.holds / peak) * 100)}%` }} />
                </div>
              ) : null}
            </div>
          ))}
        </div>
        <ul className="reasons">
          {items.map((item) => (
            <li key={item.attempt_id}>
              ${item.amount.toLocaleString()} · {item.recipient} · {item.outcome} · {item.score}
            </li>
          ))}
        </ul>
        <HelpLinks language={language} />
        <Link className="btn ink" href={`/crew/${token}`}>{t.backAlarm}</Link>
      </section>
      <div className="langs" style={{ marginTop: "0.8rem" }}>
        <button type="button" className="choice" onClick={() => setLanguage("en")}>{t.english}</button>
        <button type="button" className="choice" onClick={() => setLanguage("es")}>{t.spanish}</button>
      </div>
    </Frame>
  );
}
