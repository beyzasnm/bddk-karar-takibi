"""Collect sector-level time series from the BDDK weekly bulletin."""
import datetime as dt
from html.parser import HTMLParser
from http.cookiejar import CookieJar
import json
import math
import re
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

SOURCE = "https://www.bddk.org.tr/bultenhaftalik"
API = "https://www.bddk.org.tr/BultenHaftalik/tr/Home/KiyaslamaJsonGetir"
SERIES = (
    ("loans", "Toplam krediler", "1.0.1", "3"),
    ("deposits", "Toplam mevduat ve katılım fonu", "4.0.1", "3"),
    ("npl", "Takipteki alacaklar", "2.0.1", "3"),
    ("deposits_tp", "TL mevduat ve katılım fonu", "4.0.1", "1"),
    ("deposits_yp", "YP mevduat ve katılım fonu (TL karşılığı)", "4.0.1", "2"),
    ("cards", "Bireysel kredi kartları", "1.0.8", "3"),
)


class VerificationToken(HTMLParser):
    value = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name") == "__RequestVerificationToken":
            self.value = attrs.get("value", "")


def read(opener, request):
    with opener.open(request, timeout=12) as response:
        return response.read(2_000_000).decode(
            response.headers.get_content_charset() or "utf-8-sig")


def observation_date(value):
    if not isinstance(value, str):
        raise ValueError("Beklenmeyen tarih biçimi")
    for pattern in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(value.strip(), pattern).date().isoformat()
        except ValueError:
            continue
    raise ValueError("Beklenmeyen tarih biçimi")


def observations(payload, period):
    dates, values = payload.get("XEkseni"), payload.get("YEkseni")
    if not isinstance(dates, list) or not isinstance(values, list) or len(dates) != len(values):
        raise ValueError("Tarih ve değer dizileri eşleşmiyor")
    result = {}
    for date, value in zip(dates, values):
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError("Beklenmeyen değer biçimi")
        day, amount = observation_date(date), float(value)
        if not math.isfinite(amount) or amount < 0 or day in result:
            raise ValueError("Geçersiz gözlem")
        result[day] = amount
    if len(result) < 2 or max(result) != period:
        raise ValueError("Serinin son dönemi bültenle eşleşmiyor")
    return result


def collect(db, now):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS weekly_status (
            id TEXT PRIMARY KEY, attempt TEXT, success TEXT, error TEXT
        );
        CREATE TABLE IF NOT EXISTS weekly_observation (
            id TEXT, date TEXT, value REAL NOT NULL, PRIMARY KEY (id, date)
        );
    """)
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    headers = {"User-Agent": "BDDK-Veri-Takibi/1.0"}
    try:
        page = read(opener, Request(SOURCE, headers=headers))
        token = VerificationToken()
        token.feed(page)
        match = re.search(r"""["']tarih["']\s*:\s*["'](\d{1,2}\.\d{1,2}\.\d{4})["']""", page)
        if not match:
            raise ValueError("Bültenin dönem tarihi bulunamadı")
        date = match.group(1)
        period = observation_date(date)
        page_error = None
    except (OSError, ValueError) as error:
        page_error = str(error)

    all_ok = True
    for key, _, metric, column in SERIES:
        attempt = now()
        try:
            if page_error is not None:
                raise ValueError(page_error)
            fields = {"dil": "tr", "tarih": date, "id": metric, "parabirimi": "TRY",
                      "sutun": column, "tarafKodu": "10001", "gun": "365"}
            if token.value:
                fields["__RequestVerificationToken"] = token.value
            request = Request(API, data=urlencode(fields).encode(), headers={
                **headers, "Referer": SOURCE, "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            })
            payload = json.loads(read(opener, request))
            if not isinstance(payload, dict):
                raise ValueError("Bülten yanıtı bir veri nesnesi değil")
            points = observations(payload, period)
            with db:
                latest = db.execute("SELECT max(date) FROM weekly_observation WHERE id=?",
                                    (key,)).fetchone()[0]
                if latest and period < latest:
                    raise ValueError("Kaynak önceki bir döneme geri döndü")
                db.executemany("""INSERT INTO weekly_observation VALUES (?, ?, ?)
                                  ON CONFLICT(id,date) DO UPDATE SET value=excluded.value""",
                               ((key, day, value) for day, value in points.items()))
                db.execute("""INSERT INTO weekly_status VALUES (?, ?, ?, NULL)
                              ON CONFLICT(id) DO UPDATE SET attempt=excluded.attempt,
                              success=excluded.success, error=NULL""", (key, attempt, now()))
        except (OSError, ValueError, OverflowError) as error:
            all_ok = False
            with db:
                db.execute("""INSERT INTO weekly_status VALUES (?, ?, NULL, ?)
                              ON CONFLICT(id) DO UPDATE SET attempt=excluded.attempt,
                              error=excluded.error""", (key, attempt, str(error)))
    return all_ok


def export(db):
    statuses = {row["id"]: dict(row) for row in db.execute("SELECT * FROM weekly_status")}
    series = []
    for key, label, _, _ in SERIES:
        points = db.execute("""SELECT date, value FROM weekly_observation WHERE id=?
                              ORDER BY date DESC LIMIT 54""", (key,)).fetchall()
        series.append({"id": key, "label": label, "status": statuses.get(key, {}),
                       "points": [dict(point) for point in reversed(points)]})
    return {"source": SOURCE, "unit": "milyon TL", "series": series}
