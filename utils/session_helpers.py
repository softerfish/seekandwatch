"""
session management helpers for consistent access across blueprints,
ensures session is always available and provides type-safe accessors
"""

from flask import session
from typing import Any, Optional, List

# session keys (centralized to avoid typos)
class SessionKeys:
    MEDIA_TYPE = 'media_type'
    SELECTED_TITLES = 'selected_titles'
    GENRE_FILTER = 'genre_filter'
    KEYWORDS = 'keywords'
    MIN_YEAR = 'min_year'
    MIN_RATING = 'min_rating'
    RATING_FILTER = 'rating_filter'
    CRITIC_FILTER = 'critic_filter'
    CRITIC_THRESHOLD = 'critic_threshold'
    SHOW_RECOVERY_CODES = 'show_recovery_codes'
    NOTIFY_TABS_LOGIN = 'notify_tabs_login'
    PLEX_PIN_ID = 'plex_pin_id'

def get_session_value(key: str, default: Any = None) -> Any:
    """safely grab value from session"""
    return session.get(key, default)

def set_session_value(key: str, value: Any) -> None:
    """safely set value in session"""
    session[key] = value

def clear_session_value(key: str) -> None:
    """safely remove value from session"""
    session.pop(key, None)

def get_media_type() -> str:
    """grab current media type from session"""
    return session.get(SessionKeys.MEDIA_TYPE, 'movie')

def set_media_type(media_type: str) -> None:
    """set media type in session"""
    if media_type not in ('movie', 'tv'):
        media_type = 'movie'
    session[SessionKeys.MEDIA_TYPE] = media_type

def get_selected_titles() -> List[str]:
    """grab selected titles from session"""
    return session.get(SessionKeys.SELECTED_TITLES, [])

def set_selected_titles(titles: List[str]) -> None:
    """set selected titles in session"""
    session[SessionKeys.SELECTED_TITLES] = titles

def get_genre_filter() -> List[str]:
    """grab genre filter from session"""
    return session.get(SessionKeys.GENRE_FILTER, [])

def set_genre_filter(genres: List[str]) -> None:
    """set genre filter in session"""
    session[SessionKeys.GENRE_FILTER] = genres

def get_keywords() -> str:
    """grab keywords from session"""
    return session.get(SessionKeys.KEYWORDS, '')

def set_keywords(keywords: str) -> None:
    """set keywords in session"""
    session[SessionKeys.KEYWORDS] = keywords

def get_min_year() -> int:
    """grab minimum year filter from session"""
    try:
        return max(0, min(2100, int(session.get(SessionKeys.MIN_YEAR, 0))))
    except (ValueError, TypeError):
        return 0

def set_min_year(year: int) -> None:
    """set minimum year filter in session"""
    session[SessionKeys.MIN_YEAR] = max(0, min(2100, year))

def get_min_rating() -> float:
    """grab minimum rating filter from session"""
    try:
        return float(session.get(SessionKeys.MIN_RATING, 0))
    except (ValueError, TypeError):
        return 0.0

def set_min_rating(rating: float) -> None:
    """set minimum rating filter in session"""
    session[SessionKeys.MIN_RATING] = rating

def clear_filters() -> None:
    """clear all filter values from session"""
    clear_session_value(SessionKeys.GENRE_FILTER)
    clear_session_value(SessionKeys.KEYWORDS)
    clear_session_value(SessionKeys.MIN_YEAR)
    clear_session_value(SessionKeys.MIN_RATING)
    clear_session_value(SessionKeys.RATING_FILTER)
    clear_session_value(SessionKeys.CRITIC_FILTER)
    clear_session_value(SessionKeys.CRITIC_THRESHOLD)
