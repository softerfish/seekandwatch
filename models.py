"""database models - user accounts, settings, blocklists, etc"""

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
    recovery_codes = db.relationship('RecoveryCode', back_populates='user', cascade='all, delete-orphan')


class RecoveryCode(db.Model):
    """one-time recovery codes for password reset; stored hashed, one use only"""
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    code_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    user = db.relationship('User', back_populates='recovery_codes')


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
    
    # SeekAndWatch web app
    cloud_enabled = db.Column(db.Boolean, default=False)
    cloud_base_url = db.Column(db.String(256), nullable=True)  # e.g. https://seekandwatch.com or https://seekandwatch.com/staging; blank = use env/default
    cloud_api_key = db.Column(db.String(100))
    cloud_auto_approve = db.Column(db.Boolean, default=False)
    # direct = Radarr (for movies) or Sonarr (for TV)
    cloud_movie_handler = db.Column(db.String(20), default='direct') 
    cloud_tv_handler = db.Column(db.String(20), default='direct')
    cloud_sync_owned_enabled = db.Column(db.Boolean, default=True)  # when True, worker polls Cloud for requests (default on)
    cloud_sync_owned_interval_hours = db.Column(db.Integer, default=24)  # 12, 24, or 168 (weekly)
    last_owned_sync_at = db.Column(db.DateTime, nullable=True)  # last successful sync to Cloud
    cloud_webhook_url = db.Column(db.String(512), nullable=True)   # when set, cloud POSTs approved requests here for instant sync
    cloud_webhook_secret = db.Column(db.String(255), nullable=True)  # secret sent in X-Webhook-Secret when cloud calls webhook
    cloud_webhook_failsafe_hours = db.Column(db.Integer, default=24)  # when webhook enabled, poll every X hours as failsafe (6, 12, or 24)
    cloud_poll_interval_min = db.Column(db.Integer, nullable=True)  # seconds between polls (min); null = use config/env default
    cloud_poll_interval_max = db.Column(db.Integer, nullable=True)  # seconds between polls (max); null = use config/env default
    last_cloud_poll_at = db.Column(db.DateTime, nullable=True)   # when we last attempted a cloud poll
    last_cloud_poll_ok = db.Column(db.Boolean, nullable=True)     # True = last poll succeeded, False = failed
    quiet_webhook_logs = db.Column(db.Boolean, default=False)      # True = only log errors/filtered webhooks
    max_webhook_logs = db.Column(db.Integer, default=100)          # Max number of webhook logs to keep
    max_webhook_log_size_mb = db.Column(db.Integer, default=2)    # Max size for webhook logs in MB (deprecated, use max_webhook_logs)
    
    # Cloudflare Tunnel
    tunnel_enabled = db.Column(db.Boolean, default=False)
    tunnel_url = db.Column(db.String(512), nullable=True)
    tunnel_name = db.Column(db.String(100), nullable=True)
    tunnel_credentials_encrypted = db.Column(db.Text, nullable=True)
    tunnel_last_started = db.Column(db.DateTime, nullable=True)
    tunnel_last_error = db.Column(db.String(512), nullable=True)
    tunnel_status = db.Column(db.String(20), default='disconnected')  # disconnected, connecting, connected, error
    tunnel_restart_count = db.Column(db.Integer, default=0)
    tunnel_last_health_check = db.Column(db.DateTime, nullable=True)
    cloudflare_api_token = db.Column(db.String(255), nullable=True)  # user's cloudflare API token for creating tunnels
    cloudflare_account_id = db.Column(db.String(100), nullable=True)  # optional, auto-detected if not provided
    pairing_token = db.Column(db.String(100), nullable=True) # temporary token for zero-config cloud link
    pairing_token_expires = db.Column(db.DateTime, nullable=True)
    
    # Tunnel Auto-Recovery (phase 6: changed default to True for opt-out)
    tunnel_provider = db.Column(db.String(20), nullable=True)  # NULL, 'cloudflare', 'ngrok'
    tunnel_auto_recovery_enabled = db.Column(db.Boolean, default=True)  # phase 6: opt-out (default True)
    tunnel_consecutive_failures = db.Column(db.Integer, default=0)
    tunnel_recovery_count = db.Column(db.Integer, default=0)
    tunnel_last_recovery = db.Column(db.DateTime, nullable=True)
    tunnel_recovery_disabled = db.Column(db.Boolean, default=False)  # circuit breaker flag
    tunnel_user_stopped = db.Column(db.Boolean, default=False)  # manual stop flag
    tunnel_recovery_history = db.Column(db.Text, nullable=True)  # JSON array of last 10 recovery attempts
    
    def get_public_url(self):
        """
        returns the best available public URL for this user.
        handy to avoid checking tunnel_url vs cloud_webhook_url everywhere.
        """
        if self.tunnel_provider == 'external' and self.cloud_webhook_url:
            # use the manual webhook URL, but stripped to the base
            from urllib.parse import urlparse
            parsed = urlparse(self.cloud_webhook_url)
            # return scheme://domain (and port/path if they have one before /api/webhook)
            base = f"{parsed.scheme}://{parsed.netloc}"
            if parsed.path and '/api/webhook' in parsed.path:
                path_base = parsed.path.split('/api/webhook')[0].rstrip('/')
                if path_base:
                    base += path_base
            return base
            
        return self.tunnel_url or ''

class Blocklist(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    title = db.Column(db.String(200))
    media_type = db.Column(db.String(50))
    year = db.Column(db.Integer, nullable=True)  # release year for better identification

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
    """requests made from the app via radarr or sonarr (so they show on requested tab and in logs); scoped by user"""
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # nullable for migration; new rows set by api
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
    has_file = db.Column(db.Boolean, default=True)  # radarr hasFile / sonarr has episode files; false = "not available"
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
    
class DeletedCloudId(db.Model):
    """cloud request ids we deleted locally so we never re-import them if poll still returns them"""
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    cloud_id = db.Column(db.String(36), unique=True, nullable=False)

class WebhookLog(db.Model):
    """logs of incoming webhooks from the cloud app"""
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    event = db.Column(db.String(50))
    payload = db.Column(db.Text)
    status = db.Column(db.String(20)) # success, error, filtered
    message = db.Column(db.Text)

class CloudRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    cloud_id = db.Column(db.String(36), unique=True) # the id from the php site
    title = db.Column(db.String(255))
    media_type = db.Column(db.String(20)) # 'movie' or 'tv'
    tmdb_id = db.Column(db.Integer)
    requested_by = db.Column(db.String(100))
    year = db.Column(db.String(4), nullable=True)  # release year from cloud (optional)
    notes = db.Column(db.Text, nullable=True)  # optional notes from requester (e.g. "Season 2 only")
    status = db.Column(db.String(20), default='pending') # pending, approved, denied, completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    webhook_received_at = db.Column(db.DateTime, nullable=True)  # when webhook delivered this (if via webhook)
    webhook_process_after = db.Column(db.DateTime, nullable=True)  # when to actually process (webhook_received_at + delay)
