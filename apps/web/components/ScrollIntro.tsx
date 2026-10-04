"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { text } from "@/lib/copy";
import type { Lang } from "@/lib/types";

const FRAMES = 96;
const pad = (n: number) => String(n).padStart(3, "0");
const clamp = (v: number, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
// ease so the crop into the phone settles instead of stopping hard
const ease = (t: number) => 1 - Math.pow(1 - t, 3);

const BEATS = [
  { at: 0.0, kicker: "A practice heist", line: "Someone is already casing the vault." },
  { at: 0.34, kicker: "The job", line: "A stranger, a threat, a rush to pay in secret." },
  { at: 0.62, kicker: "The catch", line: "Lookout holds the money until someone you trust agrees." },
];

export function ScrollIntro() {
  const [language, setLanguage] = useState<Lang>("en");
  const [entered, setEntered] = useState(false);
  const t = text(language);

  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const windowRef = useRef<HTMLDivElement>(null);
  const entryRef = useRef<HTMLDivElement>(null);
  const hintRef = useRef<HTMLParagraphElement>(null);
  const capRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const win = windowRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !win || !wrap) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const imgs: HTMLImageElement[] = new Array(FRAMES);
    let ready = 0;
    let lastFrame = -1;

    const sizeCanvas = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(canvas.clientWidth * dpr);
      canvas.height = Math.round(canvas.clientHeight * dpr);
      lastFrame = -1;
    };

    const draw = (i: number) => {
      const img = imgs[i];
      if (!img || !img.complete || !img.naturalWidth) return;
      if (i === lastFrame && canvas.width === canvas.dataset.w0) return;
      lastFrame = i;
      const cw = canvas.width;
      const ch = canvas.height;
      const scale = Math.max(cw / img.naturalWidth, ch / img.naturalHeight);
      const w = img.naturalWidth * scale;
      const h = img.naturalHeight * scale;
      ctx.clearRect(0, 0, cw, ch);
      ctx.drawImage(img, (cw - w) / 2, (ch - h) * 0.42, w, h);
    };

    const nearest = (i: number) => {
      if (imgs[i]?.complete && imgs[i].naturalWidth) return i;
      for (let d = 1; d < FRAMES; d++) {
        if (imgs[i - d]?.complete && imgs[i - d]?.naturalWidth) return i - d;
        if (imgs[i + d]?.complete && imgs[i + d]?.naturalWidth) return i + d;
      }
      return -1;
    };

    const progress = () => {
      const total = wrap.offsetHeight - window.innerHeight;
      if (total <= 0) return 0;
      return clamp(-wrap.getBoundingClientRect().top / total);
    };

    const geom = () => {
      const vw = win.parentElement!.clientWidth;
      const vh = win.parentElement!.clientHeight;
      const targetW = Math.min(392, vw * 0.9);
      const targetH = Math.min(812, vh * 0.86);
      return { vw, vh, targetW, targetH };
    };

    let scheduled = false;
    const render = () => {
      scheduled = false;
      const p = reduced ? 1 : progress();

      const frameP = clamp(p / 0.6);
      const cropP = ease(clamp((p - 0.4) / 0.42));
      const entryP = clamp((p - 0.8) / 0.2);

      const { vw, vh, targetW, targetH } = geom();
      const w = Math.round(lerp(vw, targetW, cropP));
      const h = Math.round(lerp(vh, targetH, cropP));
      win.style.width = `${w}px`;
      win.style.height = `${h}px`;
      win.style.borderRadius = `${lerp(0, 34, cropP)}px`;
      win.style.borderWidth = `${lerp(0, 1, cropP)}px`;
      win.style.boxShadow = `0 ${lerp(0, 50, cropP)}px ${lerp(0, 130, cropP)}px -28px rgba(0,0,0,${0.72 * cropP})`;
      win.style.padding = `${lerp(0, 7, cropP)}px`;

      if (canvas.clientWidth && (canvas.width === 0 || Math.abs(canvas.clientWidth * (window.devicePixelRatio || 1) - canvas.width) > 4)) {
        sizeCanvas();
      }
      const target = Math.min(FRAMES - 1, Math.round(frameP * (FRAMES - 1)));
      const use = nearest(target);
      if (use >= 0) draw(use);

      canvas.style.opacity = `${lerp(1, 0.12, entryP)}`;
      if (hintRef.current) hintRef.current.style.opacity = `${clamp(1 - p / 0.12)}`;
      if (entryRef.current) {
        entryRef.current.style.opacity = `${entryP}`;
        entryRef.current.style.transform = `translateY(${lerp(14, 0, entryP)}px)`;
      }
      if (capRef.current) {
        let active = 0;
        for (let i = 0; i < BEATS.length; i++) if (p >= BEATS[i].at) active = i;
        capRef.current.style.opacity = `${clamp(1 - entryP * 1.6)}`;
        const k = capRef.current.querySelector<HTMLElement>(".intro-k");
        const l = capRef.current.querySelector<HTMLElement>(".intro-l");
        if (k && l && k.dataset.i !== String(active)) {
          k.dataset.i = String(active);
          k.textContent = BEATS[active].kicker;
          l.textContent = BEATS[active].line;
        }
      }
      const isIn = entryP > 0.5;
      if (entryRef.current) entryRef.current.style.pointerEvents = isIn ? "auto" : "none";
      setEntered((prev) => (prev === isIn ? prev : isIn));
    };

    const schedule = () => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(render);
    };

    for (let i = 0; i < FRAMES; i++) {
      const img = new Image();
      img.decoding = "async";
      img.onload = () => {
        ready++;
        schedule();
      };
      img.src = `/reel/f_${pad(i + 1)}.jpg`;
      imgs[i] = img;
    }

    sizeCanvas();
    render();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", () => {
      sizeCanvas();
      schedule();
    });
    return () => window.removeEventListener("scroll", schedule);
  }, []);

  return (
    <section className="intro" ref={wrapRef}>
      <div className="intro-stage">
        <div className="intro-topbar">
          <span className="intro-brand">Lookout</span>
          <Link className="intro-skip" href="/wallet">skip to the wallet →</Link>
        </div>

        <div className="intro-window" ref={windowRef}>
          <canvas
            className="intro-canvas"
            ref={canvasRef}
            role="img"
            aria-label="A cartoon heist: a masked burglar creeps toward a brass vault, a red alarm laser catches him, and he reaches a glowing gem."
          />
          <div className="intro-shade" aria-hidden="true" />

          <div className="intro-cap" ref={capRef} aria-hidden="true">
            <p className="intro-k" data-i="0">A practice heist</p>
            <p className="intro-l">Someone is already casing the vault.</p>
          </div>

          <div className="intro-entry" ref={entryRef}>
            <p className="intro-chrome">{t.chrome}</p>
            <h1 className="intro-h1">{t.brand}</h1>
            <p className="intro-lead">{t.landLead}</p>
            <p className="intro-banner">{t.banner}</p>
            <div className="intro-langs">
              <button type="button" className={`choice ${language === "en" ? "on" : ""}`} onClick={() => setLanguage("en")} tabIndex={entered ? 0 : -1}>{t.english}</button>
              <button type="button" className={`choice ${language === "es" ? "on" : ""}`} onClick={() => setLanguage("es")} tabIndex={entered ? 0 : -1}>{t.spanish}</button>
            </div>
            <div className="intro-actions">
              <Link className="btn primary" href="/wallet" tabIndex={entered ? 0 : -1}>{t.openWallet}</Link>
              <Link className="btn ghost" href="/crew/maya-demo" tabIndex={entered ? 0 : -1}>{t.openLookout}</Link>
            </div>
          </div>
        </div>

        <p className="intro-hint" ref={hintRef} aria-hidden="true">scroll to step inside ↓</p>
      </div>
    </section>
  );
}
