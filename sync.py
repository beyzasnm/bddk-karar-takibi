import datetime as dt
from contextlib import closing
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
SOURCES = {
    "Resm� Gazete'de yayimlanan": "https://www.bddk.org.tr/Mevzuat/Liste/55",
    "Resm� Gazete'de yayimlanmayan": "https://www.bddk.org.tr/Mevzuat/Liste/56",
}
TITLE = re.compile(r"^\(\s*(\d{1,2}\.\d{1,2}\.\d{4})\s*[---]\s*(\d+)\s*\)\s*(.+)$")
HOSTS = {"www.bddk.org.tr", "bddk.org.tr", "www.bddk.gov.tr", "bddk.gov.tr"}
LIMIT = 20 * 1024 * 1024


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def official(url):
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname in HOSTS


def fetch(url):
    if not official(url):
        raise ValueError("Resm� BDDK adresi bekleniyordu")
    request = Request(url, headers={"User-Agent": "BDDK-Karar-Takibi/1.0"})
    with urlopen(request, timeout=15) as response:
        if not official(response.url):
            raise ValueError("Beklenmeyen y�nlendirme")
        content = response.read(LIMIT + 1)
        if len(content) > LIMIT:
            raise ValueError("Yanit boyut sinirini asti")
        return content, response.headers.get_content_charset() or "utf-8"


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.href = None
        self.label = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.label = []

    def handle_data(self, data):
        if self.href is not None:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            self.links.append((self.href, " ".join("".join(self.label).split())))
            self.href = None


def decisions(page, base):
    parser = Links()
    parser.feed(page)
    rows = {}
    for href, label in parser.links:
        match = TITLE.fullmatch(label)
        url = urljoin(base, href)
        if not match or not official(url):
            continue
        date, number, title = match.groups()
        date = dt.datetime.strptime(date, "%d.%m.%Y").date().isoformat()
        rows[number] = (number, date, title, url)
    if not rows:
        raise ValueError("Sayfada karar bulunamadi")
    return sorted(rows.values(), key=lambda row: (row[1], int(row[0])), reverse=True)


def scan(db, source, url):
    stamp = now()
    try:
        raw, charset = fetch(url)
        rows = decisions(raw.decode(charset), url)
    except (OSError, ValueError, LookupError) as error:
        with db:
            db.execute("""INSERT INTO source VALUES (?, ?, NULL, ?)
                          ON CONFLICT(name) DO UPDATE SET attempt=excluded.attempt,
                          error=excluded.error""", (source, stamp, str(error)))
        return False

    with db:
        initial = db.execute("SELECT 1 FROM source WHERE name=? AND success IS NOT NULL",
                             (source,)).fetchone() is None
        for index, (number, date, title, link) in enumerate(rows):
            active = int(not initial or index < 10)
            db.execute("""INSERT INTO decision (number, date, title, url, source, first_seen,
                                               last_seen, active)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                          ON CONFLICT(source, number) DO UPDATE SET
                          title=excluded.title, date=excluded.date,
                          pdf=CASE WHEN decision.url=excluded.url THEN decision.pdf END,
                          url=excluded.url, last_seen=excluded.last_seen""",
                       (number, date, title, link, source, stamp, stamp, active))
        db.execute("""INSERT INTO source VALUES (?, ?, ?, NULL)
                      ON CONFLICT(name) DO UPDATE SET attempt=excluded.attempt,
                      success=excluded.success, error=NULL""", (source, stamp, now()))
    return True


def download(db):
    pending = db.execute("""SELECT source, number, url FROM decision
                            WHERE active=1 AND pdf IS NULL
                            ORDER BY COALESCE(pdf_attempt, ''), date DESC, number DESC
                            LIMIT 30""").fetchall()
    for row in pending:
        try:
            content, _ = fetch(row["url"])
            if not content.startswith(b"%PDF-"):
                raise ValueError("Baglanti PDF d�nd�rmedi")
            error = None
        except (OSError, ValueError) as exc:
            content, error = None, str(exc)
        with db:
            db.execute("""UPDATE decision SET pdf=?, pdf_attempt=?, pdf_error=?
                          WHERE source=? AND number=?""",
                       (content, now(), error, row["source"], row["number"]))


def render(db):
    statuses = {row["name"]: dict(row) for row in db.execute("SELECT * FROM source")}
    rows = db.execute("""SELECT number, date, title, url, source, first_seen, last_seen,
                                 publication_date, pdf IS NOT NULL AS archived, pdf_error
                          FROM decision WHERE active=1
                          ORDER BY date DESC, CAST(number AS INTEGER) DESC""").fetchall()
    payload = {"sources": statuses, "decisions": [dict(row) for row in rows]}
    output = ROOT / "site"
    output.mkdir(exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    template = (ROOT / "dashboard.html").read_text(encoding="utf-8")
    (output / "index.html").write_text(template.replace("__DATA__", data), encoding="utf-8")
    (output / "decisions.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                           encoding="utf-8")


def main():
    with closing(sqlite3.connect(ROOT / "bddk.sqlite3")) as db:
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE IF NOT EXISTS source (
                name TEXT PRIMARY KEY, attempt TEXT, success TEXT, error TEXT
            );
            CREATE TABLE IF NOT EXISTS decision (
                number TEXT, date TEXT, title TEXT, url TEXT, source TEXT,
                first_seen TEXT, last_seen TEXT, active INTEGER, publication_date TEXT,
                pdf BLOB, pdf_attempt TEXT, pdf_error TEXT,
                PRIMARY KEY (source, number)
            );
        """)
        results = [scan(db, name, url) for name, url in SOURCES.items()]
        download(db)
        render(db)
    status = ROOT / "site" / "source-error"
    if all(results):
        status.unlink(missing_ok=True)
    else:
        status.touch()


if __name__ == "__main__":
    main()
