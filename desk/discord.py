"""Discord webhook posting (embeds, 429 retry, batching). Webhook URLs come from environment secrets only."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

CHANNELS = {
    "general": "DISCORD_GENERAL_WEBHOOK",
    "nba_nfl": "DISCORD_NBA_NFL_WEBHOOK",
    "tennis_soccer": "DISCORD_TENNIS_SOCCER_WEBHOOK",
    "live": "DISCORD_LIVE_WEBHOOK",
}


def webhook(channel: str) -> str:
    return os.environ.get(CHANNELS[channel], "")


def post(channel: str, embeds: list[dict] | None = None, content: str | None = None) -> bool:
    """Post to a channel. With DRY_RUN=1 (or no webhook set) prints instead and returns False."""
    url = webhook(channel)
    embeds = embeds or []
    for e in embeds:  # Discord limits
        if "description" in e:
            e["description"] = e["description"][:4000]
        e["fields"] = [{**f, "value": (f["value"] or "–")[:1024], "name": f["name"][:256]} for f in e.get("fields", [])][:25]
    batches = [embeds[i:i + 10] for i in range(0, len(embeds), 10)] or [[]]
    if os.environ.get("DRY_RUN") or not url:
        print(f"[{channel}{' (no webhook)' if not url else ''}]", content or "", json.dumps(embeds, indent=1)[:3000])
        return False
    for i, batch in enumerate(batches):
        payload = {"username": "Betting Desk", "embeds": batch}
        if content and i == 0:
            payload["content"] = content[:2000]
        data = json.dumps(payload).encode()
        for attempt in range(4):
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json",
                                                                   "User-Agent": "BettingDesk/1.0"})
            try:
                urllib.request.urlopen(req, timeout=20).read()
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 3:
                    try:
                        wait = float(json.loads(e.read()).get("retry_after", 2))
                    except Exception:
                        wait = 2
                    time.sleep(wait + 0.5)
                    continue
                raise
        time.sleep(0.6)
    return True
