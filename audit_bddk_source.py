"""Independent source audit for the checked-in dashboard snapshot."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener
import json

from bs4 import BeautifulSoup

URL = "https://www.bddk.gov.tr/BultenHaftalik/tr/Gelismis"
ITEMS = [
    (["5698"], ["Ticari ve Diğer Krediler"]),
    (["5730", "5734", "5735", "5736"], ["Mevduat (Katılım Fonu) (2+5+8)", "Ticari Kuruluşlar (6+7)", "a) Vadesiz", "b) Vadeli"]),
]
state = json.loads(Path("archive/treasury.json").read_text())
last = state["latest"]
previous = state["periods"][-2]
friday = date.fromisoformat(last) + timedelta(days=4-date.fromisoformat(last).weekday())
by_week = {}
for day in state["periods"]:
    parsed = date.fromisoformat(day)
    by_week[(parsed + timedelta(days=4-parsed.weekday())).isoformat()] = day
start13 = by_week[(friday-timedelta(weeks=13)).isoformat()]
start52 = by_week[(friday-timedelta(weeks=52)).isoformat()]
year_end = ["2025-12-26", "2026-01-02"]
windows = [[start52, start52], [year_end[0], last]]


def client():
    return build_opener(HTTPCookieProcessor(CookieJar()))


def html(opener, url, fields=None):
    request = Request(url, data=urlencode(fields).encode() if fields else None,
                      headers={"Referer": URL, "User-Agent": "Treasury-Independent-Audit/1.0"})
    with opener.open(request, timeout=45) as response:
        return BeautifulSoup(response.read(), "lxml")


def parse_day(value):
    return datetime.strptime(value.split()[0], "%d.%m.%Y").date().isoformat()


def get_window(job):
    (ids, names), (first, final) = job
    opener = client()
    form = html(opener, URL)
    available = {parse_day(o["value"]): o["value"] for o in form.select("#bitisTarih option[value]")
                 if o["value"].strip()}
    token = form.select_one('input[name="__RequestVerificationToken"]')["value"]
    fields = [("__RequestVerificationToken", token), ("BaslangicTarihi", available[first]),
              ("BitisTarihi", available[final]), ("dil", "tr"), ("SeciliParalar", "TL"),
              ("Taraflar", "10001"), *(("Kalemler", item) for item in ids),
              ("kalemSutun", "TP"), ("kalemSutun", "YP"), ("kalemSutun", "Toplam")]
    table = html(opener, URL + "/GelismisRaporGetir", fields).select_one("#TabloExcelGelismis2")
    headings = [" ".join(p.stripped_strings).split(" / ", 1)[-1] for p in table.select("thead th p")]
    assert headings == names, headings
    columns = [" ".join(x.stripped_strings).upper() for x in table.select("thead tr")[-1].select("th")]
    assert [x for x in columns if x] == ["TP", "YP", "TOPLAM"] * len(ids), columns
    assert any("Sektör" in row.get_text() for row in table.select("tbody tr") if len(row.select("td")) == 1)
    values = {}
    for row in table.select("tbody tr"):
        cells = [c.get_text(strip=True) for c in row.find_all("td", recursive=False)]
        if len(cells) == 1:
            continue
        assert len(cells) == 1 + 3*len(ids), cells
        values[parse_day(cells[0])] = {
            (item, c): Decimal(raw.replace(".", "").replace(",", "."))
            for i, item in enumerate(ids) for j, c in enumerate(["TP", "YP"])
            if (raw := cells[1+3*i+j]) not in {"", "-", "–", "—"}
        }
    return max(available), values


with ThreadPoolExecutor(max_workers=3) as pool:
    results = list(pool.map(get_window, [(items, window) for window in windows for items in ITEMS]))
raw = {}
source_latest = set()
for newest, observations in results:
    source_latest.add(newest)
    for day, values in observations.items():
        raw.setdefault(day, {}).update(values)
print("FRESHNESS", json.dumps({"dashboard": last, "BDDK": sorted(source_latest), "dashboardPublication": state["publication"]}))
issues = []
checks = 0
for day in [start52, *year_end, start13, previous, last]:
    for column in ("TP", "YP"):
        for item, group in (("5698", "289"), ("5734", "292")):
            v = state["points"][f"{group}:{item}:10001:TL:{column}"].get(day)
            checks += 1
            if v is None or Decimal(str(v)) != raw[day][item,column]:
                issues.append([day, item, column, v, str(raw[day][item,column])])
        for index, item in enumerate(("5735", "5736")):
            v = state["depositHistory"][column][day][index]
            checks += 1
            if v is None or Decimal(str(v)) != raw[day][item,column]:
                issues.append([day, item, column, v, str(raw[day][item,column])])
        if day in (previous, last):
            context = state["depositContext"][column]
            v = context["total"][context["dates"].index(day)]
            checks += 1
            if v is None or Decimal(str(v)) != raw[day]["5730",column]:
                issues.append([day, "5730", column, v, str(raw[day]["5730",column])])
print("RAW CHECKS", checks, "MISMATCHES", json.dumps(issues))


def metric(item, column, first, final):
    a, b = (raw[d][item, column] for d in (first, final))
    return [str(a), str(b), str((b-a)/1000), str((b/a-1)*100)]

scenarios = {"weekly": [previous,last], "13": [start13,last], "52": [start52,last], "custom": year_end}
expected = {}
for scenario, (a,b) in scenarios.items():
    expected[scenario] = {"dates": [a,b], "series": [metric(item, c, a,b) for item in ["5698","5734"] for c in ["TP","YP"]],
                          "split": [[metric(item,c,a,b)[2] for item in ["5736","5735"]] for c in ["TP","YP"]],
                          "sector": [metric("5730",c,a,b)[3] for c in ["TP","YP"]]}
    print("DIRECT", scenario, json.dumps(expected[scenario]))
Path("audit-expected.json").write_text(json.dumps(expected))
if issues or source_latest != {last}:
    raise SystemExit("Source differences detected")
