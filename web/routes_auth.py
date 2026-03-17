"""
blueprint for authentication routes
handles login, logout, registration, password reset, and recovery codes
"""

import secrets
from flask import Blueprint, request, jsonify, redirect, url_for, render_template, session, flash, current_app
from flask_login import login_required, current_user, login_user, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import generate_csrf

from models import db, User, Settings, RecoveryCode
from utils.message_helpers import flash_success, flash_error

# create blueprint
web_auth_bp = Blueprint('web_auth', __name__)

def _no_users_exist():
    """check if no users exist, used to exempt first registration/login from rate limiting"""
    try:
        return User.query.count() == 0
    except Exception:
        return False

# get limiter from app after registration
def get_limiter():
    """grab limiter from current app"""
    return current_app.extensions.get('limiter')

@web_auth_bp.route('/')
def index():
    """index page, redirect to dashboard if logged in, otherwise login"""
    if current_user.is_authenticated:
        return redirect(url_for('web_pages.dashboard'))
    return redirect(url_for('web_auth.login'))

@web_auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """login page and form submission"""
    if current_user.is_authenticated:
        return redirect(url_for('web_pages.dashboard'))
    
    # check if no users exist, redirect to register
    if User.query.count() == 0:
        flash('No accounts exist. Please register to create the first admin account.')
        return redirect(url_for('web_auth.register'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            session['notify_tabs_login'] = True
            return redirect(url_for('web_pages.dashboard'))
        else:
            flash('Invalid credentials')
            
    return render_template('login.html')


@web_auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """registration page and form submission"""
    if current_user.is_authenticated:
        return redirect(url_for('web_pages.dashboard'))
    
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = (request.form.get('password') or '')
        if len(username) < 1 or len(username) > 150:
            flash('Username must be 1-150 characters.')
        elif len(password) < 8:
            flash('Password must be at least 8 characters.')
        elif User.query.filter_by(username=username).first():
            flash('Username already exists')
        else:
            hashed_pw = generate_password_hash(password, method='pbkdf2:sha256')
            new_user = User(username=username, password_hash=hashed_pw)
            
            db.session.add(new_user)
            db.session.commit()
            
            if User.query.count() == 1:
                new_user.is_admin = True
                db.session.commit()
            
            db.session.add(Settings(user_id=new_user.id))
            db.session.commit()
            
            # generate recovery codes and show once after registration
            count = 10
            plain_codes = [secrets.token_hex(8) for _ in range(count)]
            for plain in plain_codes:
                rec = RecoveryCode(user_id=new_user.id, code_hash=generate_password_hash(plain, method='pbkdf2:sha256'))
                db.session.add(rec)
            db.session.commit()
            session['show_recovery_codes'] = plain_codes
            
            login_user(new_user)
            session['notify_tabs_login'] = True
            return redirect(url_for('web_auth.welcome_codes'))
            
    return render_template('login.html', register=True)

@web_auth_bp.route('/logout')
@login_required
def logout():
    """logout and redirect to login page"""
    logout_user()
    # notify other tabs so they reload (logout in one tab = others see login)
    return render_template('logout_redirect.html', login_url=url_for('web_auth.login'))

@web_auth_bp.route('/reset_password', methods=['GET'])
def reset_password_page():
    """Page to reset your password using a one-time recovery code"""
    return render_template('reset_password.html')

@web_auth_bp.route('/welcome_codes')
@login_required
def welcome_codes():
    """show recovery codes once after registration, codes are in session; user must click continue to clear"""
    codes = session.get('show_recovery_codes')
    if not codes:
        return redirect(url_for('web_pages.dashboard'))
    return render_template('welcome_codes.html', codes=codes)

@web_auth_bp.route('/welcome_codes_done', methods=['GET', 'POST'])
@login_required
def welcome_codes_done():
    """clear one-time recovery codes from session and go to dashboard"""
    session.pop('show_recovery_codes', None)
    session['notify_tabs_login'] = True
    return redirect(url_for('web_pages.dashboard'))

@web_auth_bp.route('/api/csrf-token')
def csrf_token_route():
    """return current session csrf token for fetch/xhr, 401 when not logged in (so other tabs can redirect)"""
    if not current_user.is_authenticated:
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify({'csrf_token': generate_csrf()})


@web_auth_bp.route('/api/public/posters')
def get_public_posters():
    """grab a list of trending movie posters for the login background, unauthenticated"""
    import requests
    try:
        # try to get the first user's tmdb key to fetch fresh trending posters
        s = Settings.query.first()
        if s and s.tmdb_key:
            url = f"https://api.themoviedb.org/3/trending/movie/week?api_key={s.tmdb_key}"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                posters = [f"https://image.tmdb.org/t/p/original{m['poster_path']}" for m in data.get('results', []) if m.get('poster_path')]
                if posters:
                    return jsonify({'posters': posters})
    except Exception:
        pass

    # fallback high-quality posters if tmdb fails or no key set
    fallbacks = [
        "https://image.tmdb.org/t/p/original/8Gxv0mYmUctXsbS1vD9274asvBf.jpg", # Interstellar
        "https://image.tmdb.org/t/p/original/dfS9q3hlvY6PSwwabyeT6LZJpcS.jpg", # Inception
        "https://image.tmdb.org/t/p/original/qJ2tW6WMUDp9sZKsjrswHn64GvK.jpg", # The Dark Knight
        "https://image.tmdb.org/t/p/original/ow3wq89wMvEbSruS9RGUhbjLs9X.jpg", # Dune
        "https://image.tmdb.org/t/p/original/v9X97AnSntmYvOnmQUv99m6YpEq.jpg", # Oppenheimer
        "https://image.tmdb.org/t/p/original/6FfCtvT2mno1mSpmEQsF61oKEXi.jpg", # Star Wars
    ]
    return jsonify({'posters': fallbacks})
