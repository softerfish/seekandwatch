# SeekAndWatch Cloud - Friends Guide

This guide is for **friends and family** who have been invited to use SeekAndWatch Cloud by a server owner. You don't need to install anything; just use your browser.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Browsing & Searching](#browsing--searching)
3. [Requesting Movies & TV Shows](#requesting-movies--tv-shows)
4. [Checking Your Requests](#checking-your-requests)
5. [Settings](#settings)
6. [FAQ](#faq)

---

## Getting Started

### 1. Get an Invite Link

The server owner will send you a unique invite link. It looks something like:

```
https://seekandwatch.com/invite.php?code=abc123
```

### 2. Create Your Account

1. Click the invite link.
2. Enter your email and create a password.
3. Add your first name (so the owner knows who's requesting).
4. Submit.

### 3. Log In

After registering, log in at [seekandwatch.com](https://seekandwatch.com) with your email and password.

### Alternative: Sign in with Plex

If the server owner uses Plex and you have a Plex account:
1. Click **Sign in with Plex**.
2. Authorize the connection.
3. You're logged in!

---

## Browsing & Searching

### Dashboard

After logging in, you'll see the Dashboard with:
- **Search bar** - Find movies and TV shows.
- **Trending** - Popular titles (and other browse carousels).
- **Your requests** - First carousel: your pending requests and recently filled ones. Each shows status (Pending or Filled). Filled items stay in this carousel for 7 days after they're marked ready, then drop off. If you have no requests yet, you'll see a friendly message like "No requests yet. Request something from the browse view."
- **Your pending summary** - When you have pending requests, a line above the carousels says "You have X pending request(s). View status" with a link to My History.
- **Recently added** - Titles the owner recently marked available (new in library).
- **News** - Announcements from the server owner (e.g. maintenance notices).
- **Empty states** - When there are no search results, no genre selected, or nothing in a carousel, you'll see short, friendly copy and a clear next step (e.g. "No results. Try different keywords or browse trending below.").

### How to Search

1. Type a title in the search bar (e.g. "The Batman" or "Breaking Bad").
2. Press Enter or click Search.
3. Results show posters, titles, and release years.
4. Click a title for more details.

### What You See

| Badge | Meaning |
|-------|---------|
| **Available** | Already on the server. You can watch it now! |
| **Requested** | You (or someone else) already requested this. |
| **Request** | Click to request this title. |

---

## Requesting Movies & TV Shows

### How to Request

1. Search for or browse to a title.
2. (Optional) Add a **request note** (e.g. "season 2 only" or "prefer 4K"). The server owner sees this when approving. Notes are cleared when the request is filled or denied.
3. Click the **Request** button.
4. You'll see a confirmation: "Requested!"

### What Happens Next

1. Your request is added to the server owner's queue.
2. The owner's local app picks it up and sends it to their download service (Radarr/Sonarr).
3. Once it's downloaded and added to Plex, the status changes to **Available**.

### Request Limits

Some server owners may set limits (e.g. 5 requests per week). If you hit a limit, you'll see a message.

---

## Checking Your Requests

### My Requests / My History

Go to **My History** (or click "View status" in the pending summary on the Dashboard) to see:

| Status | Meaning |
|--------|---------|
| **Pending** | Waiting for the owner to process. |
| **Approved** | The owner approved it; it's being downloaded. |
| **Available** / **Completed** / **Filled** | Ready to watch on Plex! |
| **Denied** | The owner declined the request. |

The **Your requests** carousel on the Dashboard shows the same items: pending plus filled (filled items disappear from the carousel 7 days after they're marked ready).

### Notifications

If you've enabled email notifications, you'll get emails when:
- Your request is filled (ready to watch).
- The owner posts an announcement.
- **Weekly digest** (default on): one email per week with a short summary (e.g. how many requests were filled for you, how many new titles were added to the library). Turn it off in Settings -> Notifications if you prefer not to get it.

---

## Settings

**Location:** Click your name or the Settings link in the menu.

### Account Info

| Setting | Description |
|---------|-------------|
| **First Name** | How the owner sees you in their requests. |
| **Email** | Used for login and notifications. |
| **Change Password** | Set a new password (minimum 8 characters). |

### Plex Account

- **Link with Plex** - Sign in faster using your Plex account.
- **Unlink Plex** - Remove the Plex connection.

### Notification Preferences

| Notification | Default | Description |
|--------------|---------|-------------|
| Email me when my request is filled | ON | Get notified when a request is ready. |
| **Weekly digest email** | ON | One email per week with a summary (e.g. requests filled for you, new in library). Turn off if you prefer not to get it. |
| Email me when I log in from a new device | ON | Security alert. |
| Password changed | ON | Confirmation email. |
| Email changed | ON | Confirmation email. |
| Passkey added/removed | ON | Security alerts. |
| Reminder if I haven't made a request | OFF | Nudge to use the service. |

### Passkeys (Optional)

If supported, you can add a **passkey** for passwordless login:
1. Go to Settings -> Passkeys.
2. Click **Add Passkey**.
3. Follow your browser's prompts (fingerprint, Face ID, or security key).

---

## FAQ

### Can I see what's already on the server?

Yes! If the server owner has synced their library, you'll see **Available** badges on titles they already have.

### What is the weekly digest?

One email per week with a short summary: e.g. how many requests were filled for you and how many new titles were added to the library. Default is on. Turn it off in Settings -> Notifications if you don't want it.

### How do I turn off the weekly digest?

Settings -> Notifications -> uncheck "Weekly digest email" -> Save.

### When do filled items disappear from "Your requests" on the dashboard?

Filled items stay in the "Your requests" carousel for 7 days after they're marked ready, then they drop off. Until then they show as "Approved (Filled)" or similar. You can always see full history in My History.

### What are request notes?

When you request a title you can add an optional note (e.g. "season 2 only" or "prefer 4K"). The server owner sees it when approving. Notes are cleared when the request is filled or denied.

### Why does it say "Already requested"?

That title is already in the queue (pending, approved, or previously denied). Wait for it to be processed, or ask the owner if there's an issue.

### How long until my request is ready?

It depends on:
- How often the owner checks requests.
- Download speed and availability.
- Typically a few hours to a day.

### Can I cancel a request?

Usually not from your side. Ask the server owner if you need to cancel.

### I can't log in

- Make sure you're using the correct email.
- Try **Forgot Password** to reset.
- If you used Plex login, try **Sign in with Plex**.

### I didn't get an invite link

Ask the server owner to create a new invite link for you. Each link is usually one-time use.

### Is my data safe?

- Your email and name are stored on SeekAndWatch Cloud.
- Your password is hashed (not stored in plain text).
- The cloud does not have access to the server owner's Plex or media files.

---

## Need Help?

Contact the server owner who invited you; they manage the server and can answer questions about their specific setup.

For general issues with SeekAndWatch Cloud, visit [r/SeekAndWatch](https://www.reddit.com/r/SeekAndWatch/).