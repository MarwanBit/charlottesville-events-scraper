import requests
import json
import pprint

URL = "https://lf0ccfqrh3-dsn.algolia.net/1/indexes/*/queries"

HEADERS = {
    "x-algolia-application-id": "LF0CCFQRH3",
    "x-algolia-api-key": "9ff98e053974ef9b01af86dfe17897f7",
    "content-type": "application/json",
}

def fetch_page(page):
    payload = {
        "requests": [
            {
                "indexName": "events_cms_items",
                "params": f"query=&page={page}&hitsPerPage=9"
            }
        ]
    }
    res = requests.post(URL, headers=HEADERS, json=payload)
    return res.json()


def extract_events(data):
    hits = data["results"][0]["hits"]
    return [
        {
            "name": h["Name"],
            "start": h["startTimestamp"],
            "end": h["endTimestamp"],
            "location": h.get("locationName"),
            "url": "https://www.visitarizona.com" + h["webflowLink"]
        }
        for h in hits
    ]


# --- Run ---
first = fetch_page(0)
pprint.pprint(first)
nb_pages = first["results"][0]["nbPages"]
all_events = []
for page in range(nb_pages):
    data = fetch_page(page)
    all_events.extend(extract_events(data))
# pprint.pprint(all_events)
print(len(all_events))