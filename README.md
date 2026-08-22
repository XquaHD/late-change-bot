# AFLW Late Change Monitor → Discord

Watches @aflwomens (or any account) for tweets containing "late change"
(configurable) and pings Discord when one appears.

**Important, please read:** getting free access to tweets meant working
around X locking down its API. After trying three dead-end methods, this
uses [twscrape](https://github.com/vladkens/twscrape), which logs into X
with a **real account's session cookies** and queries the same internal API
the X website itself uses. This is more resilient than the guest-token
tricks we tried first, but it comes with real trade-offs:

- **Use a spare/burner X account for this**, not your main one. Automating
  requests through an account is against X's terms of service, and there's
  a real risk X limits or locks that account. This is why a spare account
  matters - if it does get locked, it costs you nothing but re-doing setup
  with a new one.
- The session cookies (`auth_token` / `ct0`) expire every so often (weeks
  to months, hard to predict). If the bot suddenly stops finding new
  tweets, that's almost certainly expired cookies - re-extract fresh ones
  (steps below) and update them.
- As with the other approaches, X could change its internal API again and
  break this too. The fetch logic lives entirely in `fetch_tweets.py`, so
  if that happens, only this file needs to change.

## How it works

1. `fetch_tweets.py` logs into X via twscrape using your spare account's
   cookies and grabs the account's recent tweets.
2. `monitor.py` filters out retweets and anything not matching your
   keywords (default: "late change"), keeps track of the newest tweet ID
   it's already handled (`state.json`), and posts any new matches to a
   Discord webhook with an `@everyone` ping.
3. Something needs to run `monitor.py` on a schedule - see hosting options
   below.

## 1. Get your spare account's session cookies

1. In a normal browser, log into X.com with your **spare/burner account**.
2. Open DevTools (Mac: `Cmd+Option+I`, Windows: `F12`) → **Application**
   tab → **Cookies** → `https://x.com`.
3. Find the `auth_token` and `ct0` rows and copy their **Value** column.
   Treat these like a password - anyone with them can act as that account.

## 2. Test the fetcher locally

```bash
python3 -m venv venv
source venv/bin/activate       # run this again in any new terminal session
pip install -r requirements.txt

export TWSCRAPE_AUTH_TOKEN="paste_value_here"
export TWSCRAPE_CT0="paste_value_here"
python3 fetch_tweets.py
```

You should see a list of recent tweets printed. If you get an error, paste
it back and I'll help adjust - X's internal API could have changed again,
or the cookies might be stale/incorrect.

## 3. Create the Discord webhook

1. In Discord, go to the target channel → **Edit Channel → Integrations →
   Webhooks → New Webhook**.
2. Name it (e.g. "AFLW Late Changes"), copy the **Webhook URL**.
3. Make sure the channel/role permissions allow `@everyone` mentions if
   you want that ping to actually notify people (Server Settings → Roles →
   @everyone → check "Mention @everyone, @here, and All Roles" is allowed
   for that channel, or the ping will show but not notify anyone).

## 4. Configure

Copy `.env.example` to `.env` and fill in the values. Key settings:

| Variable | Meaning |
|---|---|
| `TWITTER_USERNAME` | Account to watch (default `aflwomens`) |
| `DISCORD_WEBHOOK_URL` | Your webhook URL |
| `TWSCRAPE_AUTH_TOKEN` / `TWSCRAPE_CT0` | Spare account's session cookies |
| `KEYWORDS` | Comma-separated, case-insensitive match list |
| `PING_TARGET` | `everyone`, `role:<ROLE_ID>`, or `none` |
| `CHECK_COUNT` | How many recent tweets to scan each poll |
| `POLL_INTERVAL_SECONDS` | Only used in `RUN_MODE=loop` |
| `RUN_MODE` | `once` (for cron/Actions) or `loop` (for a persistent process) |

To ping a specific role instead of everyone: right-click the role in
Discord (enable Developer Mode in Discord settings first) → Copy ID → set
`PING_TARGET=role:123456789012345678`.

**First run note:** the very first time `monitor.py` runs, it won't ping
for existing tweets — it just records the current newest tweet as a
baseline so you don't get blasted with the last dozen late changes on
setup. Every run after that pings for genuinely new matches.

## 5. Hosting options (pick one)

### Option A — GitHub Actions (recommended, free, no server)

This repo includes `.github/workflows/monitor.yml`, which runs the check
every 5 minutes on GitHub's infrastructure - nothing to host yourself.

1. Push this folder to a **new GitHub repo** (private is fine - and
   given the cookies involved, keep it private).
2. Repo Settings → Secrets and variables → Actions:
   - **Secrets** tab → add `DISCORD_WEBHOOK_URL`, `TWSCRAPE_AUTH_TOKEN`,
     `TWSCRAPE_CT0`.
   - **Variables** tab → optionally add `TWITTER_USERNAME`, `KEYWORDS`,
     `PING_TARGET`, `CHECK_COUNT` if you want non-default values.
3. Repo Settings → Actions → General → under "Workflow permissions" select
   **Read and write permissions** (the workflow needs this to save
   `state.json` back to the repo between runs).
4. That's it - it'll start running on schedule. You can also trigger a
   manual run from the **Actions** tab → "AFLW Late Change Monitor" → "Run
   workflow", which is the easiest way to test it end-to-end.

Notes:
- GitHub's cron minimum is every 5 minutes, and actual runs can lag a bit
  further behind during busy periods - that's a GitHub platform limit, not
  something in this code.
- When your cookies eventually expire, update the `TWSCRAPE_AUTH_TOKEN` /
  `TWSCRAPE_CT0` secrets with fresh values from step 1.

### Option B — Always-on VPS

If you'd rather run it continuously yourself:

1. Any small Linux VPS works (Oracle Cloud has a genuinely free "Always
   Free" tier VM if you want zero ongoing cost; otherwise budget VPS
   providers like Hetzner or DigitalOcean run a few dollars/month).
2. `git clone` this project, set up the venv and install dependencies as
   in step 2 above.
3. Set `RUN_MODE=loop` in `.env` and run it under a process manager so it
   survives reboots/crashes, e.g. with **systemd**:

```ini
# /etc/systemd/system/aflw-late-change.service
[Unit]
Description=AFLW Late Change Monitor
After=network.target

[Service]
WorkingDirectory=/path/to/aflw-late-change-bot
EnvironmentFile=/path/to/aflw-late-change-bot/.env
ExecStart=/path/to/aflw-late-change-bot/venv/bin/python3 monitor.py
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now aflw-late-change
```

## Files

- `fetch_tweets.py` — the only file you'd need to change if X breaks this
  method too (e.g. to swap in a paid API instead).
- `monitor.py` — filtering, state tracking, Discord posting.
- `state.json` — tracks the last tweet ID handled (committed back to the
  repo automatically by the GitHub Actions workflow).
- `.github/workflows/monitor.yml` — the scheduled runner.
- `test_twscrape.py` — a standalone script used during setup to confirm
  the cookies work; not needed once the bot is running.
