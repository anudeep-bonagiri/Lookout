"use client";

import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { text } from "@/lib/copy";
import type { Lang } from "@/lib/types";

export function Frame({
  tone,
  language,
  children,
}: {
  tone: "vault" | "alarm" | "clear";
  language: Lang;
  children: React.ReactNode;
}) {
  const t = text(language);
  return (
    <main className={`screen ${tone === "vault" ? "" : tone}`}>
      <div className="wrap">
        <div className="brand">
          <strong>{t.brand}</strong>
        </div>
        <p className="chrome">{t.chrome}</p>
        {children}
      </div>
    </main>
  );
}

export function StageTracker({ stage, language }: { stage: number; language: Lang }) {
  const t = text(language);
  return (
    <ol className="stages" aria-label={t.heistTitle}>
      {t.stages.map((item, index) => {
        const number = index + 1;
        const state = number === stage ? "on" : number < stage ? "done" : "";
        return (
          <li key={item.name} className={`stage ${state}`} aria-current={number === stage ? "step" : undefined}>
            <strong>
              {number}. {item.name}
            </strong>
            {number === stage ? <span>{item.line}</span> : null}
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
    const next = `${window.location.origin}${path}`;
    QRCode.toDataURL(next, { margin: 1, width: 320, color: { dark: "#1c140e", light: "#f4efe4" } }).then((src) => {
      setQr({ src, url: next });
    });
  }, [path]);
  return (
    <div className="stack">
      {qr ? (
        // The code is drawn in the browser from the crew link. It is not a remote image.
        // eslint-disable-next-line @next/next/no-img-element
        <img className="qr" src={qr.src} alt="Link for the trusted contact's phone" width={320} height={320} />
      ) : null}
      <p className="quiet">{qr?.url || path}</p>
    </div>
  );
}
