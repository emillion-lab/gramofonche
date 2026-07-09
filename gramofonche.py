#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Грамофонче каталог — scraper + builder + личен downloader
=========================================================
Източник: https://gramofonche.chitanka.info/ (копие на Грамофончето на Свилен Добрев)

Команди:
  python3 gramofonche.py scrape              # обхожда /prikazki/ -> data/albums.json
  python3 gramofonche.py scrape --all        # + /pesnicki/ и /zagolemi/
  python3 gramofonche.py build               # data/albums.json -> index.html (single-file)
  python3 gramofonche.py download --max-min 20 --out ~/Prikazki
                                             # ЛИЧНО локално сваляне (НЕ качвай mp3 в публично repo!)

Зависимости: pip install requests beautifulsoup4
"""

import argparse, json, os, re, sys, time
from urllib.parse import urljoin, unquote

import requests
from bs4 import BeautifulSoup

BASE = "https://gramofonche.chitanka.info"
SECTIONS = {"prikazki": "приказки", "pesnicki": "песнички", "zagolemi": "за възрастни"}
HEADERS = {"User-Agent": "Mozilla/5.0 (gramofonche-catalog; personal index builder)"}
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "albums.json")
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")
OUT_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

S = requests.Session()
S.headers.update(HEADERS)


def get(url, retries=3):
    for i in range(retries):
        try:
            r = S.get(url, timeout=30)
            if r.status_code == 200:
                r.encoding = r.apparent_encoding or "utf-8"
                return r
        except requests.RequestException as e:
            print(f"  ! {e}", file=sys.stderr)
        time.sleep(2 * (i + 1))
    return None


def album_links(section):
    """Всички линкове към албумни страници в даден раздел."""
    r = get(f"{BASE}/{section}/")
    if not r:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    links, seen = [], set()
    pat = re.compile(rf"^(?:{re.escape(BASE)})?/{section}/[^/#?]+/?$")
    for a in soup.find_all("a", href=True):
        href = urljoin(BASE + "/", a["href"]).split("#")[0]
        if pat.match(href.replace(BASE, "")) and href.rstrip("/") != f"{BASE}/{section}":
            if href not in seen:
                seen.add(href)
                links.append(href)
    return links


RE_SIZE = re.compile(r"размер:\s*([\d.]+)\s*M\s*:\s*(\d+)\s*мин")
RE_MIN = re.compile(r"\.\.\s*(\d+)\s*мин")
RE_FIELD = {
    "author": re.compile(r"автор:\s*([^\n·]+)"),
    "kind": re.compile(r"вид:\s*([^\n·]+)"),
    "quality": re.compile(r"качество:\s*([+~?\-]/[+~?\-])"),
    "year": re.compile(r"година:\s*(\d{4})"),
}


def parse_album(url, section):
    r = get(url)
    if not r:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text("\n")

    h1 = soup.find("h1")
    title = (h1.get_text(" ", strip=True) if h1 else soup.title.get_text() if soup.title else url)
    title = re.sub(r"\s+", " ", title).strip()

    a = {"url": url, "section": section, "title": title,
         "minutes": None, "mb": None, "author": "", "kind": "",
         "quality": "", "year": None, "tracks": [], "mp3": []}

    m = RE_SIZE.search(text)
    if m:
        a["mb"] = float(m.group(1))
        a["minutes"] = int(m.group(2))
    if a["minutes"] in (None, 0):
        m = RE_MIN.search(text)
        if m:
            a["minutes"] = int(m.group(1))

    for key, rx in RE_FIELD.items():
        m = rx.search(text)
        if m:
            a[key] = m.group(1).strip() if key != "year" else int(m.group(1))

    # звездички от заглавната страница се пазят в title; любими = "**"
    # mp3 линкове (за личния downloader и за директно слушане)
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.lower().endswith(".mp3"):
            full = urljoin(url, href)
            name = unquote(os.path.basename(full))
            a["mp3"].append({"name": name, "url": full})
            a["tracks"].append(re.sub(r"\.mp3$", "", name, flags=re.I))

    # ако няма mp3 линкове, вземи записите от текста след "записи:"
    if not a["tracks"]:
        m = re.search(r"записи:\s*\n(.*?)(?:\n\s*размер:|\Z)", text, re.S)
        if m:
            a["tracks"] = [t.strip(" ·") for t in m.group(1).split("\n") if t.strip(" ·")][:60]

    return a


def cmd_scrape(args):
    sections = list(SECTIONS) if args.all else ["prikazki"]
    albums = []
    for sec in sections:
        links = album_links(sec)
        print(f"[{sec}] {len(links)} албума")
        for i, url in enumerate(links, 1):
            a = parse_album(url, sec)
            if a:
                albums.append(a)
                print(f"  {i}/{len(links)}  {a['minutes'] or '?'} мин  {a['title'][:70]}")
            time.sleep(args.delay)
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump({"generated": time.strftime("%Y-%m-%d %H:%M"),
                   "source": BASE, "albums": albums}, f, ensure_ascii=False, indent=1)
    total_min = sum(a["minutes"] or 0 for a in albums)
    print(f"\nГотово: {len(albums)} албума, общо {total_min} мин -> {DATA}")


def cmd_build(args):
    with open(DATA, encoding="utf-8") as f:
        data = f.read()
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    html = tpl.replace("/*__DATA__*/null", data)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Готово: {OUT_HTML} ({os.path.getsize(OUT_HTML)//1024} KB)")


def safe(s):
    return re.sub(r'[\\/:*?"<>|]+', "_", s).strip()[:120]


def cmd_download(args):
    """ЛИЧНА употреба. Папките се именуват 'NNNмин - Заглавие' — дължината се вижда веднага."""
    with open(DATA, encoding="utf-8") as f:
        albums = json.load(f)["albums"]
    picked = [a for a in albums
              if a["mp3"]
              and (args.max_min is None or (a["minutes"] or 10**6) <= args.max_min)
              and (args.min_min is None or (a["minutes"] or 0) >= args.min_min)
              and (not args.match or args.match.lower() in a["title"].lower())]
    print(f"{len(picked)} албума за сваляне -> {args.out}")
    for a in picked:
        folder = os.path.join(args.out, f"{(a['minutes'] or 0):03d}мин - {safe(a['title'])}")
        os.makedirs(folder, exist_ok=True)
        for t in a["mp3"]:
            path = os.path.join(folder, safe(t["name"]))
            if os.path.exists(path):
                continue
            print(f"  ↓ {t['name']}")
            r = get(t["url"])
            if r:
                with open(path, "wb") as f:
                    f.write(r.content)
            time.sleep(args.delay)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Грамофонче каталог")
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("scrape")
    sc.add_argument("--all", action="store_true", help="и песнички + за възрастни")
    sc.add_argument("--delay", type=float, default=1.0, help="пауза между заявки (сек)")

    sub.add_parser("build")

    dl = sub.add_parser("download")
    dl.add_argument("--out", default=os.path.expanduser("~/Gramofonche"))
    dl.add_argument("--max-min", type=int, default=None)
    dl.add_argument("--min-min", type=int, default=None)
    dl.add_argument("--match", default="", help="филтър по заглавие")
    dl.add_argument("--delay", type=float, default=1.5)

    args = p.parse_args()
    {"scrape": cmd_scrape, "build": cmd_build, "download": cmd_download}[args.cmd](args)
