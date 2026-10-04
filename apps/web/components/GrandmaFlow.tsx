"use client";

import { useEffect, useState } from "react";
import { CrewQr, Frame, HelpLinks, StageTracker } from "@/components/ui";
import {
  STORAGE_KEY,
  askContact,
  cancelPayment,
  checkMessage,
  checkPayment,
  continuePayment,
  friction,
  getAttempt,
  getIrs,
  getRosa,
  getVitals,
  playWarning,
  setLanguage,
  setup,
} from "@/lib/api";
import { text } from "@/lib/copy";
import type { CheckResult, Lang, Method, Session } from "@/lib/types";

type Step = "boot" | "setup" | "link" | "send" | "checking" | "heist" | "verify" | "waiting" | "result" | "message";

const METHODS: Method[] = ["ach", "instant", "wire", "gift_card", "crypto"];

export function GrandmaFlow() {
  const [step, setStep] = useState<Step>("boot");
  const [session, setSession] = useState<Session | null>(null);
  const [language, setLang] = useState<Lang>("en");
  const [amount, setAmount] = useState("140");
  const [recipient, setRecipient] = useState("CPS Energy");
  const [method, setMethod] = useState<Method>("ach");
  const [prompt, setPrompt] = useState("");
  const [image, setImage] = useState("");
  const [attempt, setAttempt] = useState<CheckResult | null>(null);
  const [question, setQuestion] = useState<1 | 2 | "done">(1);
  const [messageStage, setMessageStage] = useState<CheckResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [form, setForm] = useState({ user_name: "", user_phone: "", contact_name: "", contact_phone: "" });
  const t = text(session?.language || language);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (!saved) {
        setStep("setup");
        return;
      }
      try {
        const parsed = JSON.parse(saved) as Session;
        setSession(parsed);
        setLang(parsed.language);
        setStep("send");
      } catch {
        setStep("setup");
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    document.documentElement.lang = session?.language || language;
  }, [session, language]);

  useEffect(() => {
    if (step !== "heist" || !session || !attempt) return;
    playWarning(session.language).catch(() => undefined);
  }, [step, session, attempt]);

  const attemptId = attempt?.attempt_id;
  const userId = session?.user_id;
  useEffect(() => {
    if (step !== "waiting" || !userId || !attemptId) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await getAttempt(attemptId, userId);
        setAttempt(next);
        if (next.approval_status === "pending" || next.status === "held" || next.status === "verifying") return;
        setStep("result");
      } catch {
        setError(t.error);
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [step, userId, attemptId, t.error]);

  function remember(next: Session) {
    setSession(next);
    setLang(next.language);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  }

  async function chooseLanguage(next: Lang) {
    setLang(next);
    if (!session) return;
    remember(await setLanguage(session.user_id, next));
  }

  async function startRosa() {
    setBusy(true);
    setError("");
    try {
      const rosa = await getRosa();
      const next = rosa.language === language ? rosa : await setLanguage(rosa.user_id, language);
      remember(next);
      setStep("link");
    } catch {
      setError(t.error);
    } finally {
      setBusy(false);
    }
  }

  async function createPair(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      remember(await setup({ ...form, language }));
      setStep("link");
    } catch {
      setError(t.error);
    } finally {
      setBusy(false);
    }
  }

  async function useIrs() {
    if (!session) return;
    const sample = await getIrs(session.language);
    setAmount("2000");
    setRecipient("IRS Collections");
    setMethod("instant");
    setPrompt(sample.text);
    setImage("");
  }

  function useBill() {
    setAmount("140");
    setRecipient("CPS Energy");
    setMethod("ach");
    setPrompt(session?.language === "es" ? "Factura de la luz de este mes." : "Monthly electric bill.");
    setImage("");
  }

  async function onPhoto(file: File | undefined) {
    if (!file) return;
    const data = await file.arrayBuffer();
    const blob = new Blob([data], { type: file.type || "image/jpeg" });
    const reader = new FileReader();
    reader.onload = () => setImage(String(reader.result || ""));
    reader.readAsDataURL(blob);
  }

  function listen() {
    const kit = window as Window & {
      SpeechRecognition?: new () => SpeechRec;
      webkitSpeechRecognition?: new () => SpeechRec;
    };
    const Maker = kit.SpeechRecognition || kit.webkitSpeechRecognition;
    if (!Maker) return;
    const rec = new Maker();
    rec.lang = (session?.language || language) === "es" ? "es-MX" : "en-US";
    rec.onresult = (event) => {
      const said = event.results[0]?.[0]?.transcript || "";
      setPrompt((current) => (current ? `${current} ${said}` : said));
      setListening(false);
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => setListening(false);
    setListening(true);
    rec.start();
  }

  async function submitPayment(event?: React.FormEvent) {
    event?.preventDefault();
    if (!session) return;
    setStep("checking");
    setError("");
    const started = Date.now();
    try {
      const vitals = await getVitals(session.user_id).catch(() => null);
      const result = await checkPayment({
        user_id: session.user_id,
        amount: Number(amount),
        recipient,
        method,
        prompt_text: prompt,
        image_base64: image || undefined,
        pressure_elevated: Boolean(vitals?.pressure_elevated),
      });
      const wait = 1100 - (Date.now() - started);
      if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
      setAttempt(result);
      setQuestion(1);
      setStep(result.outcome === "hold" ? "heist" : result.outcome === "verify" ? "verify" : "result");
    } catch {
      setError(t.error);
      setStep("send");
    }
  }

  async function answer(which: 1 | 2, yes: boolean) {
    if (!session || !attempt) return;
    if (!yes) {
      setQuestion(which === 1 ? 2 : "done");
      return;
    }
    setBusy(true);
    try {
      const next = await friction(attempt.attempt_id, session.user_id, which === 1, which === 2);
      setAttempt(next);
      setStep(next.outcome === "hold" ? "heist" : "verify");
      setQuestion(which === 1 && next.outcome !== "hold" ? 2 : "done");
    } catch {
      setError(t.error);
    } finally {
      setBusy(false);
    }
  }

  async function ask() {
    if (!session || !attempt) return;
    setBusy(true);
    try {
      setAttempt(await askContact(attempt.attempt_id, session.user_id));
      setStep("waiting");
    } catch {
      setError(t.error);
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!session || !attempt) return;
    setAttempt(await cancelPayment(attempt.attempt_id, session.user_id));
    setStep("result");
  }

  async function proceed() {
    if (!session || !attempt) return;
    setAttempt(await continuePayment(attempt.attempt_id, session.user_id));
    setStep("result");
  }

  async function readMessage() {
    if (!session) return;
    setBusy(true);
    setError("");
    try {
      const result = await checkMessage({ user_id: session.user_id, prompt_text: prompt, image_base64: image || undefined });
      setMessageStage(result as CheckResult);
    } catch {
      setError(t.error);
    } finally {
      setBusy(false);
    }
  }

  const tone = step === "heist" || step === "waiting" ? "alarm" : step === "result" && (attempt?.status === "allowed" || attempt?.status === "approved") ? "clear" : "vault";

  if (step === "boot") return <Frame tone="vault" language={language}><p>{t.checking}</p></Frame>;

  return (
    <Frame tone={tone} language={session?.language || language}>
      {step === "setup" ? (
        <section className="paper stack">
          <h1>{t.setupTitle}</h1>
          <p className="lead">{t.setupBody}</p>
          <div className="langs">
            <button type="button" className={`choice ${language === "en" ? "on" : ""}`} onClick={() => chooseLanguage("en")}>{t.english}</button>
            <button type="button" className={`choice ${language === "es" ? "on" : ""}`} onClick={() => chooseLanguage("es")}>{t.spanish}</button>
          </div>
          <button type="button" className="btn primary" onClick={startRosa} disabled={busy}>{t.startRosa}</button>
          <p className="quiet">{t.rosaNote}</p>
          <form className="stack" onSubmit={createPair}>
            <label className="field"><span>{t.yourName}</span><input value={form.user_name} onChange={(event) => setForm({ ...form, user_name: event.target.value })} required /></label>
            <label className="field"><span>{t.yourPhone}</span><input value={form.user_phone} onChange={(event) => setForm({ ...form, user_phone: event.target.value })} required /></label>
            <label className="field"><span>{t.theirName}</span><input value={form.contact_name} onChange={(event) => setForm({ ...form, contact_name: event.target.value })} required /></label>
            <label className="field"><span>{t.theirPhone}</span><input value={form.contact_phone} onChange={(event) => setForm({ ...form, contact_phone: event.target.value })} required /></label>
            <button className="btn ink" type="submit" disabled={busy}>{t.create}</button>
          </form>
          {error ? <p className="error">{error}</p> : null}
        </section>
      ) : null}

      {step === "link" && session ? (
        <section className="paper stack">
          <h1>{t.linkTitle}</h1>
          <p className="lead">{t.linkBody}</p>
          <CrewQr path={session.crew_path} />
          <button type="button" className="btn primary" onClick={() => setStep("send")}>{t.enterWallet}</button>
          <a className="btn ghost" href="/pressure">{t.pressureTitle}</a>
        </section>
      ) : null}

      {step === "send" && session ? (
        <form className="paper stack" onSubmit={submitPayment}>
          <p className="banner">{t.banner}</p>
          <h1>{t.sendTitle}</h1>
          <div className="langs">
            <button type="button" className={`choice ${session.language === "en" ? "on" : ""}`} onClick={() => chooseLanguage("en")}>{t.english}</button>
            <button type="button" className={`choice ${session.language === "es" ? "on" : ""}`} onClick={() => chooseLanguage("es")}>{t.spanish}</button>
          </div>
          <label className="field"><span>{t.amount}</span><input inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} required /></label>
          <label className="field"><span>{t.recipient}</span><input value={recipient} onChange={(event) => setRecipient(event.target.value)} required /></label>
          <div className="field">
            <span>{t.method}</span>
            <div className="methods">
              {METHODS.map((item) => (
                <button type="button" key={item} className={`method ${method === item ? "on" : ""}`} onClick={() => setMethod(item)}>{t.methods[item]}</button>
              ))}
            </div>
          </div>
          <label className="field">
            <span>{t.prompt}</span>
            <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder={t.promptHint} />
          </label>
          <div className="split">
            <button type="button" className="btn ghost" onClick={useIrs}>{t.irs}</button>
            <button type="button" className="btn ghost" onClick={useBill}>{t.normal}</button>
          </div>
          <div className="split">
            <label className="btn ghost">{t.photo}<input type="file" accept="image/*" capture="environment" hidden onChange={(event) => onPhoto(event.target.files?.[0])} /></label>
            <button type="button" className="btn ghost" onClick={listen}>{listening ? t.listening : t.voice}</button>
          </div>
          {image ? <p className="quiet">{t.photoAdded}</p> : null}
          <button type="button" className="btn ghost" onClick={() => { setMessageStage(null); setStep("message"); }}>{t.checkMessage}</button>
          <button className="btn primary" type="submit">{t.primary}</button>
          {error ? <p className="error">{error}</p> : null}
        </form>
      ) : null}

      {step === "checking" ? (
        <section className="dial-wrap" aria-live="polite">
          <div className="dial" />
          <h1>{t.checking}</h1>
        </section>
      ) : null}

      {step === "heist" && attempt && session ? (
        <section className="stack">
          <h1>{t.heistTitle}</h1>
          <p className="score">{t.score} {attempt.score} {t.of}</p>
          <StageTracker stage={attempt.stage} language={session.language} />
          <div className="paper">
            <ul className="reasons">{attempt.reasons.slice(0, 3).map((reason) => <li key={reason}>{reason}</li>)}</ul>
            <p className="quiet">{t.readBy[attempt.label_source]}</p>
          </div>
          <button type="button" className="btn ghost" onClick={() => playWarning(session.language)}>{t.hear}</button>
          <button type="button" className="btn primary" onClick={ask} disabled={busy}>{t.ask(session.contact_name)}</button>
          <button type="button" className="btn danger" onClick={cancel}>{t.cancel}</button>
        </section>
      ) : null}

      {step === "verify" && attempt && session ? (
        <section className="paper stack">
          <h1>{t.verifyTitle}</h1>
          <p className="score">{t.score} {attempt.score} {t.of}</p>
          <ul className="reasons">{attempt.reasons.slice(0, 3).map((reason) => <li key={reason}>{reason}</li>)}</ul>
          {question === 1 ? <Question prompt={t.q1} yes={t.yes} no={t.no} onYes={() => answer(1, true)} onNo={() => answer(1, false)} /> : null}
          {question === 2 ? <Question prompt={t.q2} yes={t.yes} no={t.no} onYes={() => answer(2, true)} onNo={() => answer(2, false)} /> : null}
          {question === "done" ? <button type="button" className="btn ink" onClick={proceed}>{t.continuePay}</button> : null}
          <button type="button" className="btn primary" onClick={ask} disabled={busy}>{t.ask(session.contact_name)}</button>
          <button type="button" className="btn ghost" onClick={cancel}>{t.cancel}</button>
          {error ? <p className="error">{error}</p> : null}
        </section>
      ) : null}

      {step === "waiting" && session ? (
        <section className="stack">
          <h1>{t.waitingTitle}</h1>
          <p className="lead">{t.waitingBody(session.contact_name)}</p>
          <button type="button" className="btn danger" onClick={cancel}>{t.cancel}</button>
        </section>
      ) : null}

      {step === "result" && attempt && session ? (
        <Result attempt={attempt} language={session.language} contact={session.contact_name} onAgain={() => { setAttempt(null); setPrompt(""); setImage(""); setAmount("140"); setRecipient("CPS Energy"); setMethod("ach"); setStep("send"); }} />
      ) : null}

      {step === "message" && session ? (
        <section className="paper stack">
          <h1>{t.messageTitle}</h1>
          <p className="lead">{t.messageBody}</p>
          <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} />
          <label className="btn ghost">{t.photo}<input type="file" accept="image/*" hidden onChange={(event) => onPhoto(event.target.files?.[0])} /></label>
          <button type="button" className="btn primary" onClick={readMessage} disabled={busy}>{t.seeStage}</button>
          {messageStage ? (
            <div>
              {messageStage.stage > 0 ? <StageTracker stage={messageStage.stage} language={session.language} /> : <p>{t.stageNone}</p>}
              <ul className="reasons">{messageStage.reasons.slice(0, 3).map((reason) => <li key={reason}>{reason}</li>)}</ul>
              <p className="quiet">{t.readBy[messageStage.label_source]}</p>
            </div>
          ) : null}
          <button type="button" className="btn ink" onClick={() => setStep("send")}>{t.back}</button>
          {error ? <p className="error">{error}</p> : null}
        </section>
      ) : null}
    </Frame>
  );
}

