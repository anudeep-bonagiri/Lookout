const api = process.env.API_URL || "http://127.0.0.1:8000";
const userId = process.env.USER_ID || "11111111-1111-4111-8111-111111111111";
const apiKey = process.env.PRESAGE_API_KEY || "";

if (!apiKey) {
  console.error("Set PRESAGE_API_KEY. The wallet demo still runs without it. No pulse is invented.");
  process.exit(0);
}

let sdk;
try {
  sdk = await import("@smartspectra/node-sdk");
} catch {
  console.error("Install @smartspectra/node-sdk when the MLH Presage package is available. No pulse is invented.");
  process.exit(0);
}

const { SmartSpectraSDK, CameraSelection, breathingMetrics, cardioMetrics, decodeMetrics } = sdk;
const client = new SmartSpectraSDK({
  apiKey,
  requestedMetrics: [...(breathingMetrics || []), ...(cardioMetrics || [])],
});

if (CameraSelection?.default) client.useCamera(CameraSelection.default);

client.on("metrics", async (buf) => {
  const metrics = typeof decodeMetrics === "function" ? decodeMetrics(buf) : buf;
  const pulse = numberFrom(metrics, ["pulse.rate", "pulse", "heartRate", "hr"]);
  const breathing = numberFrom(metrics, ["breathing.rate", "breathing", "respirationRate", "rr"]);
  if (!pulse || !breathing) return;
  await fetch(`${api}/vitals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, pulse, breathing }),
  });
});

await client.start();

function numberFrom(metrics, names) {
  if (!metrics || typeof metrics !== "object") return null;
  for (const name of names) {
    const value = name.split(".").reduce((item, key) => item?.[key], metrics);
    const numeric = typeof value === "number" ? value : value?.rate;
    if (typeof numeric === "number" && numeric > 0) return numeric;
  }
  return null;
}
