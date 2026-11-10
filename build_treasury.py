"""Build the Treasury dashboard using the existing BDDK advanced-report client."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.request import HTTPCookieProcessor, build_opener
from zoneinfo import ZoneInfo
import json
from math import isclose
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


def record_observation(points, revisions, key, day, new, now):
    observations = points[key]
    if day in observations and observations[day] != new:
        revisions.append({"id": key, "date": day, "old": observations[day], "new": new, "detectedAt": now})
    observations[day] = new


DEPOSIT_GROUP = "292"
COMMERCIAL_ITEM = "5734"
DEPOSIT_ITEMS = {"total": "5730", "demand": "5735", "term": "5736"}


def deposit_context(cookies, token, dates, catalogue, interval, points):
    catalogue_items = next(items for key, _, items in catalogue if key == DEPOSIT_GROUP)
    by_id = {entry[0]: entry for entry in catalogue_items if not entry[2]}
    requested = [by_id[item] for item in DEPOSIT_ITEMS.values() if item in by_id]
    if not requested or len(interval) != 2:
        return {}
    fetched = report(list(cookies), token, dates, DEPOSIT_GROUP, requested, interval, "TL")
    by_key = {series["key"]: dict(series["points"]) for series in fetched}
    result = {}
    for column in ("TP", "YP"):
        def pair(item):
            values = by_key.get(f"{DEPOSIT_GROUP}:{item}:10001:TL:{column}", {})
            return [values.get(day) for day in interval]

        demand, term = pair(DEPOSIT_ITEMS["demand"]), pair(DEPOSIT_ITEMS["term"])
        commercial = points[f"{DEPOSIT_GROUP}:{COMMERCIAL_ITEM}:10001:TL:{column}"]
        reconciles = all(a is not None and b is not None and commercial.get(day) is not None
                         and isclose(a + b, commercial[day], rel_tol=0, abs_tol=0.00002)
                         for day, a, b in zip(interval, demand, term, strict=True))
        result[column] = {"dates": interval, "total": pair(DEPOSIT_ITEMS["total"]),
                          "demand": demand if reconciles else None,
                          "term": term if reconciles else None}
    return result


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
    verified_by_group = {group: set() for group in selected}
    failed_windows = set()
    with ThreadPoolExecutor(max_workers=3) as pool:
        def fetch(task):
            group, items, interval = task
            try:
                return group, interval, report(list(cookies), token, dates, group, items, interval, "TL"), None
            except (OSError, ValueError) as error:
                return group, interval, [], error

        for group, interval, values, error in pool.map(fetch, tasks):
            if error:
                if interval == periods[-13:]:
                    raise ValueError(f"Son 13 hafta alınamadı: {error}") from error
                failures.append(f"{interval[0]}–{interval[-1]}")
                failed_windows.add(interval[0])
                print(f"::warning::{interval[0]}–{interval[-1]}: {error}")
                continue
            verified_by_group[group].update(interval)
            for item in values:
                key = item["key"]
                if key not in points:
                    continue
                incoming = dict(item["points"])
                for day in interval:
                    new = incoming.get(day)
                    if day == last and new is None:
                        raise ValueError(f"Son dönem için boş kalem: {item['name']} {item['currency']}")
                    record_observation(points, revisions, key, day, new, now)
    windows_checked = dict(checked)
    for interval in targets:
        if interval[0] not in failed_windows:
            windows_checked[interval[0] + "/" + interval[-1]] = now
    verified_now = set.intersection(*verified_by_group.values())
    prior_week = (date.fromisoformat(week(last)) - timedelta(days=7)).isoformat()
    prior_day = next((day for day in reversed(periods[-13:]) if week(day) == prior_week), None)
    context = {}
    if prior_day:
        try:
            context = deposit_context(cookies, token, dates, catalogue, [prior_day, last], points)
        except (OSError, ValueError, StopIteration) as error:
            print(f"::warning::Ek mevduat bilgisi alınamadı: {error}")
    return {"depositContext": context, "latest": last, "publication": publications.get(week(last)), "checked": now,
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
