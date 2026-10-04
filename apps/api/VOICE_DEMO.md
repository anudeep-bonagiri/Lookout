# Lookout — the call-in scam check

A phone number anyone can call. They say, in their own words, what a caller or
a text told them. Lookout asks one follow-up, then gives a plain verdict. It
runs the caller's words through the same reader and scorer the wallet uses
(`app/labels.py` + the message signals in `app/reasons.py`).

No Twilio SDK and no API keys are required for an inbound demo — the endpoints
return TwiML (XML) directly, and the detector falls back to offline keyword
rules when no Gemini key is set. A Gemini key makes the reading sharper.

## Endpoints

- `POST /voice/incoming` — Twilio hits this when the call connects. Returns the
  greeting and opens a speech `Gather`.
- `POST /voice/turn?step=1|2` — Twilio posts `SpeechResult` here. Step 1 asks a
  follow-up; step 2 gives the verdict and hangs up.

Call state is held in memory keyed by Twilio's `CallSid`, which is enough for a
single-process demo. Restarting the server clears any call in progress.

## Point a Twilio number at it (about 5 minutes)

1. Run the API locally:
   ```
   npm run dev:api        # uvicorn on :8000
   ```
2. Give it a public URL (Twilio must reach it over HTTPS):
   ```
   ngrok http 8000        # or: cloudflared tunnel --url http://localhost:8000
   ```
   Copy the https URL it prints, e.g. `https://abc123.ngrok.app`.
3. In the Twilio console, open **Phone Numbers → your number → Voice
   Configuration**. Set **A call comes in** to **Webhook**,
   `https://abc123.ngrok.app/voice/incoming`, **HTTP POST**. Save.
4. Call the number. You should hear Joanna greet you.

**Spoken words are NLP-generated.** With `GEMINI_API_KEY` set, the follow-up
question and the verdict are written by Gemini from what the caller actually
said — so it references their words ("the IRS will never demand gift cards") and
sounds like a real agent, not a script. The rules engine still decides
scam / caution / clear underneath, so the judgment stays grounded and safe.
Without a Gemini key it falls back to the fixed lines below, which still land on
the right verdict. The rehearsed script works either way.

The voice is Amazon Polly `Joanna-Neural` by default. **Set `ELEVENLABS_API_KEY`
in `.env` and every line is spoken by ElevenLabs instead** — the bot serves the
audio from `GET /voice/audio` and plays it with `<Play>`. No code change needed;
leave the key blank to stay on Polly.

Only inbound is wired. Outbound calls (Lookout calling you) would need your
Twilio Account SID and Auth Token and the Twilio SDK — not part of this demo.

## The rehearsed script — lands on SCAM every time

Read the caller lines naturally, like a worried person. They are ordinary
sentences; the words in **bold** are what trip the detector, so keep them in.
The Lookout lines are what the bot actually says.

> **Lookout:** Hi, this is Lookout. I am a friend who double checks a payment
> before you send it. In your own words, tell me what the caller or the text
> message said. Take your time. I am listening.
>
> **You (caller):** Someone just called me. He said he was from the **IRS**, and
> that there is a **warrant for my arrest**. He says I will be **arrested**
> today unless I pay what I owe — with **gift cards**, **right now**.
>
> _(authority + threat + urgency + sensitive request = 50 → already a scam)_
>
> **Lookout:** One more thing. Did they tell you to keep this between us, and
> not tell your family or your bank?
>
> **You (caller):** **Yes.** He told me not to tell anyone.
>
> _(the "yes" confirms secrecy, +15 = 65)_
>
> **Lookout:** Okay. Please stop right here. What you are describing has the
> marks of a scam. A real agency will never threaten you with arrest, and will
> never ask for gift cards, a wire, or a code over the phone. Hang up now, and
> do not send anything. If you want to be sure, look the company up yourself and
> call the number on their real website. You did the right thing by checking
> first.

## Two more runs, if you want to show the range

**Caution (yellow).** The words are worrying but thinner.

> **You:** My bank's **fraud department** called and said to **wire** the money
> **immediately** to protect my account.
> **Lookout:** _(asks a follow-up)_
> **You:** No, they didn't say to keep it secret.
> **Lookout:** This has a few of the warning signs I listen for. Before you send
> money to anyone, check with someone you trust, and never pay an official bill
> with gift cards or a wire. When in doubt, slow down. A real bill can wait ten
> minutes.

**Clear (green).** A normal payment.

> **You:** My daughter asked me to send her fifty dollars for groceries.
> **Lookout:** _(asks a follow-up)_
> **You:** No, nothing like that.
> **Lookout:** I do not hear the usual scam signs in what you told me. Still,
> keep your guard up. If anyone rushes you, or tells you to keep a payment
> secret, that is your sign to stop and check.

## Demo tips

- Speak in short sentences and pause at the end so Twilio's speech `Gather`
  closes cleanly before the bot replies.
- There is a short pause before each reply if a Gemini key is set, while the
  words are read. Unset `GEMINI_API_KEY` for instant, offline, fully
  deterministic replies — the rehearsed script above is written to land on SCAM
  with offline rules alone.
- The step-2 "yes/no" follow-up only counts a clear **yes**. If you answer "no",
  the verdict rides on what you already said.
