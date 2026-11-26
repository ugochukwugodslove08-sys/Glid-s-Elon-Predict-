
import os
import re
import html
import requests
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

RSS_URL = "https://fixupx.com/elonmusk/feed.xml"

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def get_text(self):
        return " ".join(self.parts).strip()

def clean_text(value):
    parser = TextExtractor()
    parser.feed(html.unescape(value or ""))
    return " ".join(parser.get_text().split())

def collect_posts():
    response = requests.get(
        RSS_URL,
        headers={"User-Agent": "GlidsElonPredict/1.0"},
        timeout=30
    )
    response.raise_for_status()

    root = ET.fromstring(response.content)
    items = root.findall(".//item")

    records = []

    for item in items:
        def get_value(tag):
            element = item.find(tag)
            return element.text.strip() if element is not None and element.text else ""

        link = get_value("link")
        guid = get_value("guid")
        pub_date = get_value("pubDate")
        description = get_value("description")

        identifier_text = guid or link
        match = re.search(r"/status/(\d+)", identifier_text)

        if not match:
            match = re.search(r"(\d{15,})", identifier_text)

        if not match or not pub_date:
            continue

        try:
            posted_at = parsedate_to_datetime(pub_date)
            if posted_at.tzinfo is None:
                posted_at = posted_at.replace(tzinfo=timezone.utc)
            posted_at = posted_at.astimezone(timezone.utc).isoformat()
        except Exception:
            continue

        records.append({
            "post_id": match.group(1),
            "post_url": link or guid,
            "posted_at": posted_at,
            "post_text": clean_text(description),
            "source": "fxtwitter_rss"
        })

    return records

def save_posts(records):
    if not records:
        print("No new readable posts found.")
        return

    url = f"{SUPABASE_URL}/rest/v1/elon_posts?on_conflict=post_id"

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=ignore-duplicates,return=minimal"
    }

    response = requests.post(
        url,
        headers=headers,
        json=records,
        timeout=30
    )

    if response.status_code not in (200, 201, 204):
        raise Exception(
            f"Supabase error {response.status_code}: {response.text}"
        )

    print(f"Processed {len(records)} feed entries.")

if __name__ == "__main__":
    posts = collect_posts()
    save_posts(posts)
    print("Collection finished.")