function Question({ prompt, yes, no, onYes, onNo }: { prompt: string; yes: string; no: string; onYes: () => void; onNo: () => void }) {
  return (
    <div className="stack">
      <p>{prompt}</p>
      <div className="split">
        <button type="button" className="btn ink" onClick={onYes}>{yes}</button>
        <button type="button" className="btn ghost" onClick={onNo}>{no}</button>
      </div>
    </div>
  );
}

function Result({ attempt, language, contact, onAgain }: { attempt: CheckResult; language: Lang; contact: string; onAgain: () => void }) {
  const t = text(language);
  const status = attempt.status;
  const title = status === "denied" ? t.deniedTitle : status === "expired" ? t.expiredTitle : status === "cancelled" ? t.cancelledTitle : status === "approved" ? t.approvedTitle : t.allowedTitle;
  const body = status === "denied" ? t.deniedBody : status === "expired" ? t.expiredBody(contact) : status === "cancelled" ? t.cancelledBody : status === "approved" ? t.approvedBody : t.allowedBody;
  return (
    <section className="paper stack">
      <p className="banner">{t.banner}</p>
      <h1>{title}</h1>
      <p className="lead">{body}</p>
      <p>${attempt.amount.toLocaleString()} · {attempt.recipient}</p>
      {(status === "denied" || status === "expired") ? <HelpLinks language={language} /> : null}
      <button type="button" className="btn primary" onClick={onAgain}>{t.another}</button>
    </section>
  );
}

type SpeechRec = {
  lang: string;
  start: () => void;
  onresult: ((event: { results: { [index: number]: { [index: number]: { transcript: string } } } }) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
};
