"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Frame } from "@/components/ui";
import { STORAGE_KEY, getVitals } from "@/lib/api";
import { text } from "@/lib/copy";
import type { Lang, Session, VitalsState } from "@/lib/types";

export function PressureView() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [language, setLanguage] = useState<Lang>("en");
  const [vitals, setVitals] = useState<VitalsState | null>(null);
  const [camera, setCamera] = useState("");
  const t = text(language);

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (!saved) return;
    const session = JSON.parse(saved) as Session;
    const timer = window.setInterval(() => {
      getVitals(session.user_id).then(setVitals).catch(() => undefined);
    }, 2000);
    queueMicrotask(() => setLanguage(session.language));
    return () => window.clearInterval(timer);
  }, []);

  async function openCamera() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false });
      if (videoRef.current) videoRef.current.srcObject = stream;
    } catch {
      setCamera(t.error);
    }
  }

  const note = vitals?.pressure_elevated ? t.pressureHigh : vitals?.baseline_ready ? t.pressureReady : t.pressureWaiting;

  return (
    <Frame tone="vault" language={language} player={t.roles.pulse}>
      <section className="paper stack">
        <h1>{t.pressureTitle}</h1>
        <p>{t.pressureBody}</p>
        <video ref={videoRef} className="video" autoPlay muted playsInline />
        <button type="button" className="btn primary" onClick={openCamera}>{t.photo}</button>
        <p>{note}</p>
        {vitals?.pulse ? <p>{Math.round(vitals.pulse)} bpm · {vitals.breathing?.toFixed(1)} breaths</p> : null}
        {camera ? <p className="error">{camera}</p> : null}
        <Link className="btn ink" href="/wallet">{t.back}</Link>
      </section>
    </Frame>
  );
}
