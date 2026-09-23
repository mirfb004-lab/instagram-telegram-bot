import json
import scraper

cases = [
    ("sessionid=abc; ds_user_id=123", {"sessionid": "abc", "ds_user_id": "123"}),
    ("Cookie: sessionid=abc ds_user_id=123", {"sessionid": "abc", "ds_user_id": "123"}),
    ("sessionid=abc\nds_user_id=123", {"sessionid": "abc", "ds_user_id": "123"}),
    (json.dumps([{"name": "sessionid", "value": "abc"}, {"name": "ds_user_id", "value": "123"}]), {"sessionid": "abc", "ds_user_id": "123"}),
]
for raw, expected in cases:
    assert scraper.parse_cookie_string(raw) == expected, raw
print("cookie format tests passed")
