"""
flash message helpers for consistent user messaging,
provides type-safe message categories and formatting
"""

from flask import flash
from typing import Literal

MessageCategory = Literal['success', 'error', 'warning', 'info']

def flash_success(message: str) -> None:
    """flash a success message"""
    flash(message, 'success')

def flash_error(message: str) -> None:
    """flash an error message"""
    flash(message, 'error')

def flash_warning(message: str) -> None:
    """flash a warning message"""
    flash(message, 'warning')

def flash_info(message: str) -> None:
    """flash an info message"""
    flash(message, 'info')

# common messages
def flash_settings_required() -> None:
    """flash message for missing settings"""
    flash_error("Please complete setup in Settings.")

def flash_plex_error() -> None:
    """flash message for plex connection error"""
    flash_error("Could not connect to Plex. Check your settings.")

def flash_tmdb_error() -> None:
    """flash message for TMDB API error"""
    flash_error("TMDB API error. Check your API key in settings.")

def flash_unauthorized() -> None:
    """flash message for unauthorized access"""
    flash_error("You don't have permission to access this page.")
