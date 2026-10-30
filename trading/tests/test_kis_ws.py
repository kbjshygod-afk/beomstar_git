"""KIS WebSocket protocol helpers (checklist 2.5)."""
import json

from swing_engine import kis_ws

TICK = ("0|H0STCNT0|002|" + "^".join(["096530", "093001", "33600", "2", "500", "1.51", "33450.5", "33200", "33700",
                                      "33100", "33650", "33600", "120", "302497", "10123456789"] + ["x"] * 31)
        + "^" + "^".join(["425420", "093002", "12000", "5", "-100", "-0.83", "12050", "12100", "12200", "11950",
                          "12010", "12000", "30", "88000", "1000000"] + ["y"] * 31))


def test_subscribe_message_shape():
    m = json.loads(kis_ws.subscribe_message("K", "425420.KQ", "J"))
    assert m["header"] == {"approval_key": "K", "custtype": "P", "tr_type": "1", "content-type": "utf-8"}
    assert m["body"]["input"] == {"tr_id": "H0STCNT0", "tr_key": "425420"}
    assert json.loads(kis_ws.subscribe_message("K", "005930", "NX", on=False))["header"]["tr_type"] == "2"
    assert json.loads(kis_ws.subscribe_message("K", "005930", "UN"))["body"]["input"]["tr_id"] == "H0UNCNT0"


def test_parse_ticks_control_and_other():
    kind, ticks = kis_ws.parse_message(TICK)
    assert kind == "ticks" and [t["code"] for t in ticks] == ["096530", "425420"]
    assert ticks[0]["price"] == 33600.0 and ticks[0]["vol"] == 120.0 and ticks[0]["time"] == "093001" and ticks[0]["tr_id"] == "H0STCNT0"
    assert ticks[1]["acml_vol"] == 88000.0
    ping = json.dumps({"header": {"tr_id": "PINGPONG", "datetime": "20261102090000"}})
    kind, ctrl = kis_ws.parse_message(ping)
    assert kind == "control" and kis_ws.is_pingpong(ctrl) and kis_ws.ack_status(ctrl) == (None, None, None)
    ack = json.dumps({"header": {"tr_id": "H0STCNT0", "tr_key": "096530", "encrypt": "N"},
                      "body": {"rt_cd": "0", "msg_cd": "OPSP0000", "msg1": "SUBSCRIBE SUCCESS"}})
    assert kis_ws.ack_status(kis_ws.parse_message(ack)[1]) == ("096530", "0", "SUBSCRIBE SUCCESS")
    assert kis_ws.parse_message("garbage")[0] == "other"


def test_recorder_tracks_symbols_and_stop_distance():
    rec = kis_ws.Recorder(stops={"096530": 30000.0})
    rec.on_frame(json.dumps({"header": {"tr_id": "PINGPONG"}}))
    rec.on_frame(TICK)
    rec.on_frame(TICK.replace("33600^2^500", "32000^5^-1100", 1))
    sm = rec.summary()
    assert sm["frames"] == 3 and sm["control"] == 1 and sm["pings"] == 1
    s = sm["symbols"]["096530"]
    assert s["ticks"] == 2 and s["high"] == 33600.0 and s["low"] == 32000.0 and s["last_price"] == 32000.0
    assert s["volume"] == 240.0 and s["stop_distance_pct"] == 6.67 and sm["symbols"]["425420"]["stop"] is None
    txt = rec.summary_text()
    assert "096530: 2 ticks 093001→093001" in txt and "손절가 30,000까지 +6.67%" in txt
    json.dumps(sm)


def test_env_file_credentials(tmp_path, monkeypatch):
    for k in ("KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ENV"):
        monkeypatch.delenv(k, raising=False)
    p = tmp_path / "kis.env"
    p.write_text("# paper server\nKIS_APP_KEY=abc\nKIS_APP_SECRET='s3cret'\nKIS_ENV=vps\n")
    cred = kis_ws.env_file_credentials(str(p))
    assert cred == {"key": "abc", "secret": "s3cret", "env": "vps"}
    assert kis_ws.WS_URL[cred["env"]].endswith(":31000")
