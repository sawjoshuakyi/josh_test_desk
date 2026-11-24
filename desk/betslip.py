"""Sportsbook bet-slip links for the desk's slips.

The Odds API (includeLinks/includeSids) gives, per outcome, a bookmaker link and the bookmaker's own selection id.
Single legs use that link as-is. For parlays we combine the ids into one link:
  FanDuel:    https://sportsbook.fanduel.com/addToBetslip?marketId[0]=M1&selectionId[0]=S1&marketId[1]=M2&selectionId[1]=S2
  DraftKings: the outcome ids from each leg's link joined with '+' in one ?outcomes= parameter
Combined links are built from documented single-leg formats; the per-leg links are always listed as a fallback.
Hosts are configurable (config.BETSLIP_HOSTS) for state or Ontario sites.
"""
from __future__ import annotations

import urllib.parse

from . import config


def _host(book: str, url: str) -> str:
    want = config.BETSLIP_HOSTS.get(book)
    if not want or not url:
        return url
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme, want, p.path, p.query, p.fragment))


def fanduel(legs: list[dict]) -> str | None:
    """legs: [{"sid": selectionId, "market_sid": marketId}] — every leg must have both."""
    if not legs or any(not (l.get("sid") and l.get("market_sid")) for l in legs):
        return None
    q = []
    for i, l in enumerate(legs):
        q += [(f"marketId[{i}]", l["market_sid"]), (f"selectionId[{i}]", l["sid"])]
    if len(legs) == 1:
        q = [("marketId", legs[0]["market_sid"]), ("selectionId", legs[0]["sid"])]
    return _host("fanduel", "https://sportsbook.fanduel.com/addToBetslip?" + urllib.parse.urlencode(q, safe="[]"))


def draftkings(legs: list[dict]) -> str | None:
    """legs: [{"link": DK outcome link, "sid": outcome id}]. Uses the first leg's link and puts every outcome id in
    its ?outcomes= parameter."""
    if not legs:
        return None
    ids = []
    for l in legs:
        oid = None
        if l.get("link"):
            qs = urllib.parse.parse_qs(urllib.parse.urlsplit(l["link"]).query)
            oid = (qs.get("outcomes") or [None])[0]
        oid = oid or l.get("sid")
        if not oid:
            return None
        ids.append(oid)
    base = legs[0].get("link") or "https://sportsbook.draftkings.com/"
    p = urllib.parse.urlsplit(base)
    q = dict(urllib.parse.parse_qsl(p.query))
    q["outcomes"] = "+".join(ids)
    url = urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(q, safe="+"), ""))
    return _host("draftkings", url)


def slip_links(legs: list[dict]) -> dict:
    """legs: board rows (each with dk/fd link info). Returns {"draftkings": url|None, "fanduel": url|None,
    "per_leg": [{"leg", "draftkings", "fanduel"}]}; a combined link is None when any leg is missing at that book."""
    dk = [l.get("links", {}).get("draftkings") or {} for l in legs]
    fd = [l.get("links", {}).get("fanduel") or {} for l in legs]
    out = {"draftkings": draftkings(dk) if all(dk) else None, "fanduel": fanduel(fd) if all(fd) else None,
           "per_leg": []}
    for l, d, f in zip(legs, dk, fd):
        out["per_leg"].append({"leg": l.get("label") or l.get("player") or l.get("side"),
                               "draftkings": _host("draftkings", d.get("link")) if d else None,
                               "fanduel": _host("fanduel", f.get("link")) if f else None})
    return out
