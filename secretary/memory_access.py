"""Bounded access to archived records for the local MCP adapter."""
import re

from . import library
from .rich_text import searchable_text


def _number(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{label} must be between {minimum} and {maximum}.')
    return value


def _record(item):
    return {key: item[key] for key in ('id', 'title', 'kind', 'url', 'updated')}


def read_memory(archive, request):
    if not isinstance(request, dict):
        raise ValueError('Expected a memory request object.')
    if archive.settings()['company_mode']:
        raise ValueError('Memory MCP is unavailable while Company Mode is on.')
    action = request.get('action')
    if action == 'search':
        query = request.get('query')
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise ValueError('Enter a search query of 1 to 500 characters.')
        limit = _number(request.get('limit', 8), 1, 20, 'Limit')
        offset = _number(request.get('offset', 0), 0, 100_000, 'Offset')
        results = library.query(archive, q=query.strip(), limit=limit, offset=offset)
        items = [{**_record(item), 'snippet': item.get('search_snippet') or item['summary'][:240]}
                 for item in results['items']]
        following = offset + len(items)
        return {'items': items, 'total': results['total'],
                'next_offset': following if following < results['total'] else None}
    if action == 'read':
        item_id = request.get('record_id')
        if not isinstance(item_id, str) or not re.fullmatch(r'[a-f0-9]{32}', item_id):
            raise ValueError('Use a record ID from the search results.')
        offset = _number(request.get('offset', 0), 0, 1_000_000_000, 'Offset')
        limit = _number(request.get('limit', 5000), 1, 10_000, 'Limit')
        field = request.get('field', 'text')
        if field not in ('text', 'summary'):
            raise ValueError('Choose text or summary.')
        try:
            item = archive.get(item_id)
        except KeyError:
            raise ValueError('This record is unavailable.') from None
        content = searchable_text(item['text']) if field == 'text' else item['summary']
        following = offset + limit
        return {**_record(item), 'field': field, 'offset': offset, 'total_chars': len(content),
                'content': content[offset:following],
                'next_offset': following if following < len(content) else None}
    raise ValueError('Unknown memory action.')
