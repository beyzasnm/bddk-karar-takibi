"""Build the Treasury dashboard using the existing BDDK advanced-report client."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.request import HTTPCookieProcessor, build_opener
from zoneinfo import ZoneInfo
import json
import re

from collect_weekly import SOURCE, discover, report, request, stamp

CALENDAR = "https://www.bddk.org.tr/Veri/Detay/71"
STATE = Path("archive/treasury.json")
OUTPUT = Path("dist/treasury/index.html")
SERIES = [
    {"table": "Krediler", "group": "289", "item": "5698", "name": "Ticari ve Diğer Krediler", "column": "TP", "title": "TL Ticari ve Diğer Krediler", "reason": "Sektörün TL cinsi ticari ve diğer kredi bakiyesini izler."},
    {"table": "Krediler", "group": "289", "item": "5698", "name": "Ticari ve Diğer Krediler", "column": "YP", "title": "YP Ticari ve Diğer Krediler", "reason": "Yabancı para kredi bakiyesini TL karşılığıyla izler."},
    {"table": "Mevduat", "group": "292", "item": "5734", "name": "Ticari Kuruluşlar (6+7)", "column": "TP", "title": "TL Ticari Kuruluşlar Mevduatı", "reason": "Ticari kuruluşların vadeli ve vadesiz TL bakiyesini izler. Toplam mevduatın alt kalemidir."},
    {"table": "Mevduat", "group": "292", "item": "5734", "name": "Ticari Kuruluşlar (6+7)", "column": "YP", "title": "YP Ticari Kuruluşlar Mevduatı", "reason": "Ticari kuruluşların vadeli ve vadesiz YP bakiyesini TL karşılığıyla izler. Toplam mevduatın alt kalemidir."},
]
for series in SERIES:
    series.update(id=f"{series['group']}:{series['item']}:10001:TL:{series['column']}",
                  unit="milyon TL", scope="Sektör", source=SOURCE)

# The metadata specifies April 2022. Treat the entire month as a transition.
TRANSITION = ["2022-04-01", "2022-04-30"]


def read_publication_calendar(client):
    rows = request(client, CALENDAR).select("tr")
    result = {}
    for row in rows:
        cells = [" ".join(td.stripped_strings) for td in row.select("td")]
        if len(cells) < 3 or "Haftalık Bankacılık Sektörü Verileri" not in cells[0]:
            continue
        period = re.fullmatch(r"(\d+)\.\s*Hafta\s+(\d{4})", cells[1])
        if not period:
            continue
        try:
            friday = date.fromisocalendar(int(period[2]), int(period[1]), 5).isoformat()
            published = datetime.strptime(cells[2], "%d.%m.%Y %H:%M")
        except ValueError:
            continue
        result[friday] = published.replace(tzinfo=ZoneInfo("Europe/Istanbul")).isoformat()
    if not result:
        raise ValueError("BDDK haftalık yayımlama takvimi okunamadı")
    return result


def week(day):
    value = date.fromisoformat(day)
    return (value + timedelta(days=4 - value.weekday())).isoformat()


def refresh(previous):
    cookies = CookieJar()
    client = build_opener(HTTPCookieProcessor(cookies))
    dates, token, catalogue = discover(request(client, SOURCE))
    periods = sorted(dates)
    publications = read_publication_calendar(client)
    now = stamp()
    due = [day for day, value in publications.items()
           if datetime.fromisoformat(value) <= datetime.fromisoformat(now)]
    expected = max(due, default=None)
    last = periods[-1]
    if expected and week(last) < expected:
        raise ValueError(f"{expected} haftası takvimde vadesi gelmiş olmasına rağmen kaynakta eksik")
    selected = {}
    for config in SERIES:
        group = config["group"]
        entries = next(items for key, _, items in catalogue if key == group)
        selected[group] = list({entry[0]: entry for entry in
                                [*selected.get(group, []), *(x for x in entries if x[0] == config["item"] and not x[2])]}.values())
        if not any(entry[0] == config["item"] for entry in selected[group]):
            raise ValueError(f"BDDK kalemi bulunamadı: {config['name']}")

    points = {s["id"]: dict(previous.get("points", {}).get(s["id"], {})) for s in SERIES}
    checked = previous.get("windows", {})
    history = periods[:-13]
    windows = [history[i:i + 52] for i in range(0, len(history), 52)]
    targets = sorted(windows, key=lambda window: checked.get(window[0] + "/" + window[-1], ""))
    # Load the full archive on the first run. Recheck the oldest verified window each time.
    targets = targets if not previous.get("latest") else targets[:2]
    intervals = [periods[-13:], *targets]
    tasks = [(group, items, interval) for interval in intervals for group, items in selected.items()]
    revisions = list(previous.get("revisions", []))
    failures = []
    verified_now = set()
    failed_windows = set()
    with ThreadPoolExecutor(max_workers=3) as pool:
        def fetch(task):
            group, items, interval = task
            try:
                return interval, report(list(cookies), token, dates, group, items, interval, "TL"), None
            except (OSError, ValueError) as error:
                return interval, [], error

        for interval, values, error in pool.map(fetch, tasks):
            if error:
                if interval == periods[-13:]:
                    raise ValueError(f"Son 13 hafta alınamadı: {error}") from error
                failures.append(f"{interval[0]}–{interval[-1]}")
                failed_windows.add(interval[0])
                print(f"::warning::{interval[0]}–{interval[-1]}: {error}")
                continue
            verified_now.update(interval)
            for item in values:
                key = item["key"]
                if key not in points:
                    continue
                incoming = dict(item["points"])
                for day in interval:
                    old = points[key].get(day)
                    new = incoming.get(day)
                    if day == last and new is None:
                        raise ValueError(f"Son dönem için boş kalem: {item['name']} {item['currency']}")
                    if day in previous.get("verified", []) and old != new:
                        revisions.append({"id": key, "date": day, "old": old, "new": new, "detectedAt": now})
                    points[key][day] = new
    windows_checked = dict(checked)
    for interval in targets:
        if interval[0] not in failed_windows:
            windows_checked[interval[0] + "/" + interval[-1]] = now
    return {"latest": last, "publication": publications.get(week(last)), "checked": now,
            "attempted": now, "points": points, "periods": periods,
            "windows": windows_checked, "revisions": revisions,
            "verified": sorted(set(previous.get("verified", [])) | verified_now),
            "historyWarning": ", ".join(sorted(set(failures))), "error": None}


def render(state):
    payload = {**state, "series": SERIES, "transition": TRANSITION}
    html = Path("treasury.html").read_text(encoding="utf-8")
    snapshot = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(html.replace("__TREASURY_DATA__", snapshot), encoding="utf-8")


def main():
    previous = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    try:
        state = refresh(previous)
    except (OSError, ValueError, StopIteration) as error:
        print(f"::warning::{error}")
        if not previous:
            raise
        state = {**previous, "attempted": stamp(), "error": str(error)}
    STATE.parent.mkdir(exist_ok=True)
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(STATE)
    render(state)
    print(f"BDDK: {state['latest']} | {len(state['verified'])} doğrulanmış dönem | {len(state['revisions'])} revizyon")


if __name__ == "__main__":
    main()
