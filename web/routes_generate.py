"""
generate flow routes - phase 3.2g
handles recommendation generation, trending, history review, and related functionality.
"""

import concurrent.futures
import datetime
import json
import random
import threading
import time
from collections.abc import Mapping
from urllib.parse import quote_plus

import requests
from flask import Blueprint, request, jsonify, session, redirect, url_for, render_template, flash, current_app
from flask_login import login_required, current_user
from plexapi.server import PlexServer

from models import db, Blocklist, TmdbAlias, Settings
from utils import (
    get_tautulli_trending, normalize_title, is_owned_item,
    prefetch_keywords_parallel, item_matches_keywords, get_session_filters, write_log,
    handle_lucky_mode, prefetch_tv_states_parallel, prefetch_ratings_parallel,
    prefetch_omdb_parallel, prefetch_runtime_parallel, save_results_cache,
    get_history_cache, set_history_cache, score_recommendation, diverse_sample,
    get_tmdb_rec_cache, set_tmdb_rec_cache, get_results_cache, set_results_cache,
    fetch_omdb_ratings,
)
from utils.background_tasks import run_in_background
from utils.tmdb_http import tmdb_get

# create blueprint
generate_bp = Blueprint('web_generate', __name__, url_prefix='')


def _make_json_safe(value):
    """Convert values into plain JSON-safe data for results template serialization."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_make_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_make_json_safe(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _make_json_safe(val) for key, val in value.items()}
    return str(value)


def _results_template_items(items):
    """Normalize recommendation payloads before Jinja's tojson filter touches them."""
    return [_make_json_safe(item) for item in (items or [])]


@generate_bp.route('/get_local_trending')
@login_required
def get_local_trending():
    """grab trending items from tautulli"""
    m_type = request.args.get('type', 'movie')
    days = request.args.get('days', '30')
    try:
        days = int(days)
        if days < 1: days = 1
        if days > 365: days = 365
    except (ValueError, TypeError):
        days = 30
    items = get_tautulli_trending(m_type, days=days, settings=current_user.settings)
    return jsonify({'status': 'success', 'items': items})


@generate_bp.route('/reset_alias_db')
@login_required
def reset_alias_db():
    """wipe alias db to fix owned items showing up"""
    try:
        db.session.query(TmdbAlias).delete()
        s = current_user.settings
        s.last_alias_scan = 0
        db.session.commit()
        return "<h1>Alias DB Wiped.</h1><p>The scanner will now restart from scratch. Please wait 10 minutes and check logs.</p><a href='" + url_for('web_pages.dashboard') + "'>Back</a>"
    except Exception:
        write_log("error", "Wipe Database", "Failed to wipe alias database")
        return "<h1>Error</h1><p>An error occurred while wiping the alias database.</p><a href='" + url_for('web_pages.dashboard') + "'>Back</a>"


@generate_bp.route('/recommend_from_trending')
@login_required
def recommend_from_trending():
    """generate recommendations based on tautulli trending"""
    m_type = request.args.get('type', 'movie')

    # grab trending stuff from tautulli
    trending = get_tautulli_trending(m_type, settings=current_user.settings)
    if not trending:
        flash("No trending data found to base recommendations on.", "error")
        return redirect(url_for('web_pages.dashboard'))

    seed_ids = [str(x['tmdb_id']) for x in trending]

    # fetch tmdb recommendations for each trending item (in parallel)
    final_recs = []
    s = current_user.settings
    if not s:
        flash("no settings found", "error")
        return redirect(url_for('web_pages.dashboard'))
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for tid in seed_ids:
            for p in [1, 2]:  # grab 2 pages per item
                futures.append(executor.submit(tmdb_get, f"{m_type}/{tid}/recommendations", s.tmdb_key, {'language': 'en-US', 'page': p}))

        for f in concurrent.futures.as_completed(futures):
            try:
                data = f.result().json()
                final_recs.extend(data.get('results', []))
            except Exception: pass

    # remove duplicates and filter out stuff we already own
    seen = set()
    unique_recs = []

    for r in final_recs:
        if r['id'] not in seen:
            # normalize the year so we don't crash on weird dates
            date = r.get('release_date') or r.get('first_air_date')
            r['year'] = int(date[:4]) if date else 0
            r['media_type'] = m_type
            # set default runtime (will be fetched in background)
            if not r.get('runtime'):
                r['runtime'] = 0

            # check if already owned (improved duplicate detection)
            if is_owned_item(r, m_type):
                continue

            seen.add(r['id'])
            unique_recs.append(r)

    random.shuffle(unique_recs)

    # fetch runtime in background for trending recommendations (using helper)
    try:
        run_in_background(prefetch_runtime_parallel, unique_recs[:40], s.tmdb_key)
    except Exception as e:
        write_log("warning", "Generate", f"Trending runtime prefetch dispatch failed: {type(e).__name__}: {e}")

    # save to cache so "load more" works (thread-safe)
    set_results_cache(current_user.id, {
        'candidates': unique_recs,
        'next_index': 40
    })
    genres = []
    try:
        genres = tmdb_get(f"genre/{m_type}/list", s.tmdb_key, timeout=10).json().get('genres', [])
    except Exception: pass

    return render_template('results.html', movies=_results_template_items(unique_recs[:40]),
                         genres=genres, current_genre=None, min_year=0, min_rating=0)



@generate_bp.route('/review_history', methods=['POST'])
@login_required
def review_history():
    """scan plex watch history to find stuff for recommendations"""
    s = current_user.settings
    if not s:
        flash("No settings found.", "error")
        return redirect(url_for('web_pages.dashboard'))

    ignored_libs = [l.strip().lower() for l in request.form.getlist('ignored_libraries')]

    media_type = request.form.get('media_type', 'movie')
    manual_query = request.form.get('manual_query')
    limit = max(1, min(500, int(request.form.get('history_limit', 20))))

    # save filter preferences to session
    session['critic_filter'] = 'true' if request.form.get('critic_filter') else 'false'
    session['critic_threshold'] = request.form.get('critic_threshold', 70)

    candidates = []
    providers = []
    genres = []

    future_mode = request.form.get('future_mode') == 'true'
    include_obscure = request.form.get('include_obscure') == 'true'

    try:
        # manual search
        if manual_query:
            res = tmdb_get(f"search/{media_type}", s.tmdb_key, params={'query': manual_query}, timeout=10).json().get('results', [])
            if res:
                item = res[0]
                candidates.append({
                    'title': item.get('title', item.get('name')),
                    'year': (item.get('release_date') or item.get('first_air_date') or '')[:4],
                    'thumb': f"https://image.tmdb.org/t/p/w200{item.get('poster_path')}" if item.get('poster_path') else None,
                    'poster_path': item.get('poster_path')
                })

        # scan actual plex watch history
        elif s.plex_url and s.plex_token:
            plex = PlexServer(s.plex_url, s.plex_token)
            # convert library names to ids
            ignored_lib_names = [l.strip().lower() for l in request.form.getlist('ignored_libraries')]
            ignored_lib_ids = []

            if ignored_lib_names:
                try:
                    for section in plex.library.sections():
                        if section.title.lower() in ignored_lib_names:
                            ignored_lib_ids.append(str(section.key))
                except Exception: pass

            # build a map of plex user ids to their display names
            user_map = {}
            try:
                for acct in plex.systemAccounts():
                    user_map[int(acct.id)] = acct.name
            except Exception: pass

            try:
                account = plex.myPlexAccount()
                for user in account.users():
                    if user.id:
                        user_map[int(user.id)] = user.title
                if account.id:
                    user_map[int(account.id)] = account.username or "Admin"
            except Exception: pass

            ignored = [u.strip().lower() for u in (s.ignored_users or '').split(',')]

            cache_key = f"{current_user.id}:{media_type}:{limit}:{','.join(sorted(ignored))}:{','.join(sorted(ignored_lib_ids))}"
            cached_candidates = get_history_cache(cache_key)
            if cached_candidates:
                candidates = cached_candidates
            else:
                history = plex.history(maxresults=5000)
                seen_titles = set()
                lib_type = 'movie' if media_type == 'movie' else 'episode'
                title_stats = {}
                now_ts = datetime.datetime.now().timestamp()

                for h in history:
                    if h.type != lib_type:
                        continue

                    # check if user should be ignored
                    user_id = getattr(h, 'accountID', None)
                    user_name = "Unknown"
                    if user_id is not None:
                        user_name = user_map.get(int(user_id), "Unknown")

                    if user_name == "Unknown":
                        if hasattr(h, 'userName') and h.userName:
                            user_name = h.userName
                        elif hasattr(h, 'user') and hasattr(h.user, 'title'):
                            user_name = h.user.title

                    if user_name.lower() in ignored:
                        continue

                    # also skip if the library is ignored
                    if hasattr(h, 'librarySectionID') and h.librarySectionID:
                        if str(h.librarySectionID) in ignored_lib_ids:
                            continue

                    # dedupe TV shows (use show title, not episode)
                    if h.type == 'episode':
                        title = h.grandparentTitle
                    else:
                        title = h.title

                    if not title:
                        if hasattr(h, 'sourceTitle') and h.sourceTitle:
                            title = h.sourceTitle
                        else:
                            title = h.title

                    if not title:
                        continue

                    # track how often and recently this was watched (for scoring)
                    viewed_at = getattr(h, 'viewedAt', None)
                    if isinstance(viewed_at, datetime.datetime):
                        viewed_ts = viewed_at.timestamp()
                    elif isinstance(viewed_at, (int, float)):
                        viewed_ts = float(viewed_at)
                    else:
                        viewed_ts = None

                    stats = title_stats.setdefault(title, {'count': 0, 'last_viewed': 0})
                    stats['count'] += 1
                    if viewed_ts and viewed_ts > stats['last_viewed']:
                        stats['last_viewed'] = viewed_ts

                    # skip if we've seen this show already
                    if title in seen_titles:
                        continue

                    year = h.year if hasattr(h, 'year') else 0

                    # get poster (use show poster for tv)
                    thumb = None
                    try:
                        if h.type == 'episode':
                            thumb = h.grandparentThumb or h.thumb
                        else:
                            thumb = h.thumb
                    except Exception as e:
                        write_log("warning", "Generate", f"Plex poster/thumb fetch failed ({type(e).__name__})")

                    c = {
                        'title': title,
                        'year': year
                    }
                    if thumb:
                        raw_plex_url = f"{s.plex_url}{thumb}?X-Plex-Token={s.plex_token}"
                        c['thumb'] = url_for('web_utility.image_proxy', url=raw_plex_url)
                    else:
                        c['thumb'] = None
                    c['poster_path'] = None
                    candidates.append(c)
                    seen_titles.add(title)

                # score items based on how often and recently they were watched
                for c in candidates:
                    stats = title_stats.get(c['title'], {})
                    count = stats.get('count', 1)
                    last_viewed = stats.get('last_viewed', 0)
                    days_ago = (now_ts - last_viewed) / 86400 if last_viewed else 365
                    recency = 1 / (1 + max(days_ago, 0))
                    c['score'] = (count * 0.7) + (recency * 0.3)

                candidates.sort(key=lambda x: x.get('score', 0), reverse=True)
                candidates = candidates[:limit]
                set_history_cache(cache_key, candidates)

    except Exception as e:
        write_log("error", "Review History", f"Scan failed: {e}")
        flash("scan failed, please check your plex connection and try again", "error")
        return redirect(url_for('web_pages.dashboard'))

    # fetch providers and genres in parallel
    def _fetch_providers():
        try:
            reg = s.tmdb_region.split(',')[0] if s.tmdb_region else 'US'
            p_data = tmdb_get(f"watch/providers/{media_type}", s.tmdb_key, params={'watch_region': reg}, timeout=10).json().get('results', [])
            providers[:] = sorted(p_data, key=lambda x: x.get('display_priority', 999))[:30]
        except Exception:
            write_log("warning", "Review History", "Failed to fetch providers")
    def _fetch_genres():
        try:
            genres[:] = tmdb_get(f"genre/{media_type}/list", s.tmdb_key, timeout=10).json().get('genres', [])
        except Exception:
            write_log("warning", "Review History", "Failed to fetch genres")
    t_prov = threading.Thread(target=_fetch_providers)
    t_gen = threading.Thread(target=_fetch_genres)
    t_prov.start()
    t_gen.start()
    t_prov.join()
    t_gen.join()

    return render_template('review.html',
                           movies=candidates,
                           media_type=media_type,
                           providers=providers,
                           genres=genres,
                           future_mode=future_mode,
                           include_obscure=include_obscure,
                           has_tmdb_key=bool(s and s.tmdb_key),
                           has_plex=bool(s and s.plex_url and s.plex_token))



@generate_bp.route('/generate', methods=['POST'])
@login_required
def generate():
    """core recommendation engine, generates personalized recommendations"""
    s = current_user.settings
    if not s:
        flash("No settings found. Please complete Settings (for example, add your TMDB API Read Access Token) first.", "error")
        return redirect(url_for('web_pages.dashboard'))
    if not (s.tmdb_key or '').strip():
        flash("TMDB API Read Access Token is required for recommendations. Add it in Settings > APIs & Connections.", "error")
        return redirect(url_for('web_pages.dashboard'))

    # "I'm feeling lucky" just pulls a few random popular movies
    if request.form.get('lucky_mode') == 'true':
        raw_candidates = handle_lucky_mode(s)
        if not raw_candidates:
             flash("Could not find a lucky pick!", "error")
             return redirect(url_for('web_pages.dashboard'))

        lucky_result = []
        # keep going until we find 5 movies the user doesn't already own
        page = 1
        max_pages = 10
        while len(lucky_result) < 5 and page <= max_pages:
            # if we've exhausted the current candidates, fetch more
            if page > 1 or len(raw_candidates) == 0:
                try:
                    random_genre = random.choice([28, 35, 18, 878, 27, 53])
                    data = tmdb_get('discover/movie', s.tmdb_key, params={'with_genres': random_genre, 'sort_by': 'popularity.desc', 'page': page}, timeout=10).json().get('results', [])
                    raw_candidates = [{'id': p['id'], 'title': p['title'], 'year': (p.get('release_date') or '')[:4], 'poster_path': p.get('poster_path'), 'overview': p.get('overview'), 'vote_average': p.get('vote_average'), 'media_type': 'movie'} for p in data]
                    random.seed(int(time.time() * 1000))
                    random.shuffle(raw_candidates)
                    random.seed()
                except Exception as e:
                    write_log("warning", "Generate", f"Lucky mode page fetch failed ({type(e).__name__})")
                    break

            for item in raw_candidates:
                if len(lucky_result) >= 5:
                    break

                # start with 0; the real runtime gets filled in later
                if not item.get('runtime'):
                    item['runtime'] = 0

                # skip anything the user already owns
                if is_owned_item(item, 'movie'):
                    continue

                lucky_result.append(item)

            page += 1

        if not lucky_result:
             flash("You own all the lucky picks! Try again.", "error")
             return redirect(url_for('web_pages.dashboard'))

        genres = []
        try:
            genres = tmdb_get('genre/movie/list', s.tmdb_key, timeout=10).json().get('genres', [])
        except Exception: pass

        # fill in runtimes in the background
        try:
            run_in_background(prefetch_runtime_parallel, lucky_result, s.tmdb_key)
        except Exception as e:
            write_log("warning", "Generate", f"Lucky runtime prefetch dispatch failed: {type(e).__name__}: {e}")

        # frontend expects a title key
        for item in lucky_result:
            if not item.get('title') and item.get('name'):
                item['title'] = item['name']

        set_results_cache(current_user.id, {'candidates': lucky_result, 'next_index': len(lucky_result)})
        return render_template('results.html',
                               movies=_results_template_items(lucky_result),
                               min_year=0,
                               min_rating=0,
                               genres=genres,
                               current_genre=None,
                               use_critic_filter='false',
                               is_lucky=True)

    # standard recommendation mode
    media_type = request.form.get('media_type')
    selected_titles = request.form.getlist('selected_movies')

    session['media_type'] = media_type
    session['selected_titles'] = selected_titles
    session['genre_filter'] = request.form.getlist('genre_filter')
    session['keywords'] = request.form.get('keywords', '')

    try: session['min_year'] = max(0, min(2100, int(request.form.get('min_year', 0))))
    except Exception: session['min_year'] = 0
    try: session['min_rating'] = float(request.form.get('min_rating', 0))
    except Exception: session['min_rating'] = 0
    try:
        max_runtime = int(request.form.get('max_runtime', 9999))
        session['max_runtime'] = max_runtime if max_runtime > 0 else 9999
    except Exception:
        session['max_runtime'] = 9999

    if not selected_titles:
        flash('Please select at least one item.', 'error')
        return redirect(url_for('web_pages.dashboard'))

    blocked = set([b.title for b in Blocklist.query.filter_by(user_id=current_user.id).all()])

    recommendations = []
    seen_ids = set()
    seed_ids = []

    def resolve_title_to_id(title):
        try:
            r = tmdb_get(f"search/{media_type}", s.tmdb_key, params={'query': title}, timeout=10).json()
            if r.get('results'):
                return r['results'][0]['id']
        except Exception:
            pass
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        resolved = list(executor.map(resolve_title_to_id, selected_titles))
    seed_ids = [tid for tid in resolved if tid is not None]
    # keep seed count down so TMDB calls don't drag
    max_seeds = 10
    if len(seed_ids) > max_seeds:
        write_log("info", "Generate", f"Capping seeds from {len(seed_ids)} to {max_seeds} to reduce timeout risk.")
        seed_ids = seed_ids[:max_seeds]
    if not seed_ids:
        write_log("warning", "Generate", "No TMDB IDs resolved from selected titles; check TMDB API Read Access Token and titles.")
        flash("Could not find any of the selected titles on TMDB. Check your TMDB API Read Access Token in Settings.", "error")
        return redirect(url_for('web_pages.dashboard'))

    future_mode = request.form.get('future_mode') == 'true'
    include_obscure = request.form.get('include_obscure') == 'true'
    today = datetime.datetime.now().strftime('%Y-%m-%d')

    # grab the app object before we hop into threads
    app_obj = current_app._get_current_object()

    def fetch_seed_results(tmdb_id):
        """Fetch recommendations for a single seed (with app context for logging/cache)"""
        with app_obj.app_context():
            return _fetch_seed_results_impl(tmdb_id)

    def _fetch_seed_results_impl(tmdb_id):
        # keep the cache key simple; we shuffle later
        cache_key = f"{media_type}:{tmdb_id}:{'future' if future_mode else 'recs'}:{today}"
        cached = get_tmdb_rec_cache(cache_key)
        if cached:
            return cached

        try:
            if future_mode:
                details = tmdb_get(f"{media_type}/{tmdb_id}", s.tmdb_key, timeout=10).json()
                genres = [str(g['id']) for g in details.get('genres', [])[:3]]
                genre_str = "|".join(genres)

                params = {
                    'language': 'en-US',
                    'sort_by': 'popularity.desc',
                    'with_genres': genre_str,
                    'with_original_language': 'en',
                    'popularity.gte': 5,
                    'page': 1
                }

                if media_type == 'movie':
                    params['primary_release_date.gte'] = today
                    params['with_release_type'] = '3|2'
                    params['region'] = 'US'
                else:
                    params['first_air_date.gte'] = today
                    params['include_null_first_air_dates'] = 'false'
                    params['with_origin_country'] = 'US'

                data = tmdb_get(f"discover/{media_type}", s.tmdb_key, params=params, timeout=10).json()
                results = data.get('results', [])
            else:
                # pull a few pages per seed so the pool isn't tiny
                results = []
                for page_num in range(1, 6):
                    page_data = tmdb_get(f"{media_type}/{tmdb_id}/recommendations", s.tmdb_key, params={'language': 'en-US', 'page': page_num}, timeout=10).json()
                    if page_data.get('status_code'):
                        write_log("warning", "Generate", f"TMDB recommendations error for {media_type} {tmdb_id}: {page_data.get('status_message', page_data.get('status_code'))}")
                        continue  # TMDB errored on this page
                    results.extend(page_data.get('results', []))

                # niche titles often have empty recs, so try similar next
                if not results:
                    similar_key = f"{media_type}:{tmdb_id}:similar:{today}"
                    cached_similar = get_tmdb_rec_cache(similar_key)
                    if cached_similar:
                        results = cached_similar
                    else:
                        for page_num in range(1, 6):
                            sim_data = tmdb_get(f"{media_type}/{tmdb_id}/similar", s.tmdb_key, params={'language': 'en-US', 'page': page_num}, timeout=10).json()
                            if sim_data.get('status_code'):
                                write_log("warning", "Generate", f"TMDB similar error for {media_type} {tmdb_id}: {sim_data.get('status_message', sim_data.get('status_code'))}")
                                continue
                            results.extend(sim_data.get('results', []))
                        if results:
                            set_tmdb_rec_cache(similar_key, results)

                # still nothing? fall back to a genre-based discover call
                if not results:
                    disc_key = f"{media_type}:{tmdb_id}:discover:{today}"
                    cached_disc = get_tmdb_rec_cache(disc_key)
                    if cached_disc:
                        results = cached_disc
                    else:
                        try:
                            details = tmdb_get(f"{media_type}/{tmdb_id}", s.tmdb_key, timeout=10).json()
                            if not details.get('status_code'):
                                genres = details.get('genres', [])[:3]
                                if genres:
                                    genre_str = "|".join(str(g['id']) for g in genres)
                                    params = {
                                        'language': 'en-US',
                                        'sort_by': 'popularity.desc',
                                        'with_genres': genre_str,
                                        'page': 1
                                    }
                                    if not include_obscure:
                                        params['with_original_language'] = 'en'
                                    data = tmdb_get(f"discover/{media_type}", s.tmdb_key, params=params, timeout=10).json()
                                    if not data.get('status_code'):
                                        results = data.get('results', [])
                                        if results:
                                            set_tmdb_rec_cache(disc_key, results)
                        except Exception as disc_e:
                            write_log("warning", "Generate", f"Discover fallback for {tmdb_id} failed: {disc_e}")

            if results:
                set_tmdb_rec_cache(cache_key, results)
            return results
        except Exception as e:
            write_log("warning", "Generate", f"Fetch seed {tmdb_id} failed: {type(e).__name__}: {e}")
            return []


    # fetch recommendations from all seeds, filtering owned items as we go
    all_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        for results in executor.map(fetch_seed_results, seed_ids):
            all_results.extend(results)
    raw_count = len(all_results)
    used_last_resort = False

    # if every seed came back empty, fall back to plain popular discover results
    if raw_count == 0:
        try:
            base_params = {'language': 'en-US', 'sort_by': 'popularity.desc'}
            if not include_obscure:
                base_params['with_original_language'] = 'en'
            all_results = []
            # start on a random page so this doesn't feel the same every time
            start_page = random.randint(1, 10)
            for page_num in range(start_page, start_page + 10):
                params = dict(base_params, page=page_num)
                data = tmdb_get(f"discover/{media_type}", s.tmdb_key, params=params, timeout=10).json()
                if data.get('status_code'):
                    break
                all_results.extend(data.get('results', []))
            if all_results:
                raw_count = len(all_results)
                used_last_resort = True
        except Exception as e:
            write_log("warning", "Generate", f"Last-resort discover failed: {e}")

    if used_last_resort:
        write_log("info", "Generate", f"TMDB returned {raw_count} raw recommendations (last-resort discover; seeds had 0).")
    else:
        write_log("info", "Generate", f"TMDB returned {raw_count} raw recommendations from {len(seed_ids)} seeds.")

    # shuffle all results once before processing to get variety
    random.shuffle(all_results)

    # keep the vote floor low unless we already have a big pool
    vote_min = 10 if raw_count < 100 else 20
    # now filter and process
    for item in all_results:
        if item['id'] in seen_ids: continue

        # filter out weak picks unless the user asked for obscure stuff
        if not include_obscure:
            # standard mode stays with English-language picks
            if item.get('original_language') != 'en': continue

            # skip titles with barely any votes
            if not future_mode and item.get('vote_count', 0) < vote_min: continue

        item['media_type'] = media_type
        date = item.get('release_date') or item.get('first_air_date')
        item['year'] = int(date[:4]) if date else 0
        item['score'] = score_recommendation(item)
        # start with 0; runtime gets filled in later
        if not item.get('runtime'):
            item['runtime'] = 0 if media_type == 'tv' else 0  # filled in later

        if item.get('title', item.get('name')) in blocked: continue

        # check if already owned (improved duplicate detection)
        is_owned = is_owned_item(item, media_type)
        if is_owned:
            continue

        recommendations.append(item)
        seen_ids.add(item['id'])
    if raw_count and not recommendations:
        write_log("warning", "Generate", f"All {raw_count} raw recs were filtered out (lang/vote/blocked/owned). Try enabling International & Obscure.")
    # sort by score (popularity + votes)
    recommendations.sort(key=lambda x: x.get('score', 0), reverse=True)
    if include_obscure:
        # if user wants diverse/obscure stuff, mix it up by genre and decade
        def bucket_fn(item):
            genre_ids = item.get('genre_ids') or []
            if genre_ids:
                return genre_ids[0]
            year = item.get('year', 0)
            return year // 10
        recommendations = diverse_sample(recommendations, len(recommendations), bucket_fn=bucket_fn)

    # one more dedupe pass just to be safe
    unique_recs = []
    seen_final = set()
    for item in recommendations:
        if item['id'] not in seen_final:
            unique_recs.append(item)
            seen_final.add(item['id'])

    # shuffle results so they're different each time (use timestamp as seed for variety)
    random.seed(int(time.time() * 1000))
    random.shuffle(unique_recs)
    random.seed()  # reset to default random seed

    set_results_cache(current_user.id, {
        'candidates': unique_recs,
        'next_index': 0,
        'ts': int(time.time()),
        'sorted': False  # mark as not sorted since we shuffled
    })
    save_results_cache()

    # apply filters (use form values; session was set earlier)
    min_year, min_rating, genre_filter, critic_enabled, threshold = get_session_filters()
    # "All genres" selected (long list) = no genre filter
    if isinstance(genre_filter, list) and len(genre_filter) >= 15:
        genre_filter = None
    rating_filter = request.form.getlist('rating_filter')
    session['rating_filter'] = rating_filter
    raw_keywords = session.get('keywords', '')
    target_keywords = [k.strip() for k in raw_keywords.split('|') if k.strip()]

    # use shuffled list for display, not sorted recommendations
    try:
        prefetch_ratings_parallel(unique_recs[:60], s.tmdb_key)
    except Exception as e:
        write_log("warning", "Generate", f"Ratings prefetch failed: {type(e).__name__}: {e}")
    # Fetch runtime in background to not block initial render (using helper)
    try:
        run_in_background(prefetch_runtime_parallel, unique_recs[:60], s.tmdb_key)
    except Exception as e:
        write_log("warning", "Generate", f"Runtime prefetch dispatch failed: {type(e).__name__}: {e}")

    if s.omdb_key:
        try:
            prefetch_omdb_parallel(unique_recs[:80], s.omdb_key)
        except Exception as e:
            write_log("warning", "Generate", f"OMDb prefetch failed: {type(e).__name__}: {e}")

    if target_keywords:
        try:
            prefetch_keywords_parallel(unique_recs, s.tmdb_key)
        except Exception as e:
            write_log("warning", "Generate", f"Keyword prefetch failed: {type(e).__name__}: {e}")
    else:
        try:
            run_in_background(prefetch_keywords_parallel, unique_recs, s.tmdb_key)
        except Exception as e:
            write_log("warning", "Generate", f"Keyword prefetch dispatch failed: {type(e).__name__}: {e}")

    final_list = []
    idx = 0

    # use shuffled unique_recs instead of sorted recommendations
    while len(final_list) < 40 and idx < len(unique_recs):
        item = unique_recs[idx]
        idx += 1

        if item['year'] < min_year: continue
        # skip rating check in future mode (upcoming movies have 0 rating)
        if not future_mode and item.get('vote_average', 0) < min_rating: continue

        # runtime filter (if set in session)
        max_runtime = session.get('max_runtime', 9999)
        if max_runtime and max_runtime < 9999:
            item_runtime = item.get('runtime', 9999)
            if item_runtime > max_runtime: continue

        if rating_filter:
            c_rate = item.get('content_rating', 'NR')
            if c_rate not in rating_filter: continue

        if genre_filter and genre_filter != 'all':
            try:
                allowed_ids = [int(g) for g in genre_filter] if isinstance(genre_filter, list) else [int(genre_filter)]
                item_genres = item.get('genre_ids') or []
                if item_genres and not any(gid in allowed_ids for gid in item_genres):
                    continue
            except Exception:
                pass

        # check if it matches the keyword filter
        if target_keywords:
            if not item_matches_keywords(item, target_keywords): continue

        # grab rotten tomatoes score if we have OMDB key
        item['rt_score'] = None
        if s.omdb_key:
            if item.get('rt_score') is None and critic_enabled:
                ratings = fetch_omdb_ratings(item.get('title', item.get('name')), item['year'], s.omdb_key)
                rt_score = 0
                for r in (ratings or []):
                    if r['Source'] == 'Rotten Tomatoes':
                        rt_score = int(r['Value'].replace('%',''))
                        break
                if rt_score > 0:
                    item['rt_score'] = rt_score
            # Only exclude by critic when we have an actual RT score below threshold; missing score = include
            rt = item.get('rt_score') or 0
            if critic_enabled and rt > 0 and rt < threshold:
                continue

        final_list.append(item)

    if media_type == 'tv':
        try:
            prefetch_tv_states_parallel(final_list, s.tmdb_key)
        except Exception as e:
            write_log("warning", "Generate", f"TV state prefetch failed: {type(e).__name__}: {e}")

    # Update next_index in cache (thread-safe)
    cache = get_results_cache(current_user.id)
    if cache:
        cache['next_index'] = idx
        set_results_cache(current_user.id, cache)
    save_results_cache()

    # ensure every item has a 'title' key (TMDB TV uses 'name')
    for item in final_list:
        if not item.get('title') and item.get('name'):
            item['title'] = item['name']

    if not final_list:
        write_log("warning", "Generate", f"No results after filters (had {len(unique_recs)} recs, seeds={len(seed_ids)}). Try lowering min rating/year or enabling International & Obscure.")
        if raw_count == 0:
            flash("TMDB returned no recommendations for your selected titles. Try different titles or enable International & Obscure.", "error")
        else:
            flash("No recommendations matched your filters. Try lowering min rating/year or enabling International & Obscure.", "error")
        return redirect(url_for('web_pages.dashboard'))

    try: genres = tmdb_get(f"genre/{media_type}/list", s.tmdb_key, timeout=10).json().get('genres', [])
    except Exception:
        write_log("warning", "Generate", "Failed to fetch genres")
        genres = []

    return render_template('results.html',
                           movies=_results_template_items(final_list),
                           genres=genres,
                           current_genre=genre_filter,
                           min_year=min_year,
                           min_rating=min_rating,
                           use_critic_filter='true' if critic_enabled else 'false',
                           is_lucky=False)
