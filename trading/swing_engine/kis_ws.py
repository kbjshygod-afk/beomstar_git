"""KIS Open API WebSocket: real-time trade ticks for the held symbols (checklist 2.5).

Protocol (koreainvestment/open-trading-api, as known 2026-10; tools/kis_ws_probe.py confirms it
on the owner's Mac, since GitHub Actions is not suited to long-lived sockets):
  approval : POST {base}/oauth2/Approval {"grant_type":"client_credentials","appkey","secretkey"}
             -> {"approval_key"}  (note: "secretkey", unlike the REST token's "appsecret")
  socket   : ws://ops.koreainvestment.com:21000 (prod) / :31000 (vps paper server)
  subscribe: {"header":{"approval_key","custtype":"P","tr_type":"1","content-type":"utf-8"},
              "body":{"input":{"tr_id":"H0STCNT0","tr_key":"096530"}}}   tr_type 2 = unsubscribe
             H0STCNT0 = KRX regular-session trades, H0NXCNT0 = NXT, H0UNCNT0 = both combined.
  messages : JSON for control (subscribe ack rt_cd/msg1, PINGPONG to echo back);
             trades as text "0|H0STCNT0|<n>|f1^f2^...": n records of TICK_FIELDS joined by ^.
             Trade ticks are not encrypted (only order notices are). Up to 41 registrations per key.
Nothing here changes signals or places orders: it only listens.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime

from .kis import BASE, KISError, num

WS_URL = {"prod": "ws://ops.koreainvestment.com:21000", "vps": "ws://ops.koreainvestment.com:31000"}
TR_ID = {"J": "H0STCNT0", "NX": "H0NXCNT0", "UN": "H0UNCNT0"}
MAX_SUBSCRIPTIONS = 41
# H0STCNT0 output fields in order (the first 15 are what the probe uses; the rest are kept by name)
TICK_FIELDS = ("code", "time", "price", "sign", "change", "change_pct", "wavg_price", "open", "high", "low",
               "ask1", "bid1", "vol", "acml_vol", "acml_amount", "ask_cnt", "bid_cnt", "net_buy_cnt", "cttr",
               "seln_cntg_smtn", "shnu_cntg_smtn", "cntg_cls_code", "shnu_rate", "prdy_vol_vrss_acml_vol_rate",
               "oprc_hour", "oprc_vrss_prpr_sign", "oprc_vrss_prpr", "hgpr_hour", "hgpr_vrss_prpr_sign",
               "hgpr_vrss_prpr", "lwpr_hour", "lwpr_vrss_prpr_sign", "lwpr_vrss_prpr", "bsop_date",
               "new_mkop_cls_code", "trht_yn", "askp_rsqn1", "bidp_rsqn1", "total_askp_rsqn", "total_bidp_rsqn",
               "vol_tnrt", "prdy_smns_hour_acml_vol", "prdy_smns_hour_acml_vol_rate", "hour_cls_code",
               "mrkt_trtm_cls_code", "vi_stnd_prc")
NUMERIC = {"price", "change", "change_pct", "wavg_price", "open", "high", "low", "ask1", "bid1", "vol", "acml_vol",
           "acml_amount"}


def approval_key(cred: dict, timeout: float = 30) -> str:
    body = json.dumps({"grant_type": "client_credentials", "appkey": cred["key"], "secretkey": cred["secret"]}).encode()
    req = urllib.request.Request(f"{BASE[cred['env']]}/oauth2/Approval", data=body, method="POST",
                                 headers={"content-type": "application/json; charset=utf-8", "User-Agent": "beomstar-swing/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise KISError(f"approval: HTTP {e.code} {e.read()[:200].decode('utf-8', 'replace')}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise KISError(f"approval: network {getattr(e, 'reason', e)}") from None
    key = data.get("approval_key")
    if not key:
        raise KISError(f"approval: no approval_key in {str(data)[:200]}")
    return key


def subscribe_message(key: str, code: str, venue: str = "J", on: bool = True) -> str:
    return json.dumps({"header": {"approval_key": key, "custtype": "P", "tr_type": "1" if on else "2",
                                  "content-type": "utf-8"},
                       "body": {"input": {"tr_id": TR_ID[venue], "tr_key": code.split(".")[0]}}})


def parse_message(text: str) -> tuple[str, object]:
    """('control', dict) for JSON frames (subscribe acks, PINGPONG), ('ticks', [dict, ...]) for
    trade frames, ('other', text) for anything else."""
    t = text.strip()
    if t.startswith("{"):
        try:
            return "control", json.loads(t)
        except ValueError:
            return "other", text
    parts = t.split("|", 3)
    if len(parts) == 4 and parts[0] in ("0", "1") and parts[1] in TR_ID.values():
        n = int(parts[2]) if parts[2].isdigit() else 1
        vals = parts[3].split("^")
        width = len(vals) // n if n else len(vals)
        ticks = []
        for i in range(n):
            rec = vals[i * width:(i + 1) * width]
            d = {name: (num(v) if name in NUMERIC else v) for name, v in zip(TICK_FIELDS, rec)}
            d["tr_id"] = parts[1]
            ticks.append(d)
        return "ticks", ticks
    return "other", text


def is_pingpong(ctrl: dict) -> bool:
    return (ctrl.get("header") or {}).get("tr_id") == "PINGPONG"


def ack_status(ctrl: dict) -> tuple[str | None, str | None, str | None]:
    """(tr_key, rt_cd, msg1) of a subscribe acknowledgement, or (None, None, None)."""
    h, b = ctrl.get("header") or {}, ctrl.get("body") or {}
    if "rt_cd" not in b:
        return None, None, None
    return h.get("tr_key"), b.get("rt_cd"), b.get("msg1")


@dataclass
class SymbolStats:
    ticks: int = 0
    first: str | None = None
    last: str | None = None
    last_price: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float = 0.0
    stop: float | None = None

    def update(self, t: dict) -> None:
        p = t.get("price")
        self.ticks += 1
        self.first = self.first or t.get("time")
        self.last = t.get("time")
        if p is not None:
            self.last_price = p
            self.high = p if self.high is None else max(self.high, p)
            self.low = p if self.low is None else min(self.low, p)
        self.volume += t.get("vol") or 0.0

    def stop_distance_pct(self) -> float | None:
        if self.stop and self.last_price:
            return (self.last_price / self.stop - 1) * 100
        return None


@dataclass
class Recorder:
    """Per-symbol statistics of a listening session plus the raw tick log."""
    stops: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    frames: int = 0
    control: int = 0
    pings: int = 0
    started: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def on_frame(self, text: str) -> tuple[str, object]:
        self.frames += 1
        kind, payload = parse_message(text)
        if kind == "control":
            self.control += 1
            if is_pingpong(payload):
                self.pings += 1
        elif kind == "ticks":
            for t in payload:
                s = self.stats.setdefault(t["code"], SymbolStats(stop=self.stops.get(t["code"])))
                s.update(t)
        return kind, payload

    def summary(self) -> dict:
        return {"started": self.started, "frames": self.frames, "control": self.control, "pings": self.pings,
                "symbols": {c: {"ticks": s.ticks, "first": s.first, "last": s.last, "last_price": s.last_price,
                                "high": s.high, "low": s.low, "volume": s.volume, "stop": s.stop,
                                "stop_distance_pct": None if s.stop_distance_pct() is None else round(s.stop_distance_pct(), 2)}
                            for c, s in sorted(self.stats.items())}}

    def summary_text(self) -> str:
        sm = self.summary()
        L = [f"frames {sm['frames']} · control {sm['control']} · pingpong {sm['pings']} · symbols with ticks {len(sm['symbols'])}"]
        for c, s in sm["symbols"].items():
            dist = f" · 손절가 {s['stop']:,.0f}까지 {s['stop_distance_pct']:+.2f}%" if s["stop_distance_pct"] is not None else ""
            L.append(f"  {c}: {s['ticks']} ticks {s['first']}→{s['last']} · last {s['last_price']:,.0f} "
                     f"(high {s['high']:,.0f} / low {s['low']:,.0f}) · vol {s['volume']:,.0f}{dist}")
        return "\n".join(L)


def env_file_credentials(path: str) -> dict | None:
    """Read KIS_APP_KEY / KIS_APP_SECRET / KIS_ENV from a `KEY=value` file (the Mac keeps them in
    ~/.config/beomstar/kis.env, mode 600) into os.environ, then return kis.credentials()."""
    from .kis import credentials
    if path and os.path.exists(path):
        for ln in open(path, encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return credentials()
