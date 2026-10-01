# Set up the Google owner

Google owner setup is a host-administrator operation. Everyday website sign-in
will use **Continue with Google**; it must not require this terminal ceremony.
The normal remote dashboard is still awaiting its authenticated gateway and
live-provider acceptance gates.

The setup command supports one owner on an always-on Linux host. It temporarily
serves only setup routes, verifies a Google account in a browser, then asks for
confirmation in the host terminal. It never lets the first website visitor
claim the installation.

## Prepare the host

1. Install Mentat and its supported Node runtime. Run `mentat setup` for the
   intended data root, complete any required migration, and stop ordinary Mentat
   serving. Keep the same configuration/data-root options for subsequent commands.
2. Choose a canonical HTTPS domain. In your operator-owned Google Cloud project,
   create an OAuth web client and register the exact redirect
   `https://YOUR_DOMAIN/auth/google/callback`. Login requests only `openid email`;
   Calendar consent is separate. Follow [Google's web-server setup](https://developers.google.com/identity/protocols/oauth2/web-server).
3. Supply the client secret through the host's private environment as
   `MENTAT_GOOGLE_CLIENT_SECRET`. Do not place it in command arguments or chat.
4. Provide a trusted TLS certificate/chain and matching owner-private key for
   the domain. Setup does not request certificates or change your firewall.
   The host must reach its canonical HTTPS address; ports 80, 443 and the fixed
   loopback gateway port 8888 must be available for this temporary ceremony.
5. Stage the Caddy release assets pinned by `deploy/caddy/caddy-lock.json`, its
   extracted binary, and a trusted Cosign verifier. The command verifies the
   official checksum signature, archive/SBOM identities, binary and module
   inventory before starting Caddy. It does not download or install them.

The setup listener runs in the foreground with the operator's permissions. It
needs permission to bind the HTTPS/HTTP ports and read the TLS files. It accepts
only fixed setup routes; it does not expose the dashboard, task data or general
bridge capabilities.

## Run the ceremony

Use `enroll` for an unowned installation, `convert` for an existing passkey owner,
or `recover` to confirm the Google owner after account replacement or restore.

```sh
mentat owner-auth google-setup \
  --purpose enroll \
  --origin https://YOUR_DOMAIN \
  --client-id YOUR_WEB_CLIENT.apps.googleusercontent.com \
  --architecture amd64 \
  --release-dir /path/to/verified-release-assets \
  --caddy-bin /path/to/caddy \
  --cosign-bin /path/to/cosign \
  --tls-cert /path/to/certificate-chain.pem \
  --tls-key /path/to/private-key.pem
```

After the command verifies its own HTTPS setup page, it prints the setup URL and
a ten-minute code. Open the URL, enter the code, and choose the intended Google
account. The browser then directs you back to the terminal.

The terminal closes the browser setup surface, displays the verified account
and selected data root, and asks you to type the exact confirmation phrase.
Press Enter to cancel. Confirmation requires a verified backup and unchanged
owner authority. It changes the owner login, signs out all prior sessions,
disables old passkeys and rotates recovery codes in one transaction. Save the
new codes privately when displayed; they are not shown again.

Cancellation, expired proof and failed confirmation preserve the previous owner.
An interrupted response after a successful commit may require another host
recovery ceremony. Setup does not activate ordinary remote serving.

## Verification status

Automated checks cover the terminal/browser/backup flow with a fake Google
provider, Chromium's Google redirect and CSP controls, and real pinned Caddy
TLS routing on disposable loopback ports. Parent/guardian process-death tests
check listener cleanup. Actual Google login with the operator's domain/client,
website sign-in and complete Linux deployment acceptance are still required.
