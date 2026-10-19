"""Immutable private local completion witnesses, not producing-Run authority."""
from dataclasses import dataclass, field
import hashlib
import json
import re

from mentat.project_scope_evidence import witness_metadata

_ISSUER = object()
_HEX = re.compile(r'[0-9a-f]{64}\Z')


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True, allow_nan=False).encode()


@dataclass(frozen=True, repr=False)
class NamespaceCompletionWitness:
    _context: tuple = field(repr=False)
    _result: tuple = field(repr=False)
    _scope_witness: object = field(repr=False)
    _origin: object = field(repr=False)
    _issuer: object = field(repr=False)

    def __post_init__(self):
        if self._issuer is not _ISSUER or type(self._context) is not tuple or len(self._context) != 4:
            raise ValueError('namespace_completion.invalid')
        query, image, runtime, libraries = self._context
        if (not isinstance(query, str) or _HEX.fullmatch(query) is None
                or any(value is not None and (not isinstance(value, str) or _HEX.fullmatch(value) is None)
                       for value in (image, runtime))
                or type(libraries) is not bool or libraries and runtime is None
                or type(self._result) is not tuple or len(self._result) != 2):
            raise ValueError('namespace_completion.invalid')
        text, output_bytes = self._result
        from mentat.project_worker_frontend import MAX_OUTPUT, _text
        _text(text)
        if type(output_bytes) is not int or not 0 <= output_bytes <= MAX_OUTPUT:
            raise ValueError('namespace_completion.invalid')
        witness_metadata(self._scope_witness, 'closed')


def _issue(origin, context, result, scope_witness):
    return NamespaceCompletionWitness(context, result, scope_witness, origin, _ISSUER)


def completion_metadata(value):
    """Copy validated private evidence; raw/caller-edited dictionaries fail."""
    from mentat.project_worker_namespace import NamespaceWorker
    if (type(value) is not NamespaceCompletionWitness or value._issuer is not _ISSUER
            or type(value._origin) is not NamespaceWorker
            or value._origin._completion_witness is not value
            or value._origin._handoff_context != value._context
            or value._origin._verified_result != value._result
            or getattr(value._origin._scope, '_namespace_worker', None) is not value._origin
            or value._origin._scope.deadline_hit):
        raise ValueError('namespace_completion.invalid')
    scope = witness_metadata(value._scope_witness, 'closed')
    if value._scope_witness._origin is not value._origin._scope:
        raise ValueError('namespace_completion.invalid')
    query, image, runtime, libraries = value._context
    result = {'text': value._result[0], 'output_bytes': value._result[1]}
    return {'version': 1, 'query_digest': query, 'image_digest': image,
            'runtime_image_digest': runtime, 'sealed_libraries': libraries,
            'scope': scope, 'result': result, 'terminal_digest': hashlib.sha256(_encoded(result)).hexdigest()}
