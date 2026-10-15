"use client";

import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { text } from "@/lib/copy";
import type { Lang } from "@/lib/types";

export function Frame({
  tone,
  language,
  player,
  children,
}: {
  tone: "vault" | "alarm" | "clear";
  language: Lang;
  player?: string;
  children: React.ReactNode;
}) {
  const t = text(language);
  return (
    <main className={`screen ${tone === "vault" ? "" : tone}`} aria-label={`${t.brand} — ${t.shield}`}>
      <div className="wrap">
        <div className="brand">
          {/* The app icon, served from this site. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img className="brand-badge" src="/icon-192.png" alt="" width={40} height={40} aria-hidden="true" />
          <div className="brand-name">
            <strong>{t.brand}</strong>
            <span className="chrome">{t.chrome}</span>
          </div>
          <span className="shield-dot" aria-hidden="true" />
        </div>
        {player ? <p className="player">{player}</p> : null}
        {children}
      </div>
    </main>
  );
}

export function StageTracker({ stage, language }: { stage: number; language: Lang }) {
  const t = text(language);
  return (
    <ol className="stages" aria-label={t.holdTitle}>
      {t.stages.map((item, index) => {
        const number = index + 1;
        const state = number === stage ? "on" : number < stage ? "done" : "";
        return (
          <li key={item.name} className={`stage ${state}`} aria-current={number === stage ? "step" : undefined}>
            <span className="stage-face" aria-hidden="true">{number}</span>
            <div className="stage-body">
              <span className="who">{item.who}</span>
              <strong>
                {number}. {item.name}
              </strong>
              {number === stage ? <span className="stage-line">{item.line}</span> : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function HelpLinks({ language }: { language: Lang }) {
  const t = text(language);
  return (
    <div className="help">
      <p className="kicker">{t.report}</p>
      <a href="https://reportfraud.ftc.gov">{t.ftc}</a>
      <a href="https://www.ic3.gov">{t.fbi}</a>
      <p>{t.local}</p>
    </div>
  );
}

export function CrewQr({ path }: { path: string }) {
  const [qr, setQr] = useState<{ src: string; url: string } | null>(null);
  useEffect(() => {
    // Prefer the deployed site URL so the QR never shows localhost; fall back to the live origin.
    const base = (process.env.NEXT_PUBLIC_SITE_URL || window.location.origin).replace(/\/$/, "");
    const next = `${base}${path}`;
    QRCode.toDataURL(next, { margin: 1, width: 320, color: { dark: "#001c64", light: "#f5f8ff" } }).then((src) => {
      setQr({ src, url: next });
    });
  }, [path]);
  return (
    <div className="stack">
      {qr ? (
        // The code is drawn in the browser from the trusted contact link. It is not a remote image.
        // eslint-disable-next-line @next/next/no-img-element
        <img className="qr" src={qr.src} alt="Link for the trusted contact's phone" width={320} height={320} />
      ) : null}
      <p className="quiet">{qr?.url || path}</p>
    </div>
  );
}
