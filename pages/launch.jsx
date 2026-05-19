import { useEffect } from "react";
import { useRouter } from "next/router";

export default function LaunchPage() {
  const router = useRouter();

  useEffect(() => {
    if (!router.isReady) return;

    const iss    = router.query.iss;
    const launch = router.query.launch;

    if (!iss) return;

    (async () => {
      try {
        const smart = await fetch(
          `${iss}/.well-known/smart-configuration`
        ).then((r) => r.json());

        const verifier  = generateVerifier();
        const challenge = await generateChallenge(verifier);
        const state     = crypto.randomUUID();

        setCookie("pkce_verifier",  verifier,             300);
        setCookie("epic_token_url", smart.token_endpoint, 300);
        setCookie("epic_iss",       iss,                  300);
        setCookie("oauth_state",    state,                300);

        const params = new URLSearchParams({
          response_type:         "code",
          client_id:             process.env.NEXT_PUBLIC_EPIC_CLIENT_ID,
          redirect_uri:          window.location.origin + "/api/auth/epic/callback",
          scope:                 "launch patient/Patient.read patient/MedicationRequest.read patient/Condition.read patient/AllergyIntolerance.read patient/Encounter.read openid fhirUser",
          state,
          aud:                   iss,
          code_challenge:        challenge,
          code_challenge_method: "S256",
        });

        if (launch) params.set("launch", launch);

        window.location.href =
          smart.authorization_endpoint + "?" + params.toString();
      } catch (err) {
        console.error("Epic launch failed:", err);
      }
    })();
  }, [router.isReady]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        height: "100vh",
        fontFamily: "sans-serif",
        background: "#f9fafb",
      }}
    >
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: 52, marginBottom: 16 }}>🏥</div>
        <div style={{ fontSize: 18, fontWeight: 600, color: "#111827" }}>
          Discharge Planning AI
        </div>
        <div style={{ fontSize: 14, color: "#6b7280", marginTop: 8 }}>
          Connecting to Epic EHR…
        </div>
        <div
          style={{
            marginTop: 24,
            width: 40,
            height: 4,
            background: "#e5e7eb",
            borderRadius: 2,
            overflow: "hidden",
            margin: "24px auto 0",
          }}
        >
          <div
            style={{
              height: "100%",
              background: "#1d9e75",
              borderRadius: 2,
              animation: "progress 1.5s ease-in-out infinite",
              width: "60%",
            }}
          />
        </div>
      </div>
      <style>{`@keyframes progress{0%{transform:translateX(-100%)}100%{transform:translateX(200%)}}`}</style>
    </div>
  );
}

function generateVerifier() {
  const buf = new Uint8Array(32);
  crypto.getRandomValues(buf);
  return btoa(String.fromCharCode(...buf))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");
}

async function generateChallenge(verifier) {
  const buf  = new TextEncoder().encode(verifier);
  const hash = await crypto.subtle.digest("SHA-256", buf);
  return btoa(String.fromCharCode(...new Uint8Array(hash)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");
}

function setCookie(name, value, maxAge) {
  document.cookie = `${name}=${encodeURIComponent(
    value
  )}; path=/; max-age=${maxAge}; SameSite=Lax`;
}
