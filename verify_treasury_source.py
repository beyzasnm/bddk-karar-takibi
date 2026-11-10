"""Probe the existing BDDK collector for the Treasury dashboard."""
from http.cookiejar import CookieJar
from urllib.request import HTTPCookieProcessor, build_opener

from collect_weekly import SOURCE, discover, report, request

ITEMS = {"289": "5698", "292": "5734"}
CROSS_YEAR = ["2025-12-26", "2026-01-02"]
KNOWN_CREDIT = {"TP": 11494953.63384, "YP": 10452577.4352}


def main():
    cookies = CookieJar()
    client = build_opener(HTTPCookieProcessor(cookies))
    dates, token, catalogue = discover(request(client, SOURCE))
    calendar = sorted(dates)
    for day in CROSS_YEAR:
        if day not in dates:
            raise ValueError(f"Yıl geçişi dönemi katalogda yok: {day}")
    intervals = [[calendar[0]], CROSS_YEAR, calendar[-2:]]
    for group, label, entries in catalogue:
        if group not in ITEMS:
            continue
        items = [entry for entry in entries if entry[0] == ITEMS[group] and not entry[2]]
        if len(items) != 1:
            raise ValueError(f"BDDK kalemi eşleşmedi: {label}")
        for interval in intervals:
            series = report(list(cookies), token, dates, group, items, interval, "TL")
            for entry in series:
                currency = entry["currency"]
                if currency not in ("TP", "YP"):
                    continue
                points = dict(entry["points"])
                if list(points) != interval:
                    raise ValueError(f"Eksik gözlem: {entry['key']} {interval}")
                if group == "289" and "2026-10-30" in points:
                    if abs(points["2026-10-30"] - KNOWN_CREDIT[currency]) > 0.00001:
                        raise ValueError(f"30 Ekim temel gösterimden farklı: {currency}")
                print(label, entry["name"], entry["bank"], currency, entry["unit"], points)


if __name__ == "__main__":
    main()
