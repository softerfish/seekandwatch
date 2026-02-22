"""Webhook routes - receive approved requests from SeekAndWatch Cloud."""

import hashlib
import hmac
import json
import time
from flask import request, jsonify
from api import api_bp
from models import db, Settings, CloudRequest, DeletedCloudId
from utils import write_log

@api_bp.route('/api/webhook/approved', methods=['POST'])
def webhook_approved():
    """
    Receives approved request notifications from the cloud.
    Cloud POSTs here when a request is approved for instant sync (no polling needed).
    """
    try:
        # grab the payload
        if not request.is_json:
            return jsonify({'status': 'error', 'message': 'Content-Type must be application/json'}), 400
        
        payload = request.get_json()
        if not payload:
            return jsonify({'status': 'error', 'message': 'Empty payload'}), 400
        
        # verify webhook secret (check all users with non-null secrets)
        secret_header = request.headers.get('X-Webhook-Secret', '').strip()
        if not secret_header:
            write_log('webhook', 'Webhook call missing X-Webhook-Secret header', 'warning')
            return jsonify({'status': 'error', 'message': 'Missing webhook secret'}), 401
        
        # find a user with matching webhook secret
        settings_list = Settings.query.filter(Settings.cloud_webhook_secret.isnot(None)).all()
        matched_settings = None
        for s in settings_list:
            if s.cloud_webhook_secret and s.cloud_webhook_secret.strip() == secret_header:
                matched_settings = s
                break
        
        if not matched_settings:
            write_log('webhook', 'Webhook secret does not match any user', 'warning')
            return jsonify({'status': 'error', 'message': 'Invalid webhook secret'}), 401
        
        # handle test event (from test webhook button)
        event_type = payload.get('event', 'approved')
        if event_type == 'test':
            write_log('webhook', f'Test webhook received for user {matched_settings.user_id}', 'info')
            return jsonify({'status': 'success', 'message': 'Test webhook received'}), 200
        
        # extract request data
        cloud_id = payload.get('id')
        title = payload.get('title')
        media_type = payload.get('media_type')
        tmdb_id = payload.get('tmdb_id')
        requested_by = payload.get('requested_by', 'Unknown')
        year = payload.get('year')
        notes = payload.get('notes')
        
        if not all([cloud_id, title, media_type, tmdb_id]):
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400
        
        # check if we already have this request or deleted it
        existing = CloudRequest.query.filter_by(cloud_id=cloud_id).first()
        if existing:
            write_log('webhook', f'Request {cloud_id} already exists locally', 'info')
            return jsonify({'status': 'success', 'message': 'Request already exists'}), 200
        
        deleted = DeletedCloudId.query.filter_by(cloud_id=cloud_id).first()
        if deleted:
            write_log('webhook', f'Request {cloud_id} was previously deleted, ignoring', 'info')
            return jsonify({'status': 'success', 'message': 'Request was deleted'}), 200
        
        # create the request
        new_request = CloudRequest(
            cloud_id=cloud_id,
            title=title,
            media_type=media_type,
            tmdb_id=tmdb_id,
            requested_by=requested_by,
            year=year,
            notes=notes,
            status='approved'
        )
        db.session.add(new_request)
        db.session.commit()
        
        write_log('webhook', f'Received approved request via webhook: {title} ({media_type}, TMDB {tmdb_id})', 'info')
        
        return jsonify({
            'status': 'success',
            'message': 'Request received',
            'cloud_id': cloud_id
        }), 200
        
    except Exception as e:
        write_log('webhook', f'Webhook error: {str(e)}', 'error')
        return jsonify({'status': 'error', 'message': 'Internal error'}), 500


@api_bp.route('/api/webhook/test', methods=['POST'])
def webhook_test():
    """
    Test endpoint for webhook functionality.
    Called by the local app's test webhook button.
    """
    try:
        # this is called by the local app itself to test if the cloud can reach us
        # the cloud will call /api/webhook/approved with event=test
        return jsonify({
            'status': 'success',
            'message': 'Webhook endpoint is reachable'
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
