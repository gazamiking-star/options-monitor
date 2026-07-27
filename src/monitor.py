import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))

CONFIG_PATH = ROOT / "config.json"

DATA_LATEST_DIR = ROOT / "data" / "latest"
DATA_HISTORY_DIR = ROOT / "data" / "history"
DOCS_DIR = ROOT / "docs"
DOCS_API_DIR = DOCS_DIR / "api"
DOCS_API_LATEST_DIR = DOCS_API_DIR / "latest"
DOCS_API_HISTORY_DIR = DOCS_API_DIR / "history"


def load_config():
    return json.loads(
        CONFIG_PATH.read_text(encoding="utf-8")
    )


CFG = load_config()


def prepare_directories():
    directories = [
        DATA_LATEST_DIR,
        DATA_HISTORY_DIR,
        DOCS_DIR,
        DOCS_API_LATEST_DIR,
        DOCS_API_HISTORY_DIR,
    ]

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


def fetch_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 options-monitor/2.0"
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def safe_float(value):
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def top_rows(rows, key, count=5):
    return sorted(
        rows,
        key=lambda row: safe_float(row.get(key)) or 0,
        reverse=True,
    )[:count]


def summarize(raw):
    rows = raw.get("rows") or []

    if not rows:
        raise ValueError(
            f"{raw.get('symbol', 'UNKNOWN')} 옵션 데이터 rows가 비어 있습니다."
        )

    spot = safe_float(raw.get("spot"))

    if spot is None:
        raise ValueError(
            f"{raw.get('symbol', 'UNKNOWN')} 현물 가격이 없습니다."
        )

    atm = min(
        rows,
        key=lambda row: abs(
            (safe_float(row.get("strike")) or 0) - spot
        ),
    )

    nearby = [
        row
        for row in rows
        if (
            safe_float(row.get("strike")) is not None
            and spot * 0.85
            <= safe_float(row.get("strike"))
            <= spot * 1.15
        )
    ]

    if not nearby:
        nearby = rows

    call_wall_all = top_rows(rows, "callOI", 1)[0]
    put_wall_all = top_rows(rows, "putOI", 1)[0]

    call_wall_near = top_rows(nearby, "callOI", 1)[0]
    put_wall_near = top_rows(nearby, "putOI", 1)[0]

    max_pain = safe_float(raw.get("maxPain"))

    distance_to_max_pain_pct = None

    if max_pain is not None and spot != 0:
        distance_to_max_pain_pct = round(
            (max_pain / spot - 1) * 100,
            2,
        )

    return {
        "symbol": raw.get("symbol"),
        "name": raw.get("name"),
        "spot": spot,
        "expiry": raw.get("expiry"),
        "dte": raw.get("dte"),
        "maxPain": max_pain,
        "distance_to_max_pain_pct": distance_to_max_pain_pct,
        "atm_strike": atm.get("strike"),
        "atm_call_iv": atm.get("callIV"),
        "atm_put_iv": atm.get("putIV"),
        "atm_gamma": (atm.get("call") or {}).get("gamma"),
        "call_wall_all": {
            "strike": call_wall_all.get("strike"),
            "oi": call_wall_all.get("callOI"),
        },
        "put_wall_all": {
            "strike": put_wall_all.get("strike"),
            "oi": put_wall_all.get("putOI"),
        },
        "call_wall_near": {
            "strike": call_wall_near.get("strike"),
            "oi": call_wall_near.get("callOI"),
        },
        "put_wall_near": {
            "strike": put_wall_near.get("strike"),
            "oi": put_wall_near.get("putOI"),
        },
        "top_call_oi": [
            {
                "strike": row.get("strike"),
                "oi": row.get("callOI", 0),
            }
            for row in top_rows(rows, "callOI")
        ],
        "top_put_oi": [
            {
                "strike": row.get("strike"),
                "oi": row.get("putOI", 0),
            }
            for row in top_rows(rows, "putOI")
        ],
        "top_call_volume": [
            {
                "strike": row.get("strike"),
                "vol": row.get("callVol", 0),
            }
            for row in top_rows(rows, "callVol")
        ],
        "top_put_volume": [
            {
                "strike": row.get("strike"),
                "vol": row.get("putVol", 0),
            }
            for row in top_rows(rows, "putVol")
        ],
        "captured_at_kst": datetime.now(KST).isoformat(
            timespec="seconds"
        ),
    }


def percentage_change(old_value, new_value):
    old_number = safe_float(old_value)
    new_number = safe_float(new_value)

    if old_number in (None, 0) or new_number is None:
        return None

    return (new_number / old_number - 1) * 100


