"""
monitor.py

Polls the target X/Twitter account, filters for "late change" style tweets,
and posts new matches to a Discord channel via webhook with an @everyone
(or role) ping.

Designed to run either:
  - as a one-shot script on a schedule (e.g. GitHub Actions cron), or
  - as a long-running loop (e.g. on a VPS with systemd).

See README.md for setup instructions.
"""

import os
import sys
import json
import time
import requests

from fetch_tweets import get_recent_tweets, Tweet

# ---------------------------------------------------------------------------
# Configuration (all overridable via environment variables)
# ---------------------------------------------------------------------------

def env(name: str, default: str) -> str:
    """
    Like os.environ.get, but also falls back to the default when the
    variable is set but empty - which is what GitHub Actions does for
    unset repo Variables referenced in a workflow's `env:` block.
    """
    value = os.environ.get(name)
    return value if value else default


TWITTER_USERNAME = env("TWITTER_USERNAME", "aflwomens")
DISCORD_WEBHOOK_URL = env("DISCORD_WEBHOOK_URL", "")

# Comma-separated list of keywords; a tweet matches if it contains ANY of
# these (case-insensitive). Adjust to taste, e.g. "late change,team change".
KEYWORDS = [
    k.strip().lower()
    for k in env("KEYWORDS", "late change").split(",")
    if k.strip()
]

# What to ping. Options:
#   "everyone"        -> @everyone
#   "role:ROLE_ID"     -> ping a specific role by ID, e.g. role:123456789012345678
#   "none"             -> no ping, just post the message
PING_TARGET = env("PING_TARGET", "everyone")

# Comma-separated list of phrases; if a matched tweet contains ANY of these
# (case-insensitive), it still gets posted to Discord but WITHOUT a ping -
# e.g. "No late changes" announcements are worth seeing but don't need to
# wake anyone up.
NO_PING_KEYWORDS = [
    k.strip().lower()
    for k in env("NO_PING_KEYWORDS", "no late changes").split(",")
    if k.strip()
]

# How many of the most recent tweets to look at each poll (only needs to be
# large enough to cover the gap between polls).
CHECK_COUNT = int(env("CHECK_COUNT", "20"))

# Only used when running as a persistent loop (RUN_MODE=loop).
POLL_INTERVAL_SECONDS = int(env("POLL_INTERVAL_SECONDS", "120"))
RUN_MODE = env("RUN_MODE", "once")  # "once" or "loop"

STATE_FILE = env("STATE_FILE", "state.json")


# ---------------------------------------------------------------------------
# State (tracks the newest tweet ID we've already handled, so we never
# double-ping and never miss one between polls)
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_seen_id": None}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def is_late_change(tweet: Tweet) -> bool:
    if tweet.is_retweet:
        return False
    text_lower = tweet.text.lower()
    return any(keyword in text_lower for keyword in KEYWORDS)


def should_skip_ping(tweet: Tweet) -> bool:
    text_lower = tweet.text.lower()
    return any(phrase in text_lower for phrase in NO_PING_KEYWORDS)


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------

def build_ping_content() -> tuple[str, dict]:
    """Returns (mention_text, allowed_mentions_payload)."""
    if PING_TARGET == "everyone":
        return "@everyone", {"parse": ["everyone"]}
    if PING_TARGET.startswith("role:"):
        role_id = PING_TARGET.split(":", 1)[1]
        return f"<@&{role_id}>", {"parse": [], "roles": [role_id]}
    return "", {"parse": []}


def post_to_discord(tweet: Tweet, ping: bool = True) -> bool:
    if not DISCORD_WEBHOOK_URL:
        print("[monitor] DISCORD_WEBHOOK_URL not set - skipping post, printing instead:")
        print(tweet.text, tweet.url)
        return False

    if ping:
        mention, allowed_mentions = build_ping_content()
        label = "\U0001F6A8 **Late Change**"
    else:
        mention, allowed_mentions = "", {"parse": []}
        label = "**Late Change Update**"

    content = f"{mention} {label} from @{TWITTER_USERNAME}\n{tweet.text}\n{tweet.url}".strip()

    payload = {
        "content": content,
        "allowed_mentions": allowed_mentions,
    }

    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
        resp.raise_for_status()
        print(f"[monitor] Posted tweet {tweet.id} to Discord.")
        return True
    except Exception as e:
        print(f"[monitor] Failed to post to Discord: {e}")
        return False


# ---------------------------------------------------------------------------
# Core poll cycle
# ---------------------------------------------------------------------------

def run_once() -> None:
    state = load_state()
    last_seen_id = state.get("last_seen_id")

    tweets = get_recent_tweets(TWITTER_USERNAME, limit=CHECK_COUNT)
    if tweets is None:
        print("[monitor] Could not fetch tweets this cycle, will retry next time.")
        return

    # Oldest -> newest so we post in chronological order and update state
    # incrementally (if Discord posting fails partway through, we don't
    # lose track of what we already successfully posted).
    tweets = list(reversed(tweets))

    if last_seen_id is None:
        # First run ever: don't blast out historical tweets, just record
        # the current newest ID as the baseline and start fresh from here.
        if tweets:
            state["last_seen_id"] = tweets[-1].id
            save_state(state)
            print(f"[monitor] First run - baseline set to tweet {tweets[-1].id}. "
                  f"No pings sent for existing tweets.")
        return

    new_tweets = []
    seen_baseline = False
    for t in tweets:
        if t.id == last_seen_id:
            seen_baseline = True
            continue
        if not seen_baseline:
            continue  # still older than or equal to last_seen_id
        new_tweets.append(t)

    # Fallback: if last_seen_id has scrolled off the checked window
    # entirely (e.g. bot was down a while), treat all fetched tweets as new.
    if not seen_baseline:
        new_tweets = tweets

    for t in new_tweets:
        if is_late_change(t):
            post_to_discord(t, ping=not should_skip_ping(t))
        state["last_seen_id"] = t.id
        save_state(state)


def main() -> None:
    if RUN_MODE == "loop":
        print(f"[monitor] Starting loop, polling every {POLL_INTERVAL_SECONDS}s...")
        while True:
            try:
                run_once()
            except Exception as e:
                print(f"[monitor] Unexpected error: {e}")
            time.sleep(POLL_INTERVAL_SECONDS)
    else:
        run_once()


if __name__ == "__main__":
    main()
