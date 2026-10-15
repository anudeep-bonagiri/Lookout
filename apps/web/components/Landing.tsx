"use client";

import { useState } from "react";
import Link from "next/link";
import { text } from "@/lib/copy";
import type { Lang } from "@/lib/types";

export function Landing() {
  const [language, setLanguage] = useState<Lang>("en");
  const t = text(language);

  return (
    <main className="land">
      <div className="land-top">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="brand-badge" src="/icon-192.png" alt="" width={40} height={40} aria-hidden="true" />
        <span className="land-brand">{t.brand}</span>
        <div className="langs land-langs">
          <button type="button" className={`choice ${language === "en" ? "on" : ""}`} onClick={() => setLanguage("en")}>{t.english}</button>
          <button type="button" className={`choice ${language === "es" ? "on" : ""}`} onClick={() => setLanguage("es")}>{t.spanish}</button>
        </div>
      </div>

      <section className="land-hero">
        <p className="land-kicker">{t.landKicker}</p>
        <h1 className="land-h1">{t.landLead}</h1>
        <p className="land-body">{t.landBody}</p>
        <div className="land-actions">
          <Link className="btn primary" href="/wallet">{t.openWallet}</Link>
          <Link className="btn ghost" href="/trusted/maya-demo">{t.openLookout}</Link>
        </div>
        <p className="land-note">{t.landNote}</p>
      </section>

      <section className="land-points" aria-label={t.shield}>
        {t.landPoints.map((point, index) => (
          <article key={point.title} className="land-point">
            <span className="land-num" aria-hidden="true">{index + 1}</span>
            <h2>{point.title}</h2>
            <p>{point.body}</p>
          </article>
        ))}
      </section>
    </main>
  );
}
