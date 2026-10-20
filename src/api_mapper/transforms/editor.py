"""Validate the finite conversion blocks available in the visual editor; no executable code."""

from api_mapper.models import TransformKind, TransformStep
from api_mapper.transforms.enum_normalization import normalized_mapping

_CASTS = {'string', 'integer', 'number', 'boolean', 'date-time'}


def parse_steps(raw: object) -> tuple[TransformStep, ...] | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) > 20:
        raise ValueError('Use at most 20 conversion steps')
    return tuple(_step(item) for item in raw)


def _step(item: object) -> TransformStep:
    if not isinstance(item, dict) or not isinstance(item.get('params', {}), dict):
        raise TypeError('Each conversion needs a kind and parameters')
    kind = TransformKind(item.get('kind'))
    params = item.get('params', {})
    if kind is TransformKind.CAST:
        target = params.get('to')
        if not isinstance(target, str) or target not in _CASTS:
            raise ValueError('Choose a supported conversion type')
        return TransformStep(kind, f'Convert to {target}', {'to': target})
    if kind is TransformKind.MINOR_UNITS_TO_DECIMAL:
        exponent = params.get('exponent', 2)
        if type(exponent) is not int or not 0 <= exponent <= 9:
            raise ValueError('Decimal places must be an integer from 0 to 9')
        return TransformStep(kind, f'Divide by 10^{exponent}', {'exponent': exponent})
    if kind is TransformKind.ENUM_MAP:
        mapping = params.get('mapping', {})
        if not isinstance(mapping, dict) or len(mapping) > 500 or not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()):
            raise ValueError('Value mappings must contain text pairs (at most 500)')
        unmapped = params.get('unmapped', [])
        if not isinstance(unmapped, list) or not all(isinstance(v, str) for v in unmapped):
            raise ValueError('Unmapped values must be a list of text values')
        mode = params.get('normalization', 'exact')
        normalized_mapping(mapping, mode)
        clean = {'mapping': mapping, 'unmapped': [value for value in unmapped if value not in mapping], 'normalization': mode}
        if 'fallback' in params:
            if not isinstance(params['fallback'], str):
                raise TypeError('The fallback must be a text value')
            clean['fallback'] = params['fallback']
        return TransformStep(kind, 'Normalize to allowed values', clean)
    return TransformStep(kind, kind.value.replace('-', ' '))
