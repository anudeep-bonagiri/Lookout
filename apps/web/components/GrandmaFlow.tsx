"use client";

import { useEffect, useRef, useState } from "react";
import { CrewQr, Frame, HelpLinks, StageTracker } from "@/components/ui";
import {
  STORAGE_KEY,
  askContact,
  callMe,
  cancelPayment,
  addWatcher,
  checkMessage,
  checkPayment,
  continuePayment,
  friction,
  getAttempt,
  getIrs,
  getReasons,
  getRosa,
  getVitals,
  getWatchers,
  playWarning,
  setLanguage,
  setup,
} from "@/lib/api";
import { text } from "@/lib/copy";
import type { CheckResult, Lang, Method, Session, WatcherDesk, WhyRank } from "@/lib/types";

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
  const [why, setWhy] = useState("bill");
  const [reasons, setReasons] = useState<WhyRank[]>([]);
  const [desks, setDesks] = useState<WatcherDesk[]>([]);
  const [deskName, setDeskName] = useState("");
  const [deskWords, setDeskWords] = useState("");
  const [deskSignal, setDeskSignal] = useState("urgency");
  const [image, setImage] = useState("");
  const [attempt, setAttempt] = useState<CheckResult | null>(null);
  const [question, setQuestion] = useState<1 | 2 | "done">(1);
  const [messageStage, setMessageStage] = useState<CheckResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [details, setDetails] = useState(false);
  const [form, setForm] = useState({ user_name: "", user_phone: "", contact_name: "", contact_phone: "" });
  const stepRef = useRef<HTMLDivElement>(null);
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

  // Move focus to the new screen so keyboard and screen-reader users are oriented.
  useEffect(() => {
    if (step !== "boot") stepRef.current?.focus();
  }, [step]);

  const reasonLanguage = session?.language || language;
  useEffect(() => {
    if (step !== "send") return;
    let live = true;
    getReasons(reasonLanguage)
      .then((payload) => {
        if (live) setReasons(payload.reasons);
      })
      .catch(() => {
        if (live) setReasons([]);
      });
    return () => {
      live = false;
    };
  }, [step, reasonLanguage]);

  useEffect(() => {
    if (step !== "message") return;
    let live = true;
    getWatchers(reasonLanguage)
      .then((payload) => {
        if (live) setDesks(payload.watchers);
      })
      .catch(() => {
        if (live) setDesks([]);
      });
    return () => {
      live = false;
    };
  }, [step, reasonLanguage]);

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
    setWhy("threat");
    setImage("");
  }

  function useBill() {
    setAmount("140");
    setRecipient("CPS Energy");
    setMethod("ach");
    setPrompt(session?.language === "es" ? "Factura de la luz de este mes." : "Monthly electric bill.");
    setWhy("bill");
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
        why,
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

  async function addDesk(event: React.FormEvent) {
    event.preventDefault();
    if (!session) return;
    const phrases = deskWords.split(",").map((item) => item.trim()).filter((item) => item.length >= 3);
    if (deskName.trim().length < 2 || phrases.length === 0) return;
    setBusy(true);
    setError("");
    try {
      await addWatcher({
        name: deskName.trim(),
        phrases,
        signal: deskSignal,
        sentence: deskName.trim(),
        language: session.language,
      });
      setDeskName("");
      setDeskWords("");
      setDesks((await getWatchers(session.language)).watchers);
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : t.error);
    } finally {
      setBusy(false);
    }
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

  const player =
    step === "setup" || step === "send" || step === "result"
      ? t.roles.keeper
      : step === "link" || step === "waiting"
        ? t.roles.lookout
        : step === "boot" || step === "checking" || step === "message"
          ? t.roles.dial
          : t.roles.alarm;

  const announce =
    step === "checking" ? t.checking
      : step === "heist" ? t.heistTitle
        : step === "verify" ? t.verifyTitle
          : step === "waiting" ? t.waitingTitle
            : step === "send" ? t.sendTitle
              : step === "result" && attempt
                ? (attempt.status === "denied" ? t.deniedTitle
                  : attempt.status === "expired" ? t.expiredTitle
                    : attempt.status === "cancelled" ? t.cancelledTitle
                      : attempt.status === "approved" ? t.approvedTitle
                        : t.allowedTitle)
                : "";

  if (step === "boot") return <Frame tone="vault" language={language} player={player}><p>{t.checking}</p></Frame>;

  return (
    <Frame tone={tone} language={session?.language || language} player={player}>
      <div className="sr-only" role="status" aria-live="assertive">{announce}</div>
      <div className="step-view step-focus" key={step} ref={stepRef} tabIndex={-1}>
      {step === "setup" ? (
        <section className="paper stack">
          <h1>{t.setupTitle}</h1>
          <p className="lead">{t.setupBody}</p>
          <div className="langs" role="group" aria-label="Language">
            <button type="button" aria-pressed={language === "en"} className={`choice ${language === "en" ? "on" : ""}`} onClick={() => chooseLanguage("en")}>{t.english}</button>
            <button type="button" aria-pressed={language === "es"} className={`choice ${language === "es" ? "on" : ""}`} onClick={() => chooseLanguage("es")}>{t.spanish}</button>
          </div>
          <button type="button" className="btn primary" onClick={startRosa} disabled={busy}>{t.startRosa}</button>
          <p className="quiet">{t.rosaNote}</p>
          <p className="quiet">{t.castNote}</p>
          <form className="stack" onSubmit={createPair}>
            <label className="field"><span>{t.yourName}</span><input value={form.user_name} onChange={(event) => setForm({ ...form, user_name: event.target.value })} required /></label>
            <label className="field"><span>{t.yourPhone}</span><input value={form.user_phone} onChange={(event) => setForm({ ...form, user_phone: event.target.value })} required /></label>
            <label className="field"><span>{t.theirName}</span><input value={form.contact_name} onChange={(event) => setForm({ ...form, contact_name: event.target.value })} required /></label>
            <label className="field"><span>{t.theirPhone}</span><input value={form.contact_phone} onChange={(event) => setForm({ ...form, contact_phone: event.target.value })} required /></label>
            <button className="btn ink" type="submit" disabled={busy}>{t.create}</button>
          </form>
          {error ? <p className="error" role="alert">{error}</p> : null}
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
          <div className="langs" role="group" aria-label="Language">
            <button type="button" aria-pressed={session.language === "en"} className={`choice ${session.language === "en" ? "on" : ""}`} onClick={() => chooseLanguage("en")}>{t.english}</button>
            <button type="button" aria-pressed={session.language === "es"} className={`choice ${session.language === "es" ? "on" : ""}`} onClick={() => chooseLanguage("es")}>{t.spanish}</button>
          </div>
          <label className="field"><span>{t.amount}</span><input inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} required /></label>
          <label className="field"><span>{t.recipient}</span><input value={recipient} onChange={(event) => setRecipient(event.target.value)} required /></label>
          <div className="field">
            <span id="method-label">{t.method}</span>
            <div className="methods" role="group" aria-labelledby="method-label">
              {METHODS.map((item) => (
                <button type="button" key={item} aria-pressed={method === item} className={`method ${method === item ? "on" : ""}`} onClick={() => setMethod(item)}>{t.methods[item]}</button>
              ))}
            </div>
          </div>
          <div className="field">
            <span>{t.whyTitle}</span>
            {details ? <p className="quiet">{t.whyHint}</p> : null}
            <div className="why-list" role="group" aria-label={t.whyTitle}>
              {reasons.map((item) => (
                <button type="button" key={item.id} aria-pressed={why === item.id} className={`why ${why === item.id ? "on" : ""}`} onClick={() => setWhy(item.id)}>
                  {details ? <span className="why-meta">{item.rank} · {t.threat[item.level]} · {Math.round(item.q * 100)}% · {t.whyHeat(item.points)}</span> : null}
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
            <DetailToggle on={details} set={setDetails} t={t} />
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
          {error ? <p className="error" role="alert">{error}</p> : null}
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
          <StageTracker stage={attempt.stage} language={session.language} />
          <div className="paper">
            <ul className="reasons">{attempt.reasons.slice(0, 3).map((reason) => <li key={reason}>{reason}</li>)}</ul>
            {details ? (
              <div className="analyst">
                <p className="score">{t.score} {attempt.score} {t.of}</p>
                {attempt.why ? <WhyNote why={attempt.why} language={session.language} /> : null}
                <p className="quiet">{t.readBy[attempt.label_source]}</p>
                {attempt.looked?.length ? <p className="quiet">{t.looked}: {attempt.looked.map((item) => item.name).join(", ")}</p> : null}
              </div>
            ) : null}
            <DetailToggle on={details} set={setDetails} t={t} />
          </div>
          <button type="button" className="btn ghost" onClick={() => playWarning(session.language)}>{t.hear}</button>
          <AgentCall session={session} t={t} />
          <button type="button" className="btn primary" onClick={ask} disabled={busy}>{t.ask(session.contact_name)}</button>
          <button type="button" className="btn danger" onClick={cancel}>{t.cancel}</button>
        </section>
      ) : null}

      {step === "verify" && attempt && session ? (
        <section className="paper stack">
          <h1>{t.verifyTitle}</h1>
          <ul className="reasons">{attempt.reasons.slice(0, 3).map((reason) => <li key={reason}>{reason}</li>)}</ul>
          {details ? <p className="score">{t.score} {attempt.score} {t.of}</p> : null}
          <DetailToggle on={details} set={setDetails} t={t} />
          {question === 1 ? <Question prompt={t.q1} yes={t.yes} no={t.no} onYes={() => answer(1, true)} onNo={() => answer(1, false)} /> : null}
          {question === 2 ? <Question prompt={t.q2} yes={t.yes} no={t.no} onYes={() => answer(2, true)} onNo={() => answer(2, false)} /> : null}
          {question === "done" ? <button type="button" className="btn ink" onClick={proceed}>{t.continuePay}</button> : null}
          <AgentCall session={session} t={t} />
          <button type="button" className="btn primary" onClick={ask} disabled={busy}>{t.ask(session.contact_name)}</button>
          <button type="button" className="btn ghost" onClick={cancel}>{t.cancel}</button>
          {error ? <p className="error" role="alert">{error}</p> : null}
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
          <button type="button" className="btn ghost" onClick={() => setPrompt(session.language === "es" ? "Estoy en el hospital. Mándame el dinero ahora. No le digas a mamá." : "I'm at the doctor. Send the money now. Don't tell Mom.")}>{t.doctorSample}</button>
          <label className="btn ghost">{t.photo}<input type="file" accept="image/*" hidden onChange={(event) => onPhoto(event.target.files?.[0])} /></label>
          <button type="button" className="btn primary" onClick={readMessage} disabled={busy}>{t.seeStage}</button>
          {messageStage ? (
            <div>
              {messageStage.stage > 0 ? <StageTracker stage={messageStage.stage} language={session.language} /> : <p>{t.stageNone}</p>}
              <ul className="reasons">{messageStage.reasons.slice(0, 3).map((reason) => <li key={reason}>{reason}</li>)}</ul>
              <p className="quiet">{messageStage.review_note}</p>
              <DetailToggle on={details} set={setDetails} t={t} />
              {details ? (
                <div className="analyst">
                  <p className="score">{t.score} {messageStage.score} {t.of}</p>
                  {messageStage.suggested_why ? <WhyNote why={messageStage.suggested_why} language={session.language} /> : null}
                  {messageStage.looked?.length ? (
                    <div>
                      <p>{t.looked}</p>
                      <ul className="reasons">
                        {messageStage.looked.map((item) => (
                          <li key={item.id}>{item.name}: {item.sentence}{item.heat > 0 ? ` +${item.heat}` : ""}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  <p className="quiet">{t.readBy[messageStage.label_source]}</p>
                </div>
              ) : null}
              {messageStage.suggested_why ? (
                <button type="button" className="btn ink" onClick={() => { setWhy(messageStage.suggested_why?.id || why); setStep("send"); }}>{t.useReason}</button>
              ) : null}
            </div>
          ) : null}
          <form className="stack" onSubmit={addDesk}>
            <h2>{t.addWatcher}</h2>
            <p className="quiet">{t.addWatcherHint}</p>
            <ul className="reasons">{desks.map((desk) => <li key={desk.id}>{desk.name}</li>)}</ul>
            <label className="field"><span>{t.watcherName}</span><input value={deskName} onChange={(event) => setDeskName(event.target.value)} /></label>
            <label className="field"><span>{t.watcherWords}</span><input value={deskWords} onChange={(event) => setDeskWords(event.target.value)} /></label>
            <label className="field">
              <span>{t.watcherPattern}</span>
              <select value={deskSignal} onChange={(event) => setDeskSignal(event.target.value)}>
                {Object.entries(t.patterns).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
              </select>
            </label>
            <button className="btn ghost" type="submit" disabled={busy}>{t.addWatcher}</button>
          </form>
          <button type="button" className="btn ink" onClick={() => setStep("send")}>{t.back}</button>
          {error ? <p className="error" role="alert">{error}</p> : null}
        </section>
      ) : null}
      </div>
    </Frame>
  );
}

function WhyNote({ why, language }: { why: WhyRank; language: Lang }) {
  const t = text(language);
  return (
    <p>
      {t.whyChosen(why.label, why.rank, why.of, t.threat[why.level])} {t.whyLearned(why.disputes, why.successes)}
    </p>
  );
}

function AgentCall({ session, t }: { session: Session; t: ReturnType<typeof text> }) {
  const [open, setOpen] = useState(false);
  const [to, setTo] = useState(session.phone || "");
  const [status, setStatus] = useState<"idle" | "calling" | "ringing" | "setup" | "failed">("idle");
  const [note, setNote] = useState("");

  async function place() {
    setStatus("calling");
    setNote("");
    try {
      const res = await callMe(to);
      if (res.ok) {
        setStatus("ringing");
      } else if (res.reason === "setup") {
        setStatus("setup");
        setNote(res.detail || t.callSetup);
      } else {
        setStatus("failed");
        setNote(res.detail || t.callFailed);
      }
    } catch {
      setStatus("failed");
      setNote(t.callFailed);
    }
  }

  if (!open) {
    return (
      <button type="button" className="btn ink" onClick={() => setOpen(true)}>{t.agentCallBtn}</button>
    );
  }
  return (
    <div className="agent-call">
      <p className="quiet">{t.agentCallHint}</p>
      <label className="field"><span>{t.yourNumber}</span>
        <input inputMode="tel" value={to} onChange={(event) => setTo(event.target.value)} placeholder="+1 210 555 0147" />
      </label>
      <button type="button" className="btn primary" onClick={place} disabled={status === "calling" || to.trim().length < 7}>
        {status === "calling" ? "…" : t.callPlace}
      </button>
      {status === "ringing" ? <p className="call-ok">{t.callingNow}</p> : null}
      {status === "setup" || status === "failed" ? <p className="quiet">{note}</p> : null}
    </div>
  );
}

function DetailToggle({ on, set, t }: { on: boolean; set: (v: boolean) => void; t: ReturnType<typeof text> }) {
  return (
    <button type="button" className="details-toggle" aria-expanded={on} onClick={() => set(!on)}>
      {on ? t.hideDetails : t.showDetails}
    </button>
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
      {attempt.why ? <WhyNote why={attempt.why} language={language} /> : null}
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
