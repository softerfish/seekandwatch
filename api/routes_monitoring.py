"""
monitoring api routes - phase 1 safety infrastructure

admin-only endpoints for viewing metrics, feature flags, and migration status.
helps monitor the refactoring progress and identify issues.
"""

from flask import jsonify, request
from flask_login import login_required
from auth_decorators import admin_required
from api import api_bp
from utils.monitoring import (
    get_metrics,
    get_error_summary,
    get_migration_status,
    reset_metrics,
    get_uptime,
)
from utils.feature_flags import (
    get_all_flags,
    enable,
    disable,
    reload_flags,
    FeatureFlags,
)


@api_bp.route('/admin/metrics')
@login_required
@admin_required
def get_metrics_api():
    """grab performance metrics for all operations"""
    try:
        operation = request.args.get('operation')
        metrics = get_metrics(operation)
        uptime = get_uptime()
        
        return jsonify({
            'status': 'success',
            'uptime_seconds': uptime.total_seconds(),
            'metrics': metrics if isinstance(metrics, list) else [metrics]
        })
    except Exception:
        from api.helpers import _log_api_exception
        _log_api_exception("metrics")
        return jsonify({'status': 'error', 'message': 'Failed to retrieve metrics'}), 500


@api_bp.route('/admin/metrics/errors')
@login_required
@admin_required
def get_errors_api():
    """grab error summary"""
    try:
        errors = get_error_summary()
        return jsonify({
            'status': 'success',
            'errors': errors,
            'total_errors': sum(errors.values())
        })
    except Exception:
        from api.helpers import _log_api_exception
        _log_api_exception("metrics/errors")
        return jsonify({'status': 'error', 'message': 'Failed to retrieve error summary'}), 500


@api_bp.route('/admin/metrics/reset', methods=['POST'])
@login_required
@admin_required
def reset_metrics_api():
    """reset all metrics"""
    try:
        reset_metrics()
        return jsonify({
            'status': 'success',
            'message': 'Metrics reset successfully'
        })
    except Exception:
        from api.helpers import _log_api_exception
        _log_api_exception("metrics/reset")
        return jsonify({'status': 'error', 'message': 'Failed to reset metrics'}), 500


@api_bp.route('/admin/migration/status')
@login_required
@admin_required
def get_migration_status_api():
    """grab migration status for all features (shows which code paths are being used, old vs new)"""
    try:
        status = get_migration_status()
        return jsonify({
            'status': 'success',
            'features': status
        })
    except Exception:
        from api.helpers import _log_api_exception
        _log_api_exception("migration/status")
        return jsonify({'status': 'error', 'message': 'Failed to retrieve migration status'}), 500


@api_bp.route('/admin/feature-flags')
@login_required
@admin_required
def get_feature_flags_api():
    """grab all feature flags and their states"""
    try:
        flags = get_all_flags()
        return jsonify({
            'status': 'success',
            'flags': flags
        })
    except Exception:
        from api.helpers import _log_api_exception
        _log_api_exception("feature-flags")
        return jsonify({'status': 'error', 'message': 'Failed to retrieve feature flags'}), 500


@api_bp.route('/admin/feature-flags/<flag_name>', methods=['POST'])
@login_required
@admin_required
def toggle_feature_flag_api(flag_name):
    """enable or disable a feature flag"""
    try:
        data = request.get_json() or {}
        enabled = data.get('enabled', False)
        
        # Find the flag enum
        flag = None
        for f in FeatureFlags:
            if f.value == flag_name:
                flag = f
                break
        
        if not flag:
            return jsonify({
                'status': 'error',
                'message': f'Unknown feature flag: {flag_name}'
            }), 400
        
        if enabled:
            enable(flag)
        else:
            disable(flag)
        
        return jsonify({
            'status': 'success',
            'flag': flag_name,
            'enabled': enabled,
            'message': f'Feature flag {flag_name} {"enabled" if enabled else "disabled"}'
        })
    except Exception:
        from api.helpers import _log_api_exception
        _log_api_exception("feature-flags/toggle")
        return jsonify({'status': 'error', 'message': 'Failed to toggle feature flag'}), 500


@api_bp.route('/admin/feature-flags/reload', methods=['POST'])
@login_required
@admin_required
def reload_feature_flags_api():
    """reload feature flags from config file and environment"""
    try:
        reload_flags()
        flags = get_all_flags()
        return jsonify({
            'status': 'success',
            'message': 'Feature flags reloaded',
            'flags': flags
        })
    except Exception:
        from api.helpers import _log_api_exception
        _log_api_exception("feature-flags/reload")
        return jsonify({'status': 'error', 'message': 'Failed to reload feature flags'}), 500


@api_bp.route('/admin/health/detailed')
@login_required
@admin_required
def detailed_health_check():
    """detailed health check with metrics and migration status"""
    try:
        from utils.monitoring import get_collector, get_migration_tracker
        
        collector = get_collector()
        migration_tracker = get_migration_tracker()
        
        # grab top 10 slowest operations
        all_stats = collector.get_all_stats()
        slowest = sorted(all_stats, key=lambda x: x.get('avg_duration', 0), reverse=True)[:10]
        
        # grab operations with most errors
        error_summary = get_error_summary()
        
        # grab migration progress
        migration_status = get_migration_status()
        total_features = len(migration_status)
        migrated_features = sum(1 for f in migration_status.values() if f['ready_to_remove_old'])
        
        return jsonify({
            'status': 'success',
            'health': 'healthy',
            'uptime_seconds': get_uptime().total_seconds(),
            'metrics': {
                'total_operations': len(all_stats),
                'total_calls': sum(s.get('calls', 0) for s in all_stats),
                'total_errors': sum(error_summary.values()),
                'slowest_operations': slowest,
            },
            'migration': {
                'total_features': total_features,
                'migrated_features': migrated_features,
                'migration_percentage': (migrated_features / total_features * 100) if total_features > 0 else 0,
            },
            'feature_flags': get_all_flags(),
        })
    except Exception:
        from api.helpers import _log_api_exception
        _log_api_exception("health/detailed")
        return jsonify({
            'status': 'error',
            'health': 'unhealthy',
            'message': 'Health check failed'
        }), 500



@api_bp.route('/admin/cache/stats')
@login_required
@admin_required
def get_cache_stats_api():
    """grab cache performance statistics"""
    from utils import get_cache_stats
    
    try:
        stats = get_cache_stats()
        return jsonify({
            'status': 'success',
            'cache_stats': stats
        })
    except Exception:
        from api.helpers import _log_api_exception
        _log_api_exception("cache/stats")
        return jsonify({
            'status': 'error',
            'message': 'Failed to retrieve cache stats'
        }), 500
