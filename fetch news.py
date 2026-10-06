# JR東海の公式発表・Googleニュース・鉄道ニュースサイトを読み込み、news.json に新しい記事を追加するスクリプト
# GitHub Actions から1時間ごとに実行されます。
import json, re, sys, html
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.parse import urljoin

LIST_URL = "https://jr-central.co.jp/news/"
# 公式発表以外のニュース（新聞・ニュースサイト）も Google ニュースから集める
GOOGLE_QUERIES = [
    "JR東海", "東海道新幹線", "リニア中央新幹線", "N700S", "スプリームクラス",
    "名古屋駅 JR", "特急しなの",
    # リニアの駅・工区
    "リニア 品川駅 工事", "リニア 神奈川県駅", "リニア 山梨県駅", "リニア 長野県駅",
    "リニア 岐阜県駅", "リニア 名古屋駅 工事", "リニア 静岡工区", "南アルプストンネル",
    "中央アルプストンネル", "リニア 瑞浪", "特急ひだ", "315系", "飯田線", "身延線", "ドクターイエロー",
]
# 鉄道・旅行ニュースサイトのRSS（JR東海に関係する記事だけを取り込む）
FEEDS = {
    "鉄道チャンネル": "https://tetsudo-ch.com/feed",
    "トラベル Watch": "https://travel.watch.impress.co.jp/data/rss/1.0/trw/feed.rdf",
    "TRAICY": "https://www.traicy.com/feed",
    "レスポンス": "https://response.jp/rss/index.rdf",
}
KEYWORDS = [
    "JR東海", "ＪＲ東海", "東海旅客鉄道", "東海道新幹線", "リニア", "南アルプストンネル", "中央アルプストンネル", "N700S", "Ｎ７００Ｓ",
    "スプリームクラス", "ドクターイエロー", "名古屋駅", "静岡駅", "浜松駅", "飯田線", "身延線",
    "高山本線", "紀勢本線", "関西本線", "御殿場線", "武豊線", "太多線",
    "特急しなの", "「しなの」", "特急ひだ", "「ひだ」", "特急南紀", "「南紀」", "ふじかわ", "伊那路", "HC85", "315系", "313系", "EXサービス", "スマートEX", "エクスプレス予約",
]
GOOGLE_DAYS = 7   # 何日前までの記事を取り込むか
JSON_PATH = "news.json"
MAX_ITEMS = 300
JST = timezone(timedelta(hours=9))

# 見出しの言葉からカテゴリを決める（上から順に判定）
RULES = [
    ("linear",     ["リニア", "南アルプストンネル", "中央アルプストンネル", "静岡工区"]),
    ("unko",       ["運休", "運転見合わせ", "運行情報", "踏切", "防犯", "安全", "台風", "大雨", "地震", "遅れ", "事故"]),
    ("event",      ["キャンペーン", "きっぷ", "切符", "セール", "ツアー", "フェス", "イベント", "記念", "プレゼント", "旅"]),
    ("shinkansen", ["新幹線", "のぞみ", "ひかり", "こだま", "ＥＸ", "EX", "予約状況", "N700", "スプリーム", "グリーン車", "S Work", "個室"]),
    ("zairai",     ["在来線", "特急", "ワイドビュー", "しなの", "ひだ", "サイクルトレイン", "315系", "線"]),
    ("eki",        ["駅"]),
]

def categorize(title):
    for cat, words in RULES:
        if any(w in title for w in words):
            return cat
    return "kaisha"

DATE_RE = re.compile(r"(\d{4})\s*[.\-/年]\s*(\d{1,2})\s*[.\-/月]\s*(\d{1,2})")
LINK_RE = re.compile(r'<a\b[^>]*href="([^"]*release/[^"]+\.html)"[^>]*>(.*?)</a>', re.S | re.I)

def clean(text):
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

def parse(page):
    found = []
    prev_end = 0
    for m in LINK_RE.finditer(page):
        url = urljoin(LIST_URL, m.group(1))
        inner = clean(m.group(2))
        # 日付はリンクの中、なければ直前の部分から探す
        dm = DATE_RE.search(inner)
        if not dm:
            before = page[max(prev_end, m.start() - 800):m.start()]
            dates = list(DATE_RE.finditer(clean(before)))
            dm = dates[-1] if dates else None
        prev_end = m.end()
        if not dm:
            continue
        date = f"{int(dm.group(1)):04d}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
        title = DATE_RE.sub("", inner).strip(" 　|・-")
        if title:
            found.append({"date": date, "title": title, "url": url})
    return found

