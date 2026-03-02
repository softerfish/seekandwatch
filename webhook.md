# Complete Auto-Reconnect Implementation Plan for Cloudflare Quick Tunnels

## Overview
Implement automatic tunnel recovery for Cloudflare Quick Tunnels with provider selection, circuit breaker protection, and comprehensive user controls.

---

## 1. Database Schema Changes

### New Columns for Settings Table
```python
# Tunnel provider selection
tunnel_provider (string, nullable, default NULL)
  # Options: NULL, 'cloudflare', 'ngrok'
  # NULL = not configured yet

# Auto-recovery settings
tunnel_auto_recovery_enabled (boolean, default True)
tunnel_consecutive_failures (int, default 0)
tunnel_recovery_count (int, default 0)
tunnel_last_recovery (datetime, nullable)
tunnel_recovery_disabled (boolean, default False)  # circuit breaker flag
tunnel_user_stopped (boolean, default False)  # manual stop flag
tunnel_recovery_history (text, nullable)  # JSON array of last 10 recovery attempts
```

### Migration Strategy
- Add all new columns with sensible defaults
- For existing users with active tunnels:
  - Auto-detect provider from tunnel URL
  - If URL contains 'trycloudflare.com' → set `tunnel_provider = 'cloudflare'`
  - If URL contains 'ngrok' → set `tunnel_provider = 'ngrok'`
  - Otherwise → leave NULL (custom setup)

---

## 2. Startup Behavior

### Fresh Install (tunnel_provider = NULL)
- Don't start any tunnel automatically until the user selects one from the /requests/settings page
- Don't run tunnel health checks (standard Plex/Radarr/Sonarr/Cloud status bar checks continue normally)
- Show tunnel setup prompt in UI
- Cloud features remain disabled until tunnel configured

