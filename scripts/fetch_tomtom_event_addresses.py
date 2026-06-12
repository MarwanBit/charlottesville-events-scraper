#!/usr/bin/env python3
"""One-off: print tab-separated event_link, title, address for listed Tom Tom Sched URLs.

Uses the same resolution as TomTomFestivalEventWebsite (venues index, fallbacks, optional Nominatim).
Set TOMTOM_DISABLE_NOMINATIM=1 for a fast run when Sched/venues data is enough.
Suppress stderr to hide validation warnings: 2>/dev/null
"""
from __future__ import annotations

import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.websites.tomtomfestival import TomTomFestivalEventWebsite  # noqa: E402

URLS = [
    "https://tomtomfestival2026.sched.com/event/2IqF3/the-future-of-our-workforce-in-the-age-of-ai-a-conversation-with-senator-mark-warner",
    "https://tomtomfestival2026.sched.com/event/2Iz6I/spotlight-virginia-leading-the-way-in-resilience-and-climate-tech",
    "https://tomtomfestival2026.sched.com/event/2Ehgw/downtown-mall-block-party",
    "https://tomtomfestival2026.sched.com/event/2JSNx/lunch-learn-private-public-partnerships-to-reimagine-public-housing-in-charlottesville",
    "https://tomtomfestival2026.sched.com/event/2EhXn/west-stage-dj-c-lew-dj-inferno",
    "https://tomtomfestival2026.sched.com/event/2Ehgz/downtown-mall-block-party",
    "https://tomtomfestival2026.sched.com/event/2JGXG/west-stage-fuego-dance-team",
    "https://tomtomfestival2026.sched.com/event/2IxGN/uva-e-cup-100k-in-prize-money",
    "https://tomtomfestival2026.sched.com/event/2Iu6f/democracy-requires-courage-why-civics-matter-more-than-ever",
    "https://tomtomfestival2026.sched.com/event/2IpI7/west-stage-todd-albright",
    "https://tomtomfestival2026.sched.com/event/2IuRe/why-isnt-housing-affordable-the-cost-of-community-scarcity",
    "https://tomtomfestival2026.sched.com/event/2Ehe2/porchella-annual-belmont-front-porch-concert-series",
    "https://tomtomfestival2026.sched.com/event/2Iz3N/spotlight-ai-+-entrepreneurship",
    "https://tomtomfestival2026.sched.com/event/2JGXa/west-stage-latin-social-dancing-giveaways",
    "https://tomtomfestival2026.sched.com/event/2EhW0/west-stage-with-the-front-porch",
    "https://tomtomfestival2026.sched.com/event/2Iscy/central-stage-on-the-one-dance-group",
    "https://tomtomfestival2026.sched.com/event/2IuQv/placemaking-the-downtown-mall-at-50-and-the-future-of-charlottesville",
    "https://tomtomfestival2026.sched.com/event/2Iq4v/spotlight-defense-intelligence-activating-scaling-and-growing-central-virginias-innovation-economy",
    "https://tomtomfestival2026.sched.com/event/2Iplc/central-stage-skank",
    "https://tomtomfestival2026.sched.com/event/2EhdA/west-stage-jmu-latin-dance-club",
    "https://tomtomfestival2026.sched.com/event/2IzA1/powering-the-next-economy-energy-ai-and-the-infrastructure-of-the-future",
    "https://tomtomfestival2026.sched.com/event/2Isco/central-stage-cville-drum-circle",
    "https://tomtomfestival2026.sched.com/event/2IsdG/central-stage-darrell-rose-the-reggae-ambassadors",
    "https://tomtomfestival2026.sched.com/event/2IqBc/courage-is-the-first-ingredient-the-larabar-founding-story-and-building-companies-with-intention",
    "https://tomtomfestival2026.sched.com/event/2IpIC/west-stage-dj-williams",
    "https://tomtomfestival2026.sched.com/event/2Iplr/downtown-mall-block-party-elby-brass-parade",
    "https://tomtomfestival2026.sched.com/event/2IsdO/central-stage-mighty-joshua",
    "https://tomtomfestival2026.sched.com/event/2Ehh8/central-stage-brass-ska-stage",
    "https://tomtomfestival2026.sched.com/event/2Iz6d/leading-with-courage-building-durable-companies",
    "https://tomtomfestival2026.sched.com/event/2IpI9/west-stage-richelle-claiborne-friends",
    "https://tomtomfestival2026.sched.com/event/2Iz5J/fireside-chat-the-luminoah-story-from-a-sons-rare-tumor-diagnosis-to-a-medical-breakthrough",
    "https://tomtomfestival2026.sched.com/event/2JNJM/innovation-summit-welcome",
    "https://tomtomfestival2026.sched.com/event/2JOMZ/pitch-fest-a-civic-storytelling-lab-with-c-ville-weekly",
    "https://tomtomfestival2026.sched.com/event/2Ehh5/ting-pavillion-rb-+-dance",
    "https://tomtomfestival2026.sched.com/event/2IpHy/west-stage-arthur-terembula",
    "https://tomtomfestival2026.sched.com/event/2Ipli/central-stage-elby-brass",
    "https://tomtomfestival2026.sched.com/event/2Ehd7/west-stage-learn-to-salsa-w-uva-salsa-club",
    "https://tomtomfestival2026.sched.com/event/2EhdJ/west-stage-uva-salsa-club",
    "https://tomtomfestival2026.sched.com/event/2JGWI/west-stage-social-dancing-with-dj-x",
    "https://tomtomfestival2026.sched.com/event/2IuNY/how-peer-cities-are-innovating-think-tanks-data-coalitional-action",
    "https://tomtomfestival2026.sched.com/event/2IH8z/central-stage-reggae-stage",
    "https://tomtomfestival2026.sched.com/event/2IqVy/beyond-the-lab-nasa-technologies-powering-the-next-generation-of-startups",
    "https://tomtomfestival2026.sched.com/event/2IsdA/central-stage-dj-joshua-crenshaw",
    "https://tomtomfestival2026.sched.com/event/2EhW3/west-stage-latin-partner-dance-and-more",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CharlottesvilleEventsScraper/1.1; address-export)"}


def main() -> None:
    print("event_link\ttitle\taddress")
    for url in URLS:
        try:
            r = requests.get(url, headers=HEADERS, timeout=45)
            r.raise_for_status()
            site = TomTomFestivalEventWebsite(url, soup=BeautifulSoup(r.text, "html.parser"))
            events = site.get_events(None)
            if not events:
                print(f"{url}\t\t")
                continue
            e = events[0]
            title = (e.get("title") or "").replace("\t", " ")
            addr = (e.get("address") or "").replace("\t", " ")
            print(f"{url}\t{title}\t{addr}")
        except Exception as ex:
            print(f"{url}\tERROR\t{ex}")


if __name__ == "__main__":
    main()
