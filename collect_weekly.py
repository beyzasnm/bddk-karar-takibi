"""Import the weekly BDDK advanced report and build the dashboard snapshot."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
import gzip
import json
import re
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from bs4 import BeautifulSoup

SOURCE = "https://www.bddk.org.tr/BultenHaftalik/tr/Gelismis"
ARCHIVE = Path("archive/weekly.json.gz")
MAX_RESPONSE = 32_000_000
FEATURED = {"5687", "5694", "5709"}
SPLIT = ("TP", "YP", "TOPLAM")


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def text(tag):
    return " ".join(tag.get_text(" ", strip=True).split())


def period(value):
    return datetime.strptime(value.split()[0], "%d.%m.%Y").date().isoformat()


def request(opener, url, fields=None):
    headers = {"User-Agent": "BDDK-Veri-Arsivi/1.0", "Referer": SOURCE}
    body = None if fields is None else urlencode(fields).encode()
    with opener.open(Request(url, data=body, headers=headers), timeout=65) as response:
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError("BDDK yanıtı boyut sınırını aştı")
    return BeautifulSoup(raw.decode("utf-8-sig"), "lxml")


def discover(page):
    dates = {}
    for entry in page.select("#bitisTarih option[value]"):
        value = entry["value"]
        if value.strip():
            dates[period(value)] = value
    token = page.select_one('input[name="__RequestVerificationToken"]')
    groups = []
    for label in page.select('[onclick^="KalemleriGoster("]'):
        key = re.fullmatch(r"KalemleriGoster\((\d+)\)", label["onclick"])[1]
        items = []
        for item in page.select(f'#Kalemler-{key} [id^="Kalem-"]'):
            match = re.match(r"KalemToggle\((\d+),\s*'(.*)'\)", item["onclick"])
            if not match:
                raise ValueError("Bülten kalem kimliği okunamadı")
            visible = text(item)
            items.append((match[1], " ".join(match[2].split()), "Sonlandırılma Tarihi" in visible))
        if not items:
            raise ValueError(f"{text(label)} tablosu boş")
        groups.append((key, text(label), items))
    if len(groups) != 9 or len(dates) < 50 or not token:
        raise ValueError("Haftalık bülten kataloğu eksik")
    return dates, token["value"], groups


def numeric(raw):
    raw = raw.replace("\u2212", "-")
    if raw in {"", "-", "--", "—", "–", "..."}:
        return None
    if not re.fullmatch(r"[+-]?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?", raw):
        raise ValueError(f"Beklenmeyen BDDK sayı biçimi: {raw!r}")
    return float(raw.replace(".", "").replace(",", "."))


def extract(page, group, items, expected, denomination):
    table = page.select_one("#TabloExcelGelismis2")
    if table is None:
        raise ValueError("BDDK hassas değer tablosunu döndürmedi")
    headings = [text(p).split(" / ", 1)[-1] for p in table.select("thead th p")]
    item_names = [name for _, name, _ in items]
    if headings != item_names:
        raise ValueError(f"BDDK başlıkları seçilen kalemlerle eşleşmedi: {headings!r} != {item_names!r}")
    columns = [text(th).upper() for th in table.select("thead tr")[-1].find_all("th") if text(th)]
    if tuple(columns) != SPLIT * len(items):
        raise ValueError(f"Beklenmeyen sütun düzeni: {columns!r}")
    rows = {}
    bank = None
    for row in table.select("tbody tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) == 1 and cells[0].has_attr("colspan"):
            bank = text(cells[0])
            continue
        if len(cells) != 1 + len(columns) or bank != "Sektör":
            raise ValueError("BDDK tablo satırı veya banka grubu eşleşmedi")
        day = period(text(cells[0]))
        if day in rows or day not in expected:
            raise ValueError(f"Yinelenen veya istenmeyen dönem: {day}")
        rows[day] = [numeric(text(cell)) for cell in cells[1:]]
    if set(rows) != expected:
        raise ValueError(f"BDDK {len(expected)} dönemden {len(rows)} dönem döndürdü")
    series = []
    for index, ((item, name, ended), column) in enumerate(
            (item, column) for item in items for column in SPLIT):
        points = [[day, values[index]] for day, values in sorted(rows.items()) if values[index] is not None]
        series.append({"key": f"{group}:{item}:10001:{denomination}:{column}", "name": name,
                       "bank": "Sektör", "currency": column, "unit": f"milyon {denomination}",
                       "ended": ended, "featured": denomination == "TL" and column == "TOPLAM"
                       and (item in FEATURED or (group in {"292", "294", "297"} and index == 2)),
                       "points": points})
    return series


def report(cookies, token, dates, group, items, interval, denomination):
    jar = CookieJar()
    for cookie in cookies:
        jar.set_cookie(cookie)
    opener = build_opener(HTTPCookieProcessor(jar))
    fields = [
        ("__RequestVerificationToken", token), ("BaslangicTarihi", dates[interval[0]]),
        ("BitisTarihi", dates[interval[-1]]), ("dil", "tr"), ("SeciliParalar", denomination),
        ("Taraflar", "10001"), *(("Kalemler", item[0]) for item in items),
        ("kalemSutun", "TP"), ("kalemSutun", "YP"), ("kalemSutun", "Toplam"),
    ]
    page = request(opener, SOURCE + "/GelismisRaporGetir", fields)
    return extract(page, group, items, set(interval), denomination)


def merge(previous, updates):
    old = {s["key"]: s for g in previous.get("groups", []) for s in g["series"]}
    for group in updates:
        for series in group["series"]:
            points = dict(old.get(series["key"], {}).get("points", []))
            for day in group["interval"]:
                points.pop(day, None)
            points.update(series["points"])
            series["points"] = sorted(points.items())
    return updates


def save(archive):
    ARCHIVE.parent.mkdir(exist_ok=True)
    raw = json.dumps(archive, ensure_ascii=False, separators=(",", ":")).encode()
    temporary = ARCHIVE.with_suffix(".tmp")
    temporary.write_bytes(gzip.compress(raw, mtime=0))
    temporary.replace(ARCHIVE)


def update(previous, force_history):
    cookies = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookies))
    dates, token, catalogue = discover(request(opener, SOURCE))
    calendar = sorted(dates)
    print(f"Resmî takvim: {calendar[0]} – {calendar[-1]} ({len(calendar)} dönem)", flush=True)
    if previous.get("calendar") == calendar and not force_history:
        return {**previous, "checked_at": stamp()}
    full = not previous or force_history or not set(previous["calendar"]) <= set(calendar)
    selected = calendar if full else [day for day in calendar if day >= previous["calendar"][-13]]
    tasks = []
    for key, _, items in catalogue:
        for offset in range(0, len(items), 16):
            batch = items[offset:offset + 16]
            for denomination in ("TL", "USD"):
                tasks.append((key, batch, denomination))
    by_group = defaultdict(list)
    def collect(task):
        key, items, denomination = task
        try:
            return key, report(list(cookies), token, dates, key, items, selected, denomination)
        except (OSError, ValueError) as error:
            if len(selected) <= 105:
                raise
            print(f"{key} / {denomination}: uzun dönem parçalanıyor ({error})", flush=True)
            combined = {}
            for offset in range(0, len(selected), 104):
                for series in report(list(cookies), token, dates, key, items,
                                     selected[offset:offset + 104], denomination):
                    if series["key"] in combined:
                        combined[series["key"]]["points"].extend(series["points"])
                    else:
                        combined[series["key"]] = series
            return key, list(combined.values())
    with ThreadPoolExecutor(max_workers=3) as pool:
        for key, result in pool.map(collect, tasks):
            by_group[key].extend(result)
            print(f"{key}: {len(result)} seri, {sum(len(s['points']) for s in result)} gözlem", flush=True)
    groups = [{"id": key, "name": name, "series": by_group[key], "interval": selected}
              for key, name, _ in catalogue]
    merge({} if full else previous, groups)
    for group in groups:
        del group["interval"]
    return {"calendar": calendar, "checked_at": stamp(), "groups": groups}


def build(archive, warning):
    calendar = archive["calendar"]
    payload = {**archive, "warning": warning,
               "coverage": f"Haftalık bülten · Sektör · {calendar[0]} – {calendar[-1]} · {len(calendar)} dönem"}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    html = Path("dashboard.html").read_text(encoding="utf-8")
    library = Path("node_modules/exceljs/dist/exceljs.min.js").read_text(encoding="utf-8")
    html = html.replace("__SNAPSHOT__", raw).replace("__EXCEL_LIBRARY__", library)
    out = Path("dist")
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    for group in archive["groups"]:
        valid = sum(bool(series["points"]) for series in group["series"])
        print(f"{group['name']}: {valid} dolu seri", flush=True)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    previous = json.loads(gzip.decompress(ARCHIVE.read_bytes())) if ARCHIVE.exists() else {}
    warning = None
    try:
        archive = update(previous, args.full)
    except (OSError, ValueError) as error:
        if not previous:
            raise
        archive = previous
        warning = f"Son kontrol başarısız. Önceki arşiv gösteriliyor. {error}"
        print(f"::warning::{warning}")
    if archive != previous:
        save(archive)
    build(archive, warning)


if __name__ == "__main__":
    main()