def fetch(url):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (tokai-news bot)"})
    return urlopen(req, timeout=30).read().decode("utf-8", "replace")

def fetch_google(query):
    url = "https://news.google.com/rss/search?q=" + quote(query) + "&hl=ja&gl=JP&ceid=JP:ja"
    root = ET.fromstring(fetch(url))
    limit = datetime.now(JST) - timedelta(days=GOOGLE_DAYS)
    out = []
    for it in root.iter("item"):
        title = clean(it.findtext("title") or "")
        link = (it.findtext("link") or "").strip()
        src_el = it.find("source")
        src = clean(src_el.text) if src_el is not None and src_el.text else ""
        if src and title.endswith(" - " + src):
            title = title[: -len(" - " + src)].strip()
        try:
            when = parsedate_to_datetime(it.findtext("pubDate")).astimezone(JST)
        except Exception:
            continue
        if when < limit or not title or not link:
            continue
        out.append({"date": when.strftime("%Y-%m-%d"), "title": title, "url": link, "src": src or "ニュース"})
    return out

def local(tag):
    return tag.rsplit("}", 1)[-1]

def fetch_feed(name, url):
    """RSS 2.0 / RSS 1.0(RDF) / Atom のどれでも読めるようにする"""
    root = ET.fromstring(fetch(url))
    limit = datetime.now(JST) - timedelta(days=GOOGLE_DAYS)
    out = []
    for it in root.iter():
        if local(it.tag) not in ("item", "entry"):
            continue
        title = link = when_text = ""
        for ch in it:
            n = local(ch.tag)
            if n == "title":
                title = clean(ch.text or "")
            elif n == "link":
                link = (ch.text or ch.get("href") or "").strip()
            elif n in ("pubDate", "date", "published", "updated") and not when_text:
                when_text = (ch.text or "").strip()
        if not title or not link or not any(k in title for k in KEYWORDS):
            continue
        try:
            if re.match(r"\d{4}-", when_text):
                when = datetime.fromisoformat(when_text.replace("Z", "+00:00")).astimezone(JST)
            else:
                when = parsedate_to_datetime(when_text).astimezone(JST)
        except Exception:
            continue
        if when < limit:
            continue
        out.append({"date": when.strftime("%Y-%m-%d"), "title": title, "url": link, "src": name})
    return out

def norm(title):
    return re.sub(r"[\s「」『』【】（）()、。・!！?？]", "", title)

def main():
    try:
        with open(JSON_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {"updated": "", "items": []}

    fresh = []
    try:
        official = parse(fetch(LIST_URL))
        for x in official:
            x["src"] = "JR東海"
        fresh += official
        if not official:
            print("公式一覧から記事が見つかりませんでした。ページの形が変わった可能性があります。")
    except Exception as e:
        print("公式一覧を取得できませんでした:", e)
    for q in GOOGLE_QUERIES:
        try:
            got = fetch_google(q)
            print(f"Googleニュース「{q}」: {len(got)}件")
            fresh += got
        except Exception as e:
            print(f"Googleニュース「{q}」を取得できませんでした:", e)
    for name, url in FEEDS.items():
        try:
            got = fetch_feed(name, url)
            print(f"{name}: {len(got)}件")
            fresh += got
        except Exception as e:
            print(f"{name}を取得できませんでした:", e)

    known = {x["url"] for x in data["items"]}
    titles = {norm(x["title"]) for x in data["items"]}
    added = []
    for x in fresh:
        key = norm(x["title"])
        if x["url"] in known or key in titles:
            continue
        known.add(x["url"]); titles.add(key)
        added.append({"date": x["date"], "cat": categorize(x["title"]),
                      "title": x["title"], "summary": "", "url": x["url"], "src": x["src"]})

    if not added:
        print("新しい記事はありません")
        return 0

    items = sorted(data["items"] + added, key=lambda x: x["date"], reverse=True)[:MAX_ITEMS]
    data = {"updated": datetime.now(JST).isoformat(timespec="minutes"), "items": items}
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"{len(added)}件追加:", *[a["title"] for a in added], sep="\n  ")
    return 0

if __name__ == "__main__":
    sys.exit(main())
