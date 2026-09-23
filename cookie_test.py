import json
import scraper

cases = [
    ("sessionid=abc; ds_user_id=123", {"sessionid": "abc", "ds_user_id": "123"}),
    ("Cookie: sessionid=abc ds_user_id=123", {"sessionid": "abc", "ds_user_id": "123"}),
    ("sessionid=abc\nds_user_id=123", {"sessionid": "abc", "ds_user_id": "123"}),
    (json.dumps([{"name": "sessionid", "value": "abc"}, {"name": "ds_user_id", "value": "123"}]), {"sessionid": "abc", "ds_user_id": "123"}),
    (".instagram.com\tTRUE\t/\tTRUE\t0\tsessionid\tabc\n.instagram.com\tTRUE\t/\tTRUE\t0\tds_user_id\t123", {"sessionid": "abc", "ds_user_id": "123"}),
]
for raw, expected in cases:
    assert scraper.parse_cookie_string(raw) == expected, raw
assert scraper.normalize_cookie_string(cases[0][0]) == "sessionid=abc; ds_user_id=123"
print("cookie format tests passed")
