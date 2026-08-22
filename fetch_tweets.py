"""
fetch_tweets.py

Pulls recent tweets from an X/Twitter account using twscrape, which logs in
with a real account's session cookies and queries the same internal GraphQL
API the X website itself uses.

This requires TWSCRAPE_AUTH_TOKEN and TWSCRAPE_CT0 env vars, taken from the
`auth_token` and `ct0` cookies of a logged-in X account (ideally a spare
account dedicated to this bot, not your main one - see README.md).

Notes:
  - Cookies expire eventually (weeks to months) - if fetching starts failing
    after previously working, re-extract fresh cookies and update them.
  - This account is doing automated requests, which is against X's terms of
    service; there's a real risk X could limit or lock it. That's the
    accepted trade-off of the free route - see README.md.
  - As with the other approaches tried, X could change its internal API at
    any time and break this too. If that happens, only this file needs to
    change - the rest of the bot doesn't care how tweets are fetched.
"""

import os
import asyncio
from dataclasses import dataclass
from typing import List, Optional

from twscrape import API

AUTH_TOKEN = os.environ.get("TWSCRAPE_AUTH_TOKEN", "")
CT0 = os.environ.get("TWSCRAPE_CT0", "")

# twscrape needs a sqlite db to store the account session in. Using a fresh
# one each run (default path, recreated each time in CI) is simplest since
# we pass cookies fresh every run anyway - no session persistence needed.
DB_PATH = os.environ.get("TWSCRAPE_DB_PATH", "accounts.db")


@dataclass
class Tweet:
    id: str
    text: str
    url: str
    is_retweet: bool
    is_reply: bool


async def _get_recent_tweets_async(username: str, limit: int) -> Optional[List[Tweet]]:
    if not AUTH_TOKEN or not CT0:
        print("[fetch_tweets] TWSCRAPE_AUTH_TOKEN / TWSCRAPE_CT0 not set")
        return None

    try:
        api = API(DB_PATH)
        cookies = f"auth_token={AUTH_TOKEN}; ct0={CT0}"
        await api.pool.add_account(
            "burner_account", "unused_password", "unused@example.com", "unused_email_password",
            cookies=cookies,
        )

        user = await api.user_by_login(username)
        if user is None:
            print(f"[fetch_tweets] Could not resolve user @{username}")
            return None

        tweets: List[Tweet] = []
        async for t in api.user_tweets(user.id, limit=limit):
            tweets.append(
                Tweet(
                    id=str(t.id),
                    text=t.rawContent or "",
                    url=t.url,
                    is_retweet=t.retweetedTweet is not None,
                    is_reply=t.inReplyToTweetId is not None,
                )
            )
        return tweets
    except Exception as e:
        print(f"[fetch_tweets] twscrape fetch failed: {e}")
        return None


def get_recent_tweets(username: str, limit: int = 20) -> Optional[List[Tweet]]:
    """
    Returns a list of the account's most recent tweets (newest first),
    or None if the fetch failed, so the caller can log it and just try
    again next poll instead of crashing.
    """
    return asyncio.run(_get_recent_tweets_async(username, limit))


if __name__ == "__main__":
    # Quick manual test: python3 fetch_tweets.py
    # (requires TWSCRAPE_AUTH_TOKEN / TWSCRAPE_CT0 env vars set)
    tweets = get_recent_tweets("aflwomens")
    if tweets is None:
        print("Fetch failed - see error above.")
    else:
        print(f"Got {len(tweets)} tweets:\n")
        for t in tweets:
            flag = " [RT]" if t.is_retweet else (" [reply]" if t.is_reply else "")
            print(f"- {t.id}{flag}: {t.text[:100]}")
