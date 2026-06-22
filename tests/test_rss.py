from datetime import date
import pytz
from rss import extract_today_entry, parse_feed

FIXTURE = "tests/fixtures/juya_sample.xml"


def test_parse_feed_returns_entries():
    entries = parse_feed(open(FIXTURE).read())
    assert len(entries) > 0
    first = entries[0]
    assert "title" in first
    assert "link" in first
    assert "published_dt" in first  # datetime in UTC
    assert "content_html" in first


def test_extract_today_entry_matches_beijing_today():
    xml = open(FIXTURE).read()
    entries = parse_feed(xml)
    latest_pub_beijing = entries[0]["published_dt"].astimezone(pytz.timezone("Asia/Shanghai"))
    fake_today = latest_pub_beijing.date()

    entry = extract_today_entry(xml, today=fake_today)
    assert entry is not None
    assert entry["title"].startswith(fake_today.strftime("%Y-%m-%d"))


def test_extract_today_entry_returns_none_when_no_match():
    xml = open(FIXTURE).read()
    entry = extract_today_entry(xml, today=date(2000, 1, 1))
    assert entry is None
