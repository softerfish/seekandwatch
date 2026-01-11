from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    settings = db.relationship('Settings', backref='user', uselist=False)

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Plex
    plex_url = db.Column(db.String(200))
    plex_token = db.Column(db.String(200))
    ignored_users = db.Column(db.String(500))
    
    # TMDB
    tmdb_key = db.Column(db.String(200))
    tmdb_region = db.Column(db.String(10), default='US')
    
    # Overseerr
    overseerr_url = db.Column(db.String(200))
    overseerr_api_key = db.Column(db.String(200))

    # Tautulli (We keep this!)
    tautulli_url = db.Column(db.String(200))
    tautulli_api_key = db.Column(db.String(200))

class Blocklist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    media_type = db.Column(db.String(20), default='movie')