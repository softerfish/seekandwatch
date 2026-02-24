"""Webhook routes - receive approved requests from cloud app."""

from flask import request, jsonify
from flask_login import login_required
from api import api_bp, rate_limit_decorator
from models import db, Settings, CloudRequest
from services.CloudService import CloudService
from config import SCHEDULER_USER_ID
import logging

@api_bp.route('/webhook', methods=['POST'])
@rate_limit_decorator("30 per minute")
def receive_webhook():
    """
    Receive webhook from cloud app when requests are approved.
    """
    # If CSRF is present, we must exempt this API route
    try:
        from app import csrf
        if csrf and hasattr(csrf, 'exempt'):
            csrf.exempt(receive_webhook)
    except: pass
        
    print("--- WEBHOOK INBOUND ---", flush=True)
    try:
        # get webhook secret from settings
        settings = Settings.query.filter_by(user_id=SCHEDULER_USER_ID).first() if SCHEDULER_USER_ID is not None else None
        if settings is None:
            settings = Settings.query.first()
        
        if not settings:
            print("Webhook Error: No settings found in database", flush=True)
            return jsonify({'error': 'Configuration error'}), 500
        
        # Diagnostic: Show masked key hash
        import hmac
        local_key = getattr(settings, 'cloud_api_key', '')
        print(f"DEBUG: Configured User ID: {settings.user_id}", flush=True)
        
        webhook_secret = getattr(settings, 'cloud_webhook_secret', None) or ''
        provided_secret = request.headers.get('X-Webhook-Secret', '')
        
        print(f"Webhook IP: {request.remote_addr}", flush=True)
        
        # verify webhook secret if configured
        if webhook_secret:
            if not hmac.compare_digest(provided_secret, webhook_secret):
                print("Webhook Error: Secret mismatch!", flush=True)
                return jsonify({'error': 'Invalid webhook secret'}), 401
        
        # parse payload
        payload = request.get_json()
        if not payload:
            print("Webhook Error: Received empty or invalid JSON", flush=True)
            return jsonify({'error': 'Invalid JSON'}), 400
        
        event = payload.get('event', '')
        requests_data = payload.get('requests', [])
        print(f"Webhook Event: {event} ({len(requests_data)} items)", flush=True)

        if event == 'test_connection':
            print("--- WEBHOOK TEST SUCCESSFUL! ---", flush=True)
            return jsonify({'status': 'success', 'message': 'Test received'}), 200
        
        if not isinstance(requests_data, list):
            return jsonify({'error': 'Invalid requests format'}), 400
        
        # notify cloud worker that webhook was received (backs off polling)
        CloudService.set_last_webhook_received()
        
        # process approved requests
        if event == 'approved':
            import threading
            from flask import current_app
            
            # Extract data first to avoid thread-safety issues with request object
            requests_to_process = []
            for req_data in requests_data:
                cloud_id = req_data.get('id', '')
                title = req_data.get('title', 'Unknown')
                media_type = req_data.get('media_type', 'movie')
                tmdb_id = req_data.get('tmdb_id', 0)
                year = req_data.get('year')
                requested_by = req_data.get('requested_by', '')
                notes = req_data.get('notes', '')
                
                if not tmdb_id: continue
                
                # Update/Save to DB immediately so it's tracked
                existing = CloudRequest.query.filter_by(cloud_id=cloud_id).first() if cloud_id else None
                if existing:
                    req_db = existing
                    req_db.title = title
                    req_db.media_type = media_type
                    req_db.tmdb_id = tmdb_id
                    req_db.year = year
                    req_db.requested_by = requested_by
                    req_db.notes = notes
                    req_db.status = 'pending'
                else:
                    req_db = CloudRequest(
                        cloud_id=cloud_id,
                        title=title,
                        media_type=media_type,
                        tmdb_id=tmdb_id,
                        year=year,
                        requested_by=requested_by,
                        notes=notes,
                        status='pending'
                    )
                    db.session.add(req_db)
                
                requests_to_process.append(cloud_id)
            
            db.session.commit()

            # Process in background
            def run_async_process(app_obj, ids):
                with app_obj.app_context():
                    # Re-fetch settings in this thread
                    s_obj = Settings.query.filter_by(user_id=SCHEDULER_USER_ID).first() if SCHEDULER_USER_ID is not None else Settings.query.first()
                    for cid in ids:
                        r = CloudRequest.query.filter_by(cloud_id=cid).first()
                        if r:
                            print(f"Background Thread: Processing {r.title}", flush=True)
                            if CloudService.process_item(s_obj, r):
                                print(f"SUCCESS: Processed {r.title}", flush=True)
                                CloudService.log_cloud_import('webhook_approved', r.title, r.media_type, True)
                            else:
                                print(f"FAILED: Could not process {r.title}", flush=True)
                                CloudService.log_cloud_import('webhook_approved', r.title, r.media_type, False)

            threading.Thread(
                target=run_async_process, 
                args=(current_app._get_current_object(), requests_to_process),
                daemon=True
            ).start()
            
            return jsonify({
                'success': True,
                'message': f'Queued {len(requests_to_process)} requests for background processing'
            }), 200
        
        # handle other event types (new_pending, etc.)
        elif event == 'new_pending':
            # just acknowledge, don't process (owner needs to approve first)
            for req_data in requests_data:
                # Add/Update pending requests
                title = req_data.get('title', 'Unknown')
                media_type = req_data.get('media_type', 'movie')
                cloud_id = req_data.get('id', '')
                existing = CloudRequest.query.filter_by(cloud_id=cloud_id).first() if cloud_id else None
                if not existing:
                    req_db = CloudRequest(
                        cloud_id=cloud_id,
                        title=title,
                        media_type=media_type,
                        tmdb_id=req_data.get('tmdb_id', 0),
                        year=req_data.get('year'),
                        requested_by=req_data.get('requested_by', ''),
                        notes=req_data.get('notes', ''),
                        status='pending'
                    )
                    db.session.add(req_db)
                    db.session.commit()
                    CloudService.log_cloud_import('webhook_pending', title, media_type, True)

            CloudService.set_last_webhook_received()
            return jsonify({'success': True, 'message': 'Pending request notification received'}), 200
        
        else:
            return jsonify({'error': f'Unknown event type: {event}'}), 400
    
    except Exception:
        print("Webhook error: An unexpected error occurred", flush=True)
        return jsonify({'error': 'Internal server error'}), 500
