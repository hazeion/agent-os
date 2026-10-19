"""Host-terminal orchestration for one temporary Google setup ceremony."""

import os
import select
import signal
import sys
import time

from owner_auth import OwnerAuthAuthority
from owner_auth_setup import OwnerSetupCeremony
from owner_auth_webauthn import canonical_origin
from mentat.owner_setup_runtime import OwnerSetupRuntime
from data_schema import schema_startup_status

SUPPORTED_PLATFORM = sys.platform == 'linux'


def _read_confirmation(candidate) -> bool:
    remaining = max(0, candidate.expires_at - time.time())
    ready, _, _ = select.select([sys.stdin], [], [], remaining)
    return bool(ready) and sys.stdin.readline(128).strip() == 'CONFIRM ' + candidate.candidate_id


def run_google_setup(args, config) -> int:
    if not SUPPORTED_PLATFORM or not sys.stdin.isatty() or not sys.stdout.isatty():
        print('Google owner setup requires a foreground Linux terminal.')
        return 2
    secret = os.environ.get('MENTAT_GOOGLE_CLIENT_SECRET', '')
    if not secret:
        print('Set the Google web-client secret in MENTAT_GOOGLE_CLIENT_SECRET before setup. Do not put it in command arguments.')
        return 2
    if schema_startup_status(config.data_dir) != 'current':
        print('Initialize this data root with `mentat setup` and complete any required migration before Google owner setup.')
        return 2
    ceremony = runtime = None
    prior_handlers = {}
    def interrupted(_signal, _frame):
        raise KeyboardInterrupt
    for signum in {signal.SIGTERM, getattr(signal, 'SIGHUP', signal.SIGTERM)}:
        prior_handlers[signum] = signal.signal(signum, interrupted)
    try:
        origin, host = canonical_origin(args.origin)
        runtime = OwnerSetupRuntime(host=host, caddy=args.caddy_bin, cosign=args.cosign_bin,
            release_dir=args.release_dir, architecture=args.architecture, certificate=args.tls_cert, key=args.tls_key)
        ceremony = OwnerSetupCeremony(OwnerAuthAuthority(config.data_dir), purpose=args.purpose,
            client_id=args.client_id, origin=origin, client_secret=secret)
        secret = ''
        runtime.start(ceremony)
        print(f'Open {origin}/auth/setup in your browser.')
        print(f'Setup code: {ceremony.take_terminal_grant()}')
        print('Complete Google sign-in. Your account is not the owner until you confirm here.')
        while ceremony.terminal_status() in {'ready', 'pending', 'exchanging'}:
            if not runtime._alive():
                raise RuntimeError('setup stopped')
            time.sleep(0.1)
        candidate = ceremony.terminal_candidate()
        # Stop the complete browser surface before asking the operator to commit.
        if not runtime.stop():
            raise RuntimeError('setup teardown failed')
        print(f'Data root: {config.data_dir}')
        print(f'Verified Google account: {candidate.email}')
        print(f'Action: {candidate.purpose}. This changes the owner login, signs out all browsers, disables old passkeys, and rotates recovery codes.')
        print(f'Type CONFIRM {candidate.candidate_id} before this setup expires, or press Enter to cancel:')
        if not _read_confirmation(candidate):
            print('Setup cancelled or expired. The prior owner remains unchanged.')
            return 2
        result = ceremony.confirm(candidate_id=candidate.candidate_id, revision=candidate.revision)
        print('Google owner confirmed. Normal remote serving is not activated by this ceremony.')
        print(f'Validated backup: {result.backup_name}')
        print('Store these new recovery codes privately; they are shown once:')
        for code in result.recovery_codes:
            print(code)
        return 0
    except (Exception, KeyboardInterrupt):
        print('Owner setup did not complete. Check the host configuration and start a new ceremony; no provider error or secret is printed here.')
        return 2
    finally:
        secret = ''
        for signum in prior_handlers:
            signal.signal(signum, signal.SIG_IGN)
        try:
            stopped = runtime is None or runtime.stop()
            if ceremony is not None and stopped:
                stopped = ceremony.close()
        except Exception:
            stopped = False
        finally:
            for signum, handler in prior_handlers.items():
                signal.signal(signum, handler)
        if not stopped:
            print('Setup resources could not be fully stopped. Check the host before restarting Mentat; ownership may already have been confirmed.')
            return 2