def detect_changes(old, new):
    if not old:
        return []

    alerts = []

    alert_config = CFG.get("alert", {})

    spot_move_threshold = safe_float(
        alert_config.get("spot_move_pct")
    ) or 1.0

    wall_oi_threshold = safe_float(
        alert_config.get("wall_oi_change_pct")
    ) or 20.0

    atm_iv_threshold = safe_float(
        alert_config.get("atm_iv_change_points")
    ) or 3.0

    spot_move = percentage_change(
        old.get("spot"),
        new.get("spot"),
    )

    if (
        spot_move is not None
        and abs(spot_move) >= spot_move_threshold
    ):
        alerts.append(
            f"현물 {spot_move:+.2f}%"
        )

    if old.get("maxPain") != new.get("maxPain"):
        alerts.append(
            f"맥스페인 "
            f"{old.get('maxPain')}→{new.get('maxPain')}"
        )

    wall_labels = {
        "call_wall_near": "근접 콜월",
        "put_wall_near": "근접 풋월",
    }

    for key, label in wall_labels.items():
        old_wall = old.get(key) or {}
        new_wall = new.get(key) or {}

        if old_wall.get("strike") != new_wall.get("strike"):
            alerts.append(
                f"{label} "
                f"{old_wall.get('strike')}→"
                f"{new_wall.get('strike')}"
            )

        oi_move = percentage_change(
            old_wall.get("oi"),
            new_wall.get("oi"),
        )

        if (
            oi_move is not None
            and abs(oi_move) >= wall_oi_threshold
        ):
            alerts.append(
                f"{label} OI {oi_move:+.1f}%"
            )

    iv_labels = {
        "atm_call_iv": "ATM 콜 IV",
        "atm_put_iv": "ATM 풋 IV",
    }

    for key, label in iv_labels.items():
        old_iv = safe_float(old.get(key))
        new_iv = safe_float(new.get(key))

        if old_iv is None or new_iv is None:
            continue

        iv_point_change = (new_iv - old_iv) * 100

        if abs(iv_point_change) >= atm_iv_threshold:
            alerts.append(
                f"{label} {iv_point_change:+.1f}pt"
            )

    return alerts


def send_telegram(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print(
            "Telegram Secret이 없어 메시지를 보내지 않습니다."
        )
        return

    body = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
        ) as response:
            response.read()

    except Exception as error:
        print(
            f"Telegram 전송 실패: {error}"
        )


