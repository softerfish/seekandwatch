"""shared tmdb http helpers"""

import requests

TMDB_API_BASE = 'https://api.themoviedb.org/3/'


def _clean_tmdb_credential(tmdb_key):
    """normalize the stored tmdb credential value"""
    return tmdb_key.strip() if isinstance(tmdb_key, str) else tmdb_key


def _looks_like_tmdb_bearer_token(tmdb_key):
    """tmdb read access tokens are bearer tokens and should stay out of query strings"""
    key = _clean_tmdb_credential(tmdb_key) or ''
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return lowered.startswith('bearer ') or key.count('.') == 2


def is_tmdb_read_access_token(tmdb_key):
    """public helper for validating tmdb read access tokens in forms and tests"""
    return _looks_like_tmdb_bearer_token(tmdb_key)


def tmdb_request_kwargs(tmdb_key, params=None):
    """build tmdb request kwargs using bearer auth when possible"""
    query = dict(params or {})
    headers = {}
    key = _clean_tmdb_credential(tmdb_key)

    if _looks_like_tmdb_bearer_token(key):
        bearer = key[7:].strip() if key.lower().startswith('bearer ') else key
        headers['Authorization'] = f'Bearer {bearer}'
    elif key:
        # legacy v3 api keys still require query auth until the saved credential is upgraded
        query['api_key'] = key

    return {
        'params': query,
        'headers': headers,
    }


def tmdb_get(path_or_url, tmdb_key, params=None, timeout=10):
    """issue a tmdb get using bearer auth when supported by the saved credential"""
    url = path_or_url if str(path_or_url).startswith('http') else f'{TMDB_API_BASE}{str(path_or_url).lstrip("/")}'
    return requests.get(url, timeout=timeout, **tmdb_request_kwargs(tmdb_key, params=params))
