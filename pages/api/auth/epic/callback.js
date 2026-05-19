export default async function handler(req, res) {
  const { code, state, error } = req.query;

  if (error) return res.redirect(`/?epic_error=${error}`);
  if (!code)  return res.status(400).json({ error: "Missing code" });

  const cookies     = parseCookies(req.headers.cookie || "");
  const verifier    = cookies.pkce_verifier;
  const tokenUrl    = cookies.epic_token_url;
  const storedState = cookies.oauth_state;

  if (state !== storedState)  return res.status(400).json({ error: "State mismatch" });
  if (!verifier || !tokenUrl) return res.redirect("/launch?error=session_expired");

  try {
    const tokenRes = await fetch(tokenUrl, {
      method:  "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type:    "authorization_code",
        code,
        redirect_uri:  process.env.NEXT_PUBLIC_APP_URL + "/api/auth/epic/callback",
        client_id:     process.env.NEXT_PUBLIC_EPIC_CLIENT_ID,
        code_verifier: verifier,
      }),
    });

    const tokens = await tokenRes.json();

    if (!tokens.access_token) {
      console.error("Token exchange failed:", tokens);
      return res.redirect("/?epic_error=token_failed");
    }

    const maxAge = tokens.expires_in || 480;

    res.setHeader("Set-Cookie", [
      `epic_token=${tokens.access_token}; Path=/; Max-Age=${maxAge}; SameSite=Lax`,
      `epic_patient=${tokens.patient || ""}; Path=/; Max-Age=${maxAge}; SameSite=Lax`,
      `epic_fhir_base=${encodeURIComponent(cookies.epic_iss || "")}; Path=/; Max-Age=${maxAge}; SameSite=Lax`,
    ]);

    res.redirect(`/?patient=${tokens.patient || ""}&source=epic`);

  } catch (err) {
    console.error("Callback error:", err);
    res.redirect("/?epic_error=callback_failed");
  }
}

function parseCookies(header) {
  return Object.fromEntries(
    header.split(";").map((c) => {
      const [k, ...v] = c.trim().split("=");
      return [k.trim(), decodeURIComponent(v.join("="))];
    })
  );
}
