"""
User-friendly error messages for tunnel operations.

Maps technical errors to actionable messages with troubleshooting guidance.
"""


ERROR_MESSAGES = {
    'binary_download_failed': {
        'message': 'Failed to download cloudflared binary',
        'guidance': 'Check your internet connection and try again. If the problem persists, you may need to manually download cloudflared.'
    },
    'authentication_failed': {
        'message': 'Could not authenticate with Cloudflare',
        'guidance': 'Make sure you complete the browser authentication flow. Try resetting your tunnel configuration and starting over.'
    },
    'authentication_timeout': {
        'message': 'Authentication timed out',
        'guidance': 'The authentication window expired. Please try again and complete the login within 5 minutes.'
    },
    'tunnel_creation_failed': {
        'message': 'Failed to create tunnel',
        'guidance': 'This could be a temporary Cloudflare issue. Wait a few minutes and try again.'
    },
    'process_start_failed': {
        'message': 'Could not start tunnel process',
        'guidance': 'Check that cloudflared binary has execute permissions. Try resetting the tunnel configuration.'
    },
    'process_crashed': {
        'message': 'Tunnel process stopped unexpectedly',
        'guidance': 'Check the tunnel logs for details. The health monitor will attempt to restart automatically.'
    },
    'webhook_registration_failed': {
        'message': 'Could not register webhook with cloud app',
        'guidance': 'Verify your cloud API key and base URL are correct. The system will retry automatically.'
    },
    'webhook_test_failed': {
        'message': 'Webhook connection test failed',
        'guidance': 'Make sure your tunnel is running and the cloud app is accessible. Check firewall settings.'
    },
    'config_not_found': {
        'message': 'Tunnel configuration not found',
        'guidance': 'Your tunnel may not be set up yet. Try enabling the tunnel first.'
    },
    'settings_not_found': {
        'message': 'User settings not found',
        'guidance': 'This is an unexpected error. Try logging out and back in.'
    },
    'max_restarts_exceeded': {
        'message': 'Tunnel failed too many times',
        'guidance': 'The automatic restart limit was reached. Check the logs and try resetting the tunnel configuration.'
    },
    'invalid_credentials': {
        'message': 'Tunnel credentials are invalid',
        'guidance': 'Your Cloudflare credentials may have expired. Try resetting the tunnel configuration to re-authenticate.'
    },
    'network_error': {
        'message': 'Network connection error',
        'guidance': 'Check your internet connection and firewall settings. Make sure you can reach Cloudflare services.'
    },
    'permission_denied': {
        'message': 'Permission denied',
        'guidance': 'The app may not have permission to write config files. Check file permissions in the config directory.'
    }
}


def get_user_friendly_error(error_key, technical_details=None):
    """
    Get user-friendly error message with guidance.
    
    Args:
        error_key: Key from ERROR_MESSAGES dict
        technical_details: Optional technical error details (not shown to user)
        
    Returns:
        Dict with message and guidance
    """
    error_info = ERROR_MESSAGES.get(error_key, {
        'message': 'An unexpected error occurred',
        'guidance': 'Try again in a few minutes. If the problem continues, check the logs or reset the tunnel configuration.'
    })
    
    result = {
        'message': error_info['message'],
        'guidance': error_info['guidance']
    }
    
    # technical details are logged but not shown to user
    if technical_details:
        result['_technical'] = technical_details
    
    return result


def format_error_response(error_key, technical_details=None, http_status=500):
    """
    Format error for API response.
    
    Args:
        error_key: Key from ERROR_MESSAGES dict
        technical_details: Optional technical error details
        http_status: HTTP status code
        
    Returns:
        Tuple of (response_dict, status_code)
    """
    error_info = get_user_friendly_error(error_key, technical_details)
    
    return {
        'success': False,
        'error': error_info['message'],
        'guidance': error_info['guidance']
    }, http_status
