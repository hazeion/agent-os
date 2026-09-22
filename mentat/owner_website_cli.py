"""Foreground command for the explicit authenticated owner website profile."""

import signal
import time

from owner_auth import OwnerAuthAuthority
from owner_gateway import owner_origin
from .owner_website_runtime import OwnerWebsiteRuntime


def run_owner_website(args, config, runtime_environment):
    runtime = None
    handlers = {}
    stopped = False
    def interrupt(_signal, _frame):
        raise KeyboardInterrupt
    try:
        if int(config.port) != 8888:
            raise ValueError('fixed port required')
        origin = owner_origin(OwnerAuthAuthority(config.data_dir))
        runtime = OwnerWebsiteRuntime(host=origin.removeprefix('https://'), caddy=args.caddy_bin,
            cosign=args.cosign_bin, release_dir=args.release_dir, architecture=args.architecture,
            certificate=args.tls_cert, key=args.tls_key)
        for signum in {signal.SIGTERM, getattr(signal, 'SIGHUP', signal.SIGTERM)}:
            handlers[signum] = signal.signal(signum, interrupt)
        runtime.start_website(config.data_dir, runtime_environment)
        print(f'Mentat owner website ready at {origin}', flush=True)
        while runtime._alive():
            time.sleep(0.2)
        return 2
    except KeyboardInterrupt:
        return 0
    except Exception:
        print('The owner website could not start or remain available. Check owner setup, credentials, TLS and the host configuration.', flush=True)
        return 2
    finally:
        for signum in handlers:
            signal.signal(signum, signal.SIG_IGN)
        try:
            stopped = runtime is None or runtime.stop()
        except Exception:
            stopped = False
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)
        if not stopped:
            print('Website shutdown could not be verified. Check the host before restarting Mentat.', flush=True)
            return 2
