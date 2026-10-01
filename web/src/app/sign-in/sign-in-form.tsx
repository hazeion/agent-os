"use client";

import { useState } from "react";

export function SignInForm() {
  const [pending, setPending] = useState(false);
  return <form action="/auth/google/start" method="post" onSubmit={() => setPending(true)}>
    <button className="sign-in-button" disabled={pending} type="submit">
      {pending ? "Opening Google…" : "Continue with Google"}
      <span aria-hidden="true">↗</span>
    </button>
    <p aria-live="polite" className="sign-in-progress">{pending ? "Connecting to secure sign-in." : "Use the Google account that owns this Mentat."}</p>
  </form>;
}
