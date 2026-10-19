"""Fixed Python owner-access capabilities for the ordinary website gateway."""

import os

from owner_auth import OwnerAuthAuthority, OwnerAuthError, _google_principal, _digest, _token_bytes, UNSAFE_REQUEST_LIMIT
from owner_auth_google_transactions import GoogleLoginTransactions
from owner_auth_webauthn import canonical_origin


def owner_origin(authority: OwnerAuthAuthority) -> str:
    connection = authority._open()
    try:
        state = authority._state(connection)
        if state['auth_method'] != 'google':
            raise OwnerAuthError('unavailable')
        _google_principal(connection, state)
        configuration = connection.execute('SELECT canonical_origin,requires_reconciliation FROM mentat_owner_google_configuration WHERE singleton=1').fetchone()
        if configuration[1]:
            raise OwnerAuthError('unavailable')
        return canonical_origin(configuration[0])[0]
    finally:
        connection.close()


class OwnerGateway:
    """Only bounded projections; no database row or provider payload crosses Node."""
    def __init__(self, data_root, origin, *, _transport=None, _client_secret=None):
        self.authority = OwnerAuthAuthority(data_root)
        self.origin = owner_origin(self.authority)
        if origin != self.origin:
            raise OwnerAuthError('unavailable')
        self._client_secret = os.environ.pop('MENTAT_GOOGLE_CLIENT_SECRET', '') if _client_secret is None else _client_secret
        if not isinstance(self._client_secret, str) or not 1 <= len(self._client_secret) <= 4096 or any(not 33 <= ord(value) <= 126 for value in self._client_secret):
            raise OwnerAuthError('unavailable')
        self.login = GoogleLoginTransactions(self.authority, _transport=_transport)

    def dispatch(self, operation: str, body: dict) -> dict:
        if operation == 'login-start' and body == {}:
            start = self.login.begin()
            return {'ok': True, 'authorization_url': start.authorization_url, 'browser_binding': start.browser_binding}
        if operation == 'login-callback' and set(body) == {'state', 'browser_binding', 'code'} and all(isinstance(value, str) for value in body.values()):
            # The credential never enters Node or browser-selected configuration.
            grant = self.login.authenticate_callback(**body, client_secret=self._client_secret)
            return {'ok': True, 'cookie': grant.cookie_value, 'csrf': grant.csrf_value}
        if operation == 'login-cancel' and set(body) == {'state', 'browser_binding'}:
            self.login.cancel_callback(**body)
            return {'ok': True}
        if operation == 'session' and set(body) == {'cookie'}:
            session = self.authority.authenticate_session(body['cookie'], touch=False)
            return {'ok': True, 'absolute_expires_at': session['absolute_expires_at']}
        if operation == 'validate' and set(body) == {'cookie', 'csrf'} and (body['csrf'] is None or isinstance(body['csrf'], str)):
            self.authority.authenticate_session(body['cookie'], body['csrf'], touch=False)
            return {'ok': True}
        if operation in {'sign-out', 'sign-out-all'} and set(body) == {'cookie', 'csrf'}:
            action = self.authority.sign_out if operation == 'sign-out' else self.authority.sign_out_all
            action(body['cookie'], body['csrf'])
            return {'ok': True}
        if operation == 'sse-reserve' and set(body) == {'cookie'}:
            lease = self.authority.reserve_sse(body['cookie'])
            return {'ok': True, 'lease': lease.reservation_id}
        if operation in {'sse-check', 'sse-release'} and set(body) == {'cookie', 'lease'}:
            action = self.authority.validate_sse if operation == 'sse-check' else self.authority.release_owned_sse
            action(body['cookie'], body['lease'])
            return {'ok': True}
        raise OwnerAuthError('invalid')

    def admit_private_operation(self, *, cookie: str, csrf: str | None, lease: str | None, unsafe: bool) -> None:
        if lease is not None:
            if unsafe:
                raise OwnerAuthError('invalid')
            self.authority.validate_sse(cookie, lease)
        else:
            if unsafe and csrf is None:
                raise OwnerAuthError('invalid')
            if unsafe and not self.authority._admit_durable('unsafe_request', _digest(_token_bytes(cookie, 32)), UNSAFE_REQUEST_LIMIT):
                raise OwnerAuthError('limited')
            self.authority.authenticate_session(cookie, csrf if unsafe else None)

    def close(self) -> bool:
        self._client_secret = ''
        return self.login._transport.close()