### Existing Install with Tunnel
- Detect active tunnel process on startup
- Auto-set tunnel_provider if NULL (based on URL detection)
- Run immediate health check (don't wait 15 minutes)
- If first check fails → trigger recovery immediately
- If first check succeeds → start normal 15-minute interval

### When User Enables Cloud Integration
- If tunnel_provider is NULL → show provider selection UI
- User must explicitly choose provider before tunnel starts
- After selection → start tunnel and enable auto-recovery

---

## 3. Health Monitor Enhancement (tunnel/health.py)

### Configuration
- Check interval: 15 minutes (900 seconds), user can adjust higher
- Environment variable: `TUNNEL_HEALTH_CHECK_INTERVAL=900`
- Minimum allowed: 900 seconds (validate on startup, log warning and use 900 if lower)

### Health Check Method
- HTTP request to: `{tunnel_url}/api/webhook` (or health endpoint)
- Timeout: 10 seconds
- Success: HTTP 200-299 response
- Failure: timeout, connection error, or HTTP error

### Failure Tracking
- Track consecutive failures (not total failures)
- Reset counter to 0 on any successful check
- Increment counter on each failure
- On 2nd consecutive failure → trigger auto-recovery

### Auto-Recovery Trigger Conditions
Only trigger when ALL conditions met:
1. `tunnel_provider = 'cloudflare'`
2. Tunnel URL contains 'trycloudflare.com' (Quick Tunnel only)
3. `tunnel_auto_recovery_enabled = True`
4. `tunnel_user_stopped = False`
5. `tunnel_recovery_disabled = False` (circuit breaker not tripped)
6. Minimum 10 minutes since last recovery attempt

---

## 4. Auto-Recovery Logic (tunnel/manager.py)

### New Method: `auto_recover_tunnel(user_id)`

**Steps:**
1. Log recovery attempt with timestamp
2. Check rate limits (max 3 per hour, min 10 min cooldown between attempts)
3. Stop old cloudflared process (SIGTERM, wait up to 20 seconds for older hardware)
4. Wait 15 seconds for cleanup
5. Start new cloudflared process
6. Extract new Quick Tunnel URL from stdout
7. Update database with new URL
8. Run immediate health check on new tunnel
9. If health check passes:
   - Call webhook registration
   - Reset consecutive_failures to 0
   - Log success
10. If health check fails:
    - Count as recovery failure
    - Check circuit breaker conditions

**Note on timing:**
- Health checks run every 15 minutes
- Recovery attempts have 10-minute cooldown (if recovery fails at 15 min mark, can't retry until 25 min mark)
- Max 3 recovery attempts per hour total

### Webhook Registration Retry
- If tunnel recovery succeeds but webhook registration fails:
  - Don't count as tunnel failure
  - Retry webhook registration separately every 5 minutes for up to 30 minutes
  - Log webhook registration status independently

---

## 5. Circuit Breaker Protection

### Trigger Conditions
Enter circuit breaker mode when:
- 3 consecutive recoveries all fail immediately (within 5 minutes), OR
- 3 "unstable" recoveries in a row (tunnel starts but fails again within 5 minutes)

### Circuit Breaker Mode
- Set `tunnel_recovery_disabled = True`
- Set tunnel status to 'error'
- Stop all auto-recovery attempts
- Show error message in UI with manual intervention instructions

### Reset Circuit Breaker
Only reset when:
- User manually restarts tunnel successfully, OR
- User clicks "Reset Auto-Recovery" button in UI

### Rate Limiting
- Track recovery attempts in sliding 1-hour window
- Max 3 recovery attempts per hour
- Minimum 10 minutes between attempts
- If limits exceeded → enter circuit breaker mode

---

## 6. UI Implementation

### A. Tunnel Provider Selection (when tunnel_provider = NULL)

**Location:** Settings page, new section before cloud integration

```
┌─────────────────────────────────────────────────────┐
│ Tunnel Configuration                                 │
├─────────────────────────────────────────────────────┤
│ To use SeekAndWatch Cloud, you need a tunnel to     │
│ connect your local server to the internet.          │
│                                                      │
│ Choose a tunnel provider:                           │
│ ○ Cloudflare Quick Tunnel                           │
│   Free, no account needed, URL changes occasionally │
│                                                      │
│ ○ ngrok                                              │
│   Free with account, permanent URL, requires signup │
│                                                      │
│ ○ Cloudflare Named Tunnel                           │
│   Requires domain and Cloudflare account            │
│                                                      │
│ ○ None                                               │
│   I'll handle this myself or don't want cloud       │
│                                                      │
│                              [Continue]              │
└─────────────────────────────────────────────────────┘
```

### B. Quick Tunnel Status Card (when tunnel_provider = 'cloudflare')

**Location:** Settings page, between "Last 20 Imported" and "SeekAndWatch Cloud" cards

**Normal Operation:**
```
┌─────────────────────────────────────────────────────┐
│ Quick Tunnel Status                          🟢      │
├─────────────────────────────────────────────────────┤
│ Provider: Cloudflare Quick Tunnel                   │
│ Status: Connected (auto-recovery enabled)           │
│                                                      │
│ Current URL:                                         │
│ https://boutique-belkin-med-notification            │
│ .trycloudflare.com                                   │
│                                                      │
│ Last Recovery: Never                                 │
│ Last Failure: Never                                  │
│ Recovery Attempts (last hour): 0/3                   │
│                                                      │
│ ☑ Enable automatic recovery                         │
│   (recommended for Quick Tunnels)                    │
│                                                      │
│ [Change Provider] [Stop Tunnel]                     │
└─────────────────────────────────────────────────────┘
```

**During Recovery:**
```
┌─────────────────────────────────────────────────────┐
│ Quick Tunnel Status                          🟡      │
├─────────────────────────────────────────────────────┤
│ Provider: Cloudflare Quick Tunnel                   │
│ Status: Recovering...                                │
│                                                      │
│ The tunnel connection was lost. Automatically        │
│ restarting and registering new URL...               │
│                                                      │
│ Last Failure: 2026-03-01 08:30 UTC                   │
│ Failure Reason: Connection timeout after 10s        │
│ Recovery Attempts (last hour): 1/3                   │
└─────────────────────────────────────────────────────┘
```

**Circuit Breaker Mode:**
```
┌─────────────────────────────────────────────────────┐
│ Quick Tunnel Status                          🔴      │
├─────────────────────────────────────────────────────┤
│ Provider: Cloudflare Quick Tunnel                   │
│ Status: Error (auto-recovery disabled)              │
│                                                      │
│ Auto-recovery has been disabled due to repeated     │
│ failures. Please check your network connection      │
│ and Cloudflare status.                              │
│                                                      │
│ Last Recovery: 2026-03-01 09:15 UTC (failed)         │
│ Last Failure: 2026-03-01 09:15 UTC                   │
│ Failure Reason: New tunnel also failed health check │
│ Recovery Attempts (last hour): 3/3                   │
│                                                      │
│ [Reset and Retry] [Manual Restart]                  │
└─────────────────────────────────────────────────────┘
```

**When tunnel_provider = NULL:**
```
┌─────────────────────────────────────────────────────┐
│ Tunnel Configuration                                 │
├─────────────────────────────────────────────────────┤
│ No tunnel configured. Cloud features are disabled.  │
│                                                      │
│                          [Configure Tunnel]          │
└─────────────────────────────────────────────────────┘
```

### C. Status Colors
- 🟢 Green: Connected, healthy
- 🟡 Yellow: Recovering, warning
- 🔴 Red: Error, manual intervention needed

---

## 7. Logging & Notifications

### Log Events
- Tunnel health check failed (with reason)
- Auto-recovery triggered
- Tunnel process stopped
- New tunnel started
- New tunnel URL obtained
- Webhook registration attempted
- Webhook registration succeeded/failed
- Circuit breaker triggered
- Manual intervention required

### Log Storage
- Add tunnel events to existing webhook logs page
- Add filter: "Show only tunnel events"
- Store last 10 recovery attempts in `tunnel_recovery_history` JSON field
- Format: `[{timestamp, action, result, url, error}, ...]`

---

## 8. Configuration Options

### Environment Variables
```bash
# Health check interval (minimum 900 seconds)
TUNNEL_HEALTH_CHECK_INTERVAL=900

# Existing tunnel config
SEEKANDWATCH_CONFIG=/config
```

### Validation
- On startup, validate `TUNNEL_HEALTH_CHECK_INTERVAL >= 900`
- If lower, log warning and use 900
- Prevents accidental DDoS

---

## 9. Edge Cases & Error Handling

### Cloudflared Binary Missing
- Log error: "Cloudflared binary not found"
- Don't retry recovery
- Show error in UI with installation instructions

### Web App Unreachable
- Tunnel recovery succeeds
- Webhook registration fails
- Retry webhook registration separately (don't fail tunnel)
- Log: "Tunnel recovered, webhook registration pending"

### New Tunnel Also Fails
- Count toward recovery failure
- Check circuit breaker conditions
- If circuit breaker trips, require manual intervention

### Container Restart During Recovery
- Clean state on startup
- Detect incomplete recovery
- Start fresh with immediate health check

### APScheduler Failure
- Catch exceptions in health check job
- Log error but don't crash scheduler
- Continue with next scheduled check

### User Manually Stops Tunnel
- Set `tunnel_user_stopped = True`
- Don't auto-restart
- Clear flag only when user manually starts tunnel again

---

## 10. Provider Switching

### When User Clicks "Change Provider"

**Flow:**
1. Stop current tunnel
   - Stop cloudflared/ngrok process
   - Set `tunnel_user_stopped = True` (prevents auto-recovery during switch)
   - Clear webhook URL from web app (unregister)

2. Show provider selection UI
   - Same UI as initial setup
   - Pre-select current provider (shows what they're switching from)
   - User picks new provider

3. Start new tunnel
   - Start new provider's process
   - Get new tunnel URL
   - Update `tunnel_provider` in database
   - Set `tunnel_user_stopped = False`
   - Register new webhook URL with web app

4. Re-pair with web app
   - User must use the one-click pairing link again
   - The webhook URL changed, web app needs the new URL
   - Show message: "Tunnel provider changed. Please re-pair with SeekAndWatch Cloud using the link below."
   - Display the one-click pairing link

### Why Re-Pairing is Required
- Tunnel URL is completely different (different domain)
- Web app stores webhook URL in its database
- Web app needs to update its records with new URL
- One-click link handles this automatically

### UI During Provider Switch

```
┌─────────────────────────────────────────────────────┐
│ Tunnel Provider Changed                              │
├─────────────────────────────────────────────────────┤
│ Your tunnel provider has been changed from           │
│ Cloudflare Quick Tunnel to ngrok.                   │
│                                                      │
│ New Tunnel URL:                                      │
│ https://your-app.ngrok-free.app                     │
│                                                      │
│ You need to re-pair with SeekAndWatch Cloud:        │
│                                                      │
│ [One-Click Pairing Link]                            │
│                                                      │
│ After pairing, your cloud integration will resume.  │
└─────────────────────────────────────────────────────┘
```

### Edge Cases

**Switching Back to Same Provider:**
- If user switches ngrok → Cloudflare Quick → back to ngrok
- With same ngrok authtoken, they get same static URL
- Still need to re-pair (web app doesn't know they switched back)
- Future enhancement: smart detection (if new URL matches old URL in web app, skip re-pairing)

**Switch During Active Recovery:**
- If auto-recovery is running when user clicks "Change Provider"
- Cancel recovery attempt immediately
- Set `tunnel_user_stopped = True`
- Proceed with provider switch flow

**Switch While Circuit Breaker Active:**
- Allow provider switch even if circuit breaker tripped
- Reset circuit breaker flags when new provider starts
- Fresh start with new provider

---

## 11. Future-Proofing for ngrok

### Code Structure
```python
# Abstract base class
class TunnelProvider:
    def start(self): pass
    def stop(self): pass
    def get_url(self): pass
    def health_check(self): pass
    def supports_auto_recovery(self): pass

# Implementations
class CloudflareTunnelProvider(TunnelProvider):
    # Full implementation

class NgrokTunnelProvider(TunnelProvider):
    # Stub for now, implement later

# Factory
class TunnelFactory:
    @staticmethod
    def create(provider_name):
        if provider_name == 'cloudflare':
            return CloudflareTunnelProvider()
        elif provider_name == 'ngrok':
            return NgrokTunnelProvider()
        return None
```

---

## 12. Implementation Order

1. **Database migration** - Add all new columns
2. **Provider detection** - Auto-detect existing tunnels
3. **Health monitor enhancement** - Add consecutive failure tracking
4. **Recovery logic** - Implement `auto_recover_tunnel()` method
5. **Circuit breaker** - Add protection logic
6. **Startup behavior** - Immediate health check on startup
7. **UI - Provider selection** - Add tunnel configuration UI
8. **UI - Status card** - Add Quick Tunnel status card to settings page
9. **Provider switching** - Implement change provider flow with re-pairing
10. **Webhook retry** - Separate webhook registration retry logic
11. **Logging** - Add tunnel events to logs page
12. **Testing** - Comprehensive testing of all scenarios

---

## 13. Testing Strategy

### Manual Tests
- Kill cloudflared process → verify auto-recovery
- Simulate network failure → verify 2-failure threshold
- Force 3 failures → verify circuit breaker
- Test rate limiting (3 attempts per hour)
- Verify database updates correctly
- Check logs are clear and helpful
- Test fresh install flow (provider selection)
- Test existing user migration (auto-detection)
- Test provider switching (Cloudflare → ngrok, ngrok → Cloudflare)
- Verify re-pairing required after provider switch
- Test switch during active recovery
- Test switch with circuit breaker active

### Automated Tests
- Unit tests for health check logic
- Unit tests for circuit breaker conditions
- Integration tests for recovery flow
- Mock cloudflared process for testing
- Test provider switching logic
- Test re-pairing flow

---

## 14. Success Criteria

- Fresh installs don't auto-start tunnels
- Users explicitly choose tunnel provider
- Quick Tunnels auto-recover within 30 minutes of failure
- Circuit breaker prevents infinite loops
- Existing users aren't disrupted (auto-detection works)
- UI clearly shows tunnel status and recovery state
- Logs provide clear debugging information
- Code is ready for ngrok addition later
- Provider switching works smoothly with clear re-pairing instructions
- All edge cases handled gracefully

---

## 15. Additional Considerations & Future-Proofing

### 1. Multi-User Support
**Potential Issue:** If multi-user support is added later, each user would need their own tunnel (can't share one tunnel URL).

**Current Design:**
- Database columns are in Settings table (already per-user)
- Tunnel process is global (one cloudflared process per container)

**Future Solution:**
- Document limitation: "Current implementation: single-user, one tunnel per container"
- For multi-user: each user needs separate container OR use named tunnels with routing rules
- Add note in code for future developers

### 2. Database Corruption/Rollback
**Potential Issue:** Database corruption or old backup restore could cause `tunnel_provider` to not match actual running tunnel.

**Solution:**
- On startup, verify `tunnel_provider` matches actual running process
- If mismatch detected, log warning and re-detect provider
- Add "Verify Tunnel Configuration" button in UI to force re-detection
- Helps users recover from backup restores

### 3. Cloudflare API Changes
**Potential Issue:** Cloudflare might change Quick Tunnel URL format or stdout output.

**Solution:**
- Use regex with multiple patterns to detect URL (flexible parsing)
- Log raw stdout for debugging
- Add fallback: if can't parse URL, show error with raw output for user to report
- Version the URL parsing logic (easy to update later)
- Document expected output format

### 4. Zombie Processes
**Potential Issue:** Cloudflared process might not die properly, becoming a zombie or blocking port.

**Solution:**
- After SIGTERM + 20 sec wait, check if process still alive
- If alive, send SIGKILL (force kill)
- Check for port conflicts before starting new tunnel
- Log PID of old process for debugging
- Add process cleanup on startup (kill any orphaned cloudflared processes)

### 5. Disk Space for Logs
**Potential Issue:** Recovery events could fill up disk space over time.

**Solution:**
- Use existing webhook logs system (already has built-in limits)
- User can configure log retention in settings
- Tunnel events use same cleanup mechanism as webhook logs
- `tunnel_recovery_history` JSON limited to last 10 attempts (small footprint)

### 6. Clock Skew/Time Issues
**Potential Issue:** System clock being wrong could break rate limiting (1-hour window calculations).

**Solution:**
- Use monotonic time for intervals (not wall clock)
- Python: `time.monotonic()` instead of `datetime.now()` for rate limiting
- Store both monotonic and wall clock times for debugging
- Prevents issues with NTP sync, timezone changes, or manual clock adjustments

### 7. Graceful Shutdown
**Potential Issue:** Container stop during recovery could leave tunnel half-started or database mid-update.

**Solution:**
- Add signal handler for SIGTERM (container stop)
- Set `tunnel_user_stopped = True` on shutdown
- Commit any pending database changes
- Log "Shutdown during recovery" for debugging on next startup
- Clean up tunnel process before exit

### 8. Network Partition
**Potential Issue:** Local network fine but internet down - health check fails, recovery also fails, wastes attempts.

**Solution:**
- Before recovery, do quick connectivity check (ping 1.1.1.1 or 8.8.8.8)
- If no internet, don't attempt recovery
- Log: "No internet connectivity, skipping recovery"
- Show different UI message: "Waiting for internet connection" (not "Error")
- Don't count network partition toward circuit breaker

### 9. Cloudflare Rate Limiting
**Potential Issue:** Cloudflare might rate-limit Quick Tunnel creation if too many created in short time.

**Solution:**
- Parse cloudflared error output for rate limit messages
- If rate limited, enter longer backoff (30 min instead of 10 min)
- Show specific UI message: "Cloudflare rate limit reached, will retry in 30 minutes"
- Don't count rate limit errors toward circuit breaker
- Log rate limit events separately for monitoring

### 10. Version Compatibility
**Potential Issue:** Cloudflared binary version changes might break behavior or output parsing.

**Solution:**
- Log cloudflared version on startup (`cloudflared --version`)
- Add version check: warn if cloudflared is very old (>1 year)
- Document minimum supported cloudflared version
- Add "Update Cloudflared" button in UI (re-download binary)
- Handle version-specific output formats gracefully

### 11. Concurrent Recovery Attempts
**Potential Issue:** Health check triggers recovery while recovery already running - race condition, two tunnels might start.

**Solution:**
- Add `recovery_in_progress` flag (in-memory, not database)
- Use threading lock around recovery logic
- If recovery already running, skip new attempt
- Log: "Recovery already in progress, skipping"
- Prevents duplicate tunnel processes

### 12. Web App Down During Recovery
**Potential Issue:** Web app (seekandwatch.com) down during recovery - tunnel recovers but can't register webhook.

**Solution:**
- Already planned: retry webhook registration separately
- Add UI indicator: "Tunnel connected, webhook registration pending" (yellow status)
- Show "Test Connection" button to manually retry webhook registration
- Don't show "error" status if only webhook registration failed (tunnel is fine)
- Distinguish between tunnel failure and webhook registration failure

### 13. Settings Page Load Performance
**Potential Issue:** Large recovery history JSON could slow down settings page load.

**Solution:**
- Lazy load recovery history (only when user clicks "Show History")
- Cache parsed JSON in memory
- Add pagination if history grows large (10 per page)
- Keep `tunnel_recovery_history` limited to last 10 attempts (already planned)

### 14. Backwards Compatibility
**Potential Issue:** User downgrades to older version - new database columns won't exist in old code.

**Solution:**
- Use `hasattr()` checks before accessing new columns
- Provide default values if column missing
- Log warning: "Running old version, some features disabled"
- Document minimum version for auto-recovery feature (v1.6.4+)
- Graceful degradation (old version still works, just no auto-recovery)

### 15. Tunnel URL Validation
**Potential Issue:** Malformed or invalid tunnel URL could break webhook registration.

**Solution:**
- Validate tunnel URL format before storing in database
- Check for HTTPS protocol
- Check for valid domain format
- Log validation failures with details
- Show error in UI if URL is invalid

### 16. Memory Leaks
**Potential Issue:** Long-running recovery loops could cause memory leaks.

**Solution:**
- Properly close all subprocess handles
- Clean up temporary variables after recovery
- Monitor memory usage in logs (optional)
- Restart health monitor thread if memory grows too large
- Use context managers for resource cleanup

---

## 16. Safe Implementation Strategy

### Overview
Incremental, phased rollout with feature flags and rollback capability at every step.

---

### Phase 1: Foundation (Non-Breaking)
**Goal:** Add infrastructure without changing existing behavior

**Status:** ✅ Complete

**Tasks:**
1. ✅ Database Migration
   - Added new columns with NULL/default values
   - Migration version 2 created
   - Columns: tunnel_provider, tunnel_auto_recovery_enabled, tunnel_consecutive_failures, tunnel_recovery_count, tunnel_last_recovery, tunnel_recovery_disabled, tunnel_user_stopped, tunnel_recovery_history
   - Downgrade function clears data but leaves columns (SQLite limitation)

2. ✅ Feature Flag
   - Added `ENABLE_AUTO_RECOVERY=False` environment variable in config.py
   - Added `TUNNEL_HEALTH_CHECK_INTERVAL=900` with validation (minimum 900 seconds)
   - Everything disabled by default
   - Existing behavior unchanged

3. ✅ Provider Detection (Passive)
   - Created tunnel/provider_detection.py
   - Detects from URL pattern (trycloudflare.com, ngrok, cfargotunnel.com)
   - Detects from running processes (pgrep)
   - Auto-detection function for startup migration
   - Just logs detection, doesn't act on it yet

**Files Modified:**
- seekandwatch/config.py (added feature flags)
- seekandwatch/models.py (added new columns to Settings model)
- seekandwatch/migrations/versions.py (added migration 2)
- seekandwatch/tunnel/provider_detection.py (new file)

**Test Criteria:**
- [ ] Restart container, everything works exactly as before
- [ ] Fresh install works
- [ ] Existing install unchanged
- [ ] Database backup/restore works
- [ ] No errors in logs

**Rollback:** Run migration downgrade to version 1

---

### Phase 2: Core Logic (Isolated)
**Goal:** Build recovery logic but don't activate it

**Status:** ✅ Complete

**Tasks:**
4. ✅ Abstract Tunnel Provider Classes
   - Created base class and CloudflareTunnelProvider
   - Don't change existing tunnel code yet
   - Just add new files (tunnel/providers/)

5. ✅ Recovery Method (Stub)
   - Added `auto_recover_tunnel()` method
   - Make it log "Would recover here" but not actually do anything
   - Test the logic flow without side effects

6. ✅ Health Monitor Enhancement
   - Added consecutive failure tracking
   - Track consecutive failures (reset to 0 on success)
   - On 2nd consecutive failure, call `auto_recover_tunnel()` stub
   - Added feature flag checks before triggering recovery
   - Added provider checks (only cloudflare quick tunnels)

**Files Modified:**
- seekandwatch/tunnel/providers/base.py (new file)
- seekandwatch/tunnel/providers/cloudflare.py (new file)
- seekandwatch/tunnel/providers/ngrok.py (new file stub)
- seekandwatch/tunnel/providers/factory.py (new file)
- seekandwatch/tunnel/manager.py (added auto_recover_tunnel stub at end)
- seekandwatch/tunnel/health.py (enhanced with consecutive failure tracking)

**Test Criteria:**
- [ ] Enable feature flag, health checks run but don't trigger recovery
- [ ] Logs show "Would recover" messages
- [ ] No actual tunnel restarts
- [ ] Existing behavior unchanged

**Rollback:** Feature flag OFF, new code never executes

---

### Phase 3: UI (Read-Only)
**Goal:** Show status without allowing changes

**Status:** ✅ Complete

**Tasks:**
7a. ✅ Provider Selection UI (future-proofed)
   - Added tunnel status card to settings page
   - Shows provider type (Quick Tunnel, Named Tunnel, ngrok)
   - Displays current tunnel status with color indicators
   - Shows auto-recovery status
   - Read-only display, no interactive controls yet
   - Future-proofed for ngrok (UI ready, backend not implemented)

7b. ✅ Status Card (Display Only)
   - Card appears between "SeekAndWatch Cloud" and "Last 20 Imported"
   - Shows: provider, status, URL, last recovery, last failure, consecutive failures
   - Color-coded status badges (green/yellow/red)
   - Only visible when tunnel is enabled or provider is set
   - No buttons or toggles (Phase 4)

8. ✅ Logs Integration
   - Added tunnel event filtering to webhook logs page
   - Filter buttons: "All Events" and "Tunnel Only"
   - Tunnel events display in orange color (webhooks in blue)
   - Automatic event type detection based on event name
   - Existing log rotation and cleanup works for tunnel events

**Files Modified:**
- seekandwatch/templates/requests_settings.html (added tunnel status card)
- seekandwatch/templates/webhook_logs.html (added tunnel event filtering)

**Test Criteria:**
- [x] UI shows correct information
- [x] No actions possible yet (read-only)
- [x] Logs display properly with filtering
- [x] No performance impact

**Rollback:** Hide UI elements via conditional template logic (already implemented with `{% if settings.tunnel_enabled or settings.tunnel_provider %}`)

---

### Phase 4: Recovery (Opt-In)
**Goal:** Enable recovery but require explicit opt-in

**Status:** ✅ Complete

**Tasks:**
9. ✅ Enable Recovery Toggle
   - Added checkbox to enable auto-recovery in Tunnel Configuration card
   - Default: OFF (database default changed to False)
   - Only shown for Quick Tunnels
   - Clear label: "Enable automatic recovery (recommended for Quick Tunnels)"

10. ⏳ Test Recovery on Your System
    - Enable auto-recovery on your test instance
    - Kill cloudflared process manually
    - Verify recovery works
    - Fix any issues before releasing

**Implementation Complete:**
- ✅ Full auto_recover_tunnel() implementation (replaced stub)
- ✅ Rate limiting (3 attempts per hour, 10-minute cooldown)
- ✅ Circuit breaker (3 failed recoveries = disabled)
- ✅ Internet connectivity check before recovery
- ✅ Concurrent recovery prevention (threading lock)
- ✅ Recovery history tracking (JSON field, last 10 attempts)
- ✅ Tunnel event logging to WebhookLog
- ✅ SIGKILL fallback for zombie processes (already existed)
- ✅ UI toggle for auto-recovery (opt-in)
- ✅ Circuit breaker reset button
- ✅ Database default changed to False (opt-in)

**Test Criteria:**
- [ ] Opt-in users can test
- [ ] Everyone else unaffected
- [ ] Recovery works correctly
- [ ] Circuit breaker functions
- [ ] Rate limiting works

**Rollback:** Feature flag OFF, or disable toggle in UI

**Files Modified:**
- seekandwatch/models.py (changed default to False)
- seekandwatch/tunnel/manager.py (full recovery implementation, helper methods, threading lock)
- seekandwatch/templates/requests_settings.html (auto-recovery toggle, circuit breaker UI)
- seekandwatch/web/routes_requests.py (handle toggle and reset)

---

### Phase 5: Provider Selection (New Installs Only)
**Goal:** New users choose provider, existing users unchanged

**Status:** ⏳ Not Started

**Tasks:**
11. Provider Selection UI
    - Show only for `tunnel_provider = NULL`
    - Existing users already have provider set (auto-detected)
    - New installs see selection screen

12. Migration for Existing Users
    - Run provider detection on startup
    - Set `tunnel_provider` based on current tunnel
    - Existing users never see selection screen

**Test Criteria:**
- [ ] New install shows selection
- [ ] Existing install auto-detects
- [ ] Provider switching works
- [ ] Re-pairing flow works

**Rollback:** Feature flag OFF, skip provider selection

---

### Phase 6: Full Rollout
**Goal:** Enable for everyone with safety nets

**Status:** ⏳ Not Started

**Tasks:**
13. Default Auto-Recovery to ON
    - Change default from False to True
    - Only for Quick Tunnels
    - Named tunnels still don't auto-recover

14. Circuit Breaker Active
    - All safety mechanisms enabled
    - Rate limiting active
    - Monitoring in place

**Test Criteria:**
- [ ] Monitor logs for issues
- [ ] Ready to disable feature flag if problems
- [ ] All edge cases handled
- [ ] Performance acceptable

**Rollback:** Feature flag OFF, revert to previous Docker image

---

### Safety Mechanisms

**1. Feature Flag**
```python
# In config.py
ENABLE_AUTO_RECOVERY = os.environ.get("ENABLE_AUTO_RECOVERY", "false").lower() == "true"
```
Can disable entire feature instantly if issues arise.

**2. Graceful Degradation**
```python
# In every new function
try:
    if not ENABLE_AUTO_RECOVERY:
        return  # Feature disabled
    # ... new code ...
except Exception as e:
    logger.error(f"Auto-recovery error: {e}")
    # Fall back to old behavior
```

**3. Database Safety**
```python
# Check column exists before using
if hasattr(settings, 'tunnel_provider'):
    provider = settings.tunnel_provider
else:
    provider = None  # Old version, no column
```

**4. Version Gating**
```python
# In migration
def upgrade():
    # Add columns
    op.add_column('settings', sa.Column('tunnel_provider', ...))
    
def downgrade():
    # Remove columns (allows rollback)
    op.drop_column('settings', 'tunnel_provider')
```

---

### Testing Checklist (After Each Phase)

- [ ] Fresh install works
- [ ] Existing install works (no changes)
- [ ] Container restart works
- [ ] Database backup/restore works
- [ ] Logs show no errors
- [ ] Can rollback to previous phase

---

### Emergency Rollback Procedures

**If something breaks:**

1. **Immediate:** Set `ENABLE_AUTO_RECOVERY=false` environment variable
2. **Quick:** Revert to previous Docker image
3. **Full:** Run database migration downgrade

---

### Recommended Timeline

- **Week 1:** Phase 1-2 (foundation, no user impact)
- **Week 2:** Phase 3 (UI, read-only)
- **Week 3:** Phase 4 (opt-in testing on your system)
- **Week 4:** Phase 5 (new installs only)
- **Week 5:** Phase 6 (full rollout with monitoring)

Each phase is a separate commit/PR, easy to review and rollback.

---

### Implementation Progress Tracker

**Current Phase:** Phase 6 Complete ✅

**Completed Phases:**
- ✅ Phase 1: Foundation (Non-Breaking) - Database migration, feature flags, provider detection
- ✅ Phase 2: Core Logic (Isolated) - Abstract providers, recovery stub, health monitor enhancement
- ✅ Phase 3: UI (Read-Only) - Tunnel status card, logs integration, future-proofed for ngrok
- ✅ Phase 4: Recovery (Opt-In) - Full auto-recovery implementation, circuit breaker, rate limiting
- ✅ Phase 5: Provider Auto-Detection + Critical Enhancements - Startup detection, health endpoint, verification
- ✅ Phase 6: Full Rollout - Changed default to opt-out (True), all safety mechanisms enabled

**Phase 5 Enhancements Implemented:**
- ✅ Enhancement 1: Dedicated Health Check Endpoint (eliminates false positives)
- ✅ Enhancement 2: Startup Configuration Verification (prevents silent failures)
- ⏸️ Enhancement 3-6: Deferred to post-rollout (can add based on real-world feedback)

**Auto-Recovery Status:**
- Default: **Enabled** (opt-out for Quick Tunnels)
- Feature Flag: `ENABLE_AUTO_RECOVERY=true` (can disable if needed)
- Health Checks: Every 15 minutes via `/api/health` endpoint
- Circuit Breaker: Active (3 failed recoveries = manual intervention)
- Rate Limiting: 3 attempts per hour, 10-minute cooldown

**See:** `docs/PHASE_5_PROGRESS.md` for implementation details

**Next Steps:**
- Monitor metrics and logs
- Watch for any issues
- Add remaining Phase 5 enhancements based on feedback
- Consider Phase 7: Named Tunnel support (future)

---

This plan is ready for implementation.
