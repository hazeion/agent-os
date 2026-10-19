import Link from "next/link";
import { PROCESS_GATEWAY_AUTHORITY } from "@/lib/gateway-authority";
import { SignInForm } from "./sign-in-form";

export const dynamic = "force-dynamic";

const MESSAGES: Record<string, string> = {
  cancelled: "Sign-in was cancelled. You can try again when you’re ready.",
  failed: "Sign-in could not be completed. Use the owner’s Google account and start a new attempt if the previous one expired.",
  unavailable: "Sign-in is temporarily unavailable. Please try again shortly.",
  "signed-out": "You’re signed out of this Mentat.",
  expired: "This sign-in attempt expired. Start again to continue.",
  "session-ended": "Your session ended. Sign in again to continue.",
  wrong_account: "That Google account isn’t the owner of this Mentat. Try again with the account selected during setup.",
};

export default async function SignInPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const status = typeof params.status === "string" ? params.status : "";
  const message = Object.hasOwn(MESSAGES, status) ? MESSAGES[status] : undefined;
  const hosted = PROCESS_GATEWAY_AUTHORITY.mode === "owner";
  return <main className="sign-in-page">
    <meta name="mentat-instance" content={process.env.MENTAT_GATEWAY_INSTANCE ?? ""} />
    <section aria-labelledby="sign-in-title" className="sign-in-card">
      <div className="sign-in-brand"><span aria-hidden="true" className="brand-mark" /><span>Mentat</span></div>
      <p className="sign-in-eyebrow">Your workspace</p>
      <h1 id="sign-in-title">Sign in to Mentat</h1>
      <p className="sign-in-description">Access your projects and agents from any device.</p>
      {message ? <p className="sign-in-notice" role="status">{message}</p> : null}
      {hosted ? <SignInForm /> : <div><p className="sign-in-description">This Mentat is running locally.</p><Link className="sign-in-button" href="/">Open your workspace <span aria-hidden="true">→</span></Link></div>}
      <p className="sign-in-footnote">Your agents keep working after you sign out.</p>
    </section>
  </main>;
}
