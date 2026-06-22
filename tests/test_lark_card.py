from rss import parse_feed
from lark_card import parse_entry_to_card, CATEGORY_COLORS


def load_latest_entry():
    return parse_feed(open("tests/fixtures/juya_sample.xml").read())[0]


def test_card_has_header_with_date():
    entry = load_latest_entry()
    card = parse_entry_to_card(entry)
    assert card["header"]["template"] in ("purple", "blue", "indigo")
    title_text = card["header"]["title"]["content"]
    assert "橘鸦 AI 早报" in title_text
    assert entry["title"] in title_text


def test_card_contains_category_sections():
    entry = load_latest_entry()
    card = parse_entry_to_card(entry)
    text_blob = str(card)
    assert any(cat in text_blob for cat in CATEGORY_COLORS)


def test_card_contains_view_full_button():
    entry = load_latest_entry()
    card = parse_entry_to_card(entry)
    actions = [e for e in card["elements"] if e.get("tag") == "action"]
    assert len(actions) >= 1
    buttons = actions[-1]["actions"]
    urls = [b["url"] for b in buttons if "url" in b]
    assert entry["link"] in urls


def test_card_has_disclaimer():
    entry = load_latest_entry()
    card = parse_entry_to_card(entry)
    text_blob = str(card)
    assert "juya" in text_blob.lower() or "AI 辅助" in text_blob


def test_card_json_serializable():
    import json
    entry = load_latest_entry()
    card = parse_entry_to_card(entry)
    json.dumps(card)
