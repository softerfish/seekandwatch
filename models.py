"""Database models - user accounts, settings, blocklists, etc."""

from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(150), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    
    settings = db.relationship('Settings', back_populates='user', uselist=False)

class Settings(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    schedule_time = db.Column(db.String(10), default='04:00')
    
    user = db.relationship('User', back_populates='settings')
    
    # Plex
    plex_url = db.Column(db.String(200))
    plex_token = db.Column(db.String(200))
    ignored_users = db.Column(db.String(500))
    ignored_libraries = db.Column(db.String(500))
    
    # Metadata APIs
    tmdb_key = db.Column(db.String(200))
    tmdb_region = db.Column(db.String(10), default='US')
    omdb_key = db.Column(db.String(200))
    
    # Integrations
    overseerr_url = db.Column(db.String(200))
    overseerr_api_key = db.Column(db.String(200))
    tautulli_url = db.Column(db.String(200))
    tautulli_api_key = db.Column(db.String(200))
    radarr_url = db.Column(db.String(200))
    radarr_api_key = db.Column(db.String(200))
    sonarr_url = db.Column(db.String(200))
    sonarr_api_key = db.Column(db.String(200))
    
    # System
    last_checked = db.Column(db.DateTime)
    cache_interval = db.Column(db.Integer, default=24)
    logging_enabled = db.Column(db.Boolean, default=True)
    max_log_size = db.Column(db.Integer, default=5)
    
    # Backups
    backup_interval = db.Column(db.Integer, default=2) 
    backup_retention = db.Column(db.Integer, default=7) 

    # Background scanner
    scanner_enabled = db.Column(db.Boolean, default=False)
    scanner_interval = db.Column(db.Integer, default=15)
    scanner_batch = db.Column(db.Integer, default=500)
    last_alias_scan = db.Column(db.Integer, default=0)
    scanner_log_size = db.Column(db.Integer, default=10)
    kometa_config = db.Column(db.Text)
    keyword_cache_size = db.Column(db.Integer, default=3000)
    runtime_cache_size = db.Column(db.Integer, default=3000)
    
    # Radarr/Sonarr scanner
    radarr_sonarr_scanner_enabled = db.Column(db.Boolean, default=False)
    radarr_sonarr_scanner_interval = db.Column(db.Integer, default=24)  # hours
    last_radarr_sonarr_scan = db.Column(db.Integer, default=0)

class Blocklist(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    title = db.Column(db.String(200))
    media_type = db.Column(db.String(50))

class CollectionSchedule(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    preset_key = db.Column(db.String(50), unique=True, nullable=False)
    frequency = db.Column(db.String(20), default='manual') 
    last_run = db.Column(db.DateTime)
    configuration = db.Column(db.Text)

class SystemLog(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    level = db.Column(db.String(20)) 
    category = db.Column(db.String(50))
    message = db.Column(db.Text)

class TmdbAlias(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    tmdb_id = db.Column(db.Integer, nullable=False)
    media_type = db.Column(db.String(10), nullable=False)
    plex_title = db.Column(db.String(200))
    original_title = db.Column(db.String(200))
    match_year = db.Column(db.Integer)
    
class TmdbKeywordCache(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tmdb_id = db.Column(db.Integer, unique=True)
    media_type = db.Column(db.String(10))
    keywords = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.now)

class TmdbRuntimeCache(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    tmdb_id = db.Column(db.Integer, unique=True, nullable=False)
    media_type = db.Column(db.String(10), nullable=False)
    runtime = db.Column(db.Integer, nullable=False)  # minutes
    timestamp = db.Column(db.DateTime, default=datetime.now)

class AppRequest(db.Model):
    """Requests made from the app via Radarr or Sonarr (so they show on Requested tab and in logs)."""
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    tmdb_id = db.Column(db.Integer, nullable=False)
    media_type = db.Column(db.String(10), nullable=False)  # 'movie' or 'tv'
    title = db.Column(db.String(300), nullable=False)
    requested_via = db.Column(db.String(20), nullable=False)  # 'Radarr' or 'Sonarr'
    requested_at = db.Column(db.DateTime, default=datetime.now)


class RadarrSonarrCache(db.Model):
    # unique constraint on tmdb_id + media_type + source
    __table_args__ = (
        db.UniqueConstraint('tmdb_id', 'media_type', 'source', name='uq_radarr_sonarr_cache'),
        {'extend_existing': True}
    )
    id = db.Column(db.Integer, primary_key=True)
    tmdb_id = db.Column(db.Integer, nullable=False)  # TMDB ID for movies/shows
    media_type = db.Column(db.String(10), nullable=False)  # 'movie' or 'tv'
    source = db.Column(db.String(10), nullable=False)  # 'radarr' or 'sonarr'
    title = db.Column(db.String(200))  # normalized title
    original_title = db.Column(db.String(200))  # original title from API
    year = db.Column(db.Integer)  # release year
    timestamp = db.Column(db.DateTime, default=datetime.now)

class KometaTemplate(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(20))  # movie, tv, anime
    cols = db.Column(db.Text)  # JSON array of collection names
    ovls = db.Column(db.Text)  # JSON array of overlay names
    template_vars = db.Column(db.Text)  # JSON object of template variables
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    user = db.relationship('User', backref='kometa_templates')