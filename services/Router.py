"""
router - centralized url mapping for seekandwatch.
provides a single source of truth for all local and cloud endpoints.
"""

class Router:
    # --- local app endpoints (inbound) ---
    LOCAL_WEBHOOK_PATH = "/api/webhook"
    
    @staticmethod
    def get_local_webhook_url(base_url):
        """construct the full local webhook url"""
        return f"{base_url.rstrip('/')}{Router.LOCAL_WEBHOOK_PATH}"

    # --- cloud app endpoints (outbound) ---
    CLOUD_POLL = "/api/poll.php"
    CLOUD_SYNC = "/api/sync.php"
    CLOUD_ACKNOWLEDGE = "/api/acknowledge.php"
    CLOUD_MARK_SYNCED = "/api/mark_synced.php"
    CLOUD_SAVE_WEBHOOK = "/api/save_webhook.php"
    CLOUD_TEST_WEBHOOK = "/api/test_webhook.php"
    CLOUD_REGISTER_WEBHOOK = "/api/save_webhook.php" # consolidated with save_webhook
    CLOUD_PAIR_PAGE = "/pair.php"
    CLOUD_PAIR_HANDOFF_CREATE = "/api/pair_handoff_create.php"

    @staticmethod
    def get_cloud_url(cloud_base, endpoint_path):
        """construct a full url for a cloud endpoint"""
        return f"{cloud_base.rstrip('/')}{endpoint_path}"