def save_private_history(symbol, snapshot, stamp):
    latest_path = DATA_LATEST_DIR / f"{symbol}.json"

    latest_path.write_text(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    symbol_history_dir = DATA_HISTORY_DIR / symbol
    symbol_history_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    history_path = symbol_history_dir / f"{stamp}.json"

    history_path.write_text(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def make_public_snapshot(item):
    return {
        "captured_at_kst": item.get("captured_at_kst"),
        "symbol": item.get("symbol"),
        "name": item.get("name"),
        "spot": item.get("spot"),
        "expiry": item.get("expiry"),
        "dte": item.get("dte"),
        "maxPain": item.get("maxPain"),
        "distance_to_max_pain_pct": item.get(
            "distance_to_max_pain_pct"
        ),
        "atm_strike": item.get("atm_strike"),
        "atm_call_iv": item.get("atm_call_iv"),
        "atm_put_iv": item.get("atm_put_iv"),
        "atm_gamma": item.get("atm_gamma"),
        "call_wall_near": item.get("call_wall_near"),
        "put_wall_near": item.get("put_wall_near"),
        "call_wall_all": item.get("call_wall_all"),
        "put_wall_all": item.get("put_wall_all"),
        "top_call_oi": item.get("top_call_oi"),
        "top_put_oi": item.get("top_put_oi"),
        "top_call_volume": item.get(
            "top_call_volume"
        ),
        "top_put_volume": item.get(
            "top_put_volume"
        ),
    }


def publish_api(items):
    for item in items:
        symbol = item["symbol"]

        latest_path = (
            DOCS_API_LATEST_DIR / f"{symbol}.json"
        )

        latest_path.write_text(
            json.dumps(
                item,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        snapshot = make_public_snapshot(item)

        history_path = (
            DOCS_API_HISTORY_DIR / f"{symbol}.json"
        )

        if history_path.exists():
            try:
                history = json.loads(
                    history_path.read_text(
                        encoding="utf-8"
                    )
                )
            except (
                json.JSONDecodeError,
                OSError,
            ):
                history = []
        else:
            history = []

        if not isinstance(history, list):
            history = []

        current_time = snapshot.get(
            "captured_at_kst"
        )

        if (
            not history
            or history[-1].get(
                "captured_at_kst"
            )
            != current_time
        ):
            history.append(snapshot)

        history = history[-96:]

        history_path.write_text(
            json.dumps(
                history,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def format_value(value):
    if value is None:
        return "-"

    return value


def build_dashboard(items):
    cards = []

    for item in items:
        distance = item.get(
            "distance_to_max_pain_pct"
        )

        if distance is None:
            distance_text = "-"
        else:
            distance_text = f"{distance:+.2f}%"

        card = f"""
        <section>
            <h2>{item.get('symbol')}</h2>

            <p>
                <b>Spot</b>
                {format_value(item.get('spot'))}
                ·
                <b>Max Pain</b>
                {format_value(item.get('maxPain'))}
                ({distance_text})
            </p>

            <p>
                <b>근접 Call Wall</b>
                {format_value(
                    (item.get('call_wall_near') or {}).get('strike')
                )}
                /
                OI
                {format_value(
                    (item.get('call_wall_near') or {}).get('oi')
                )}
            </p>

            <p>
                <b>근접 Put Wall</b>
                {format_value(
                    (item.get('put_wall_near') or {}).get('strike')
                )}
                /
                OI
                {format_value(
                    (item.get('put_wall_near') or {}).get('oi')
                )}
            </p>

            <p>
                <b>ATM</b>
                {format_value(item.get('atm_strike'))}
                ·
                Call IV
                {format_value(item.get('atm_call_iv'))}
                ·
                Put IV
                {format_value(item.get('atm_put_iv'))}
            </p>

            <small>
                {item.get('captured_at_kst')}
            </small>
        </section>
        """

        cards.append(card)

    html = """
    <!doctype html>
    <html lang="ko">
    <head>
        <meta charset="utf-8">
        <meta
            name="viewport"
            content="width=device-width, initial-scale=1"
        >
        <title>Options Monitor</title>

        <style>
            body {
                font-family: system-ui, sans-serif;
                max-width: 900px;
                margin: 30px auto;
                padding: 0 16px;
                background: #111;
                color: #eee;
            }

            section {
                border: 1px solid #444;
                border-radius: 14px;
                padding: 18px;
                margin: 14px 0;
                background: #1b1b1b;
            }

            h1, h2 {
                margin-top: 0;
            }

            p {
                line-height: 1.6;
            }

            small {
                color: #aaa;
            }
        </style>
    </head>

    <body>
        <h1>무료 옵션 모니터</h1>
    """

    html += "".join(cards)
    html += "</body></html>"

    (DOCS_DIR / "index.html").write_text(
        html,
        encoding="utf-8",
    )


def main():
    prepare_directories()

    stamp = datetime.now(KST).strftime(
        "%Y%m%d_%H%M%S"
    )

    alerts = []
    items = []
    failures = []

    symbols = CFG.get("symbols") or []

    if not symbols:
        raise ValueError(
            "config.json의 symbols가 비어 있습니다."
        )

    api_template = CFG.get("api_template")

    if not api_template:
        raise ValueError(
            "config.json의 api_template이 없습니다."
        )

    for symbol in symbols:
        try:
            latest_path = (
                DATA_LATEST_DIR / f"{symbol}.json"
            )

            if latest_path.exists():
                try:
                    old = json.loads(
                        latest_path.read_text(
                            encoding="utf-8"
                        )
                    )
                except (
                    json.JSONDecodeError,
                    OSError,
                ):
                    old = None
            else:
                old = None

            api_url = api_template.format(
                symbol=symbol
            )

            raw = fetch_json(api_url)
            new = summarize(raw)

            save_private_history(
                symbol=symbol,
                snapshot=new,
                stamp=stamp,
            )

            symbol_changes = detect_changes(
                old,
                new,
            )

            if symbol_changes:
                alerts.append(
                    f"[{symbol}] "
                    + " | ".join(symbol_changes)
                )

            items.append(new)

        except Exception as error:
            failure_text = (
                f"{symbol} 수집 실패: {error}"
            )

            failures.append(failure_text)
            print(failure_text)

    if items:
        build_dashboard(items)
        publish_api(items)

    if alerts:
        send_telegram(
            "옵션 변화 감지\n"
            + "\n".join(alerts)
        )

    if failures:
        send_telegram(
            "옵션 모니터 오류\n"
            + "\n".join(failures)
        )

    result = {
        "updated": [
            item["symbol"]
            for item in items
        ],
        "alerts": alerts,
        "failures": failures,
    }

    print(
        json.dumps(
            result,
            ensure_ascii=False,
        )
    )

    if failures and not items:
        raise RuntimeError(
            "모든 종목 수집에 실패했습니다."
        )


if __name__ == "__main__":
    main()
