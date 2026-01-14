from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(150), nullable=False)
    settings = db.relationship('Settings', backref='user', uselist=False)

class Settings(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    
    # Plex Settings
    plex_url = db.Column(db.String(200))
    plex_token = db.Column(db.String(200))
    ignored_users = db.Column(db.String(500))
    
    # Metadata Settings
    tmdb_key = db.Column(db.String(200))
    tmdb_region = db.Column(db.String(10), default='US')
    omdb_key = db.Column(db.String(200))
    
    # Integration Settings
    overseerr_url = db.Column(db.String(200))
    overseerr_api_key = db.Column(db.String(200))
    tautulli_url = db.Column(db.String(200))
    tautulli_api_key = db.Column(db.String(200))
    
    # Backup Settings
    backup_interval = db.Column(db.Integer, default=2)
    backup_retention = db.Column(db.Integer, default=7)

    # Cache & Logging
    cache_interval = db.Column(db.Integer, default=24)
    logging_enabled = db.Column(db.Boolean, default=True)
    max_log_size = db.Column(db.Integer, default=5)

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
    level = db.Column(db.String(10))
    module = db.Column(db.String(50))
    message = db.Column(db.String(500))

class TmdbAlias(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    tmdb_id = db.Column(db.Integer, index=True)
    media_type = db.Column(db.String(10))
    aliases = db.Column(db.Text) # Stores JSON string