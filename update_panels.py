# リニア工事の進捗（linear.json）と業績（finance.json）を自動で更新するスクリプト
# fetch_news.py のあとに GitHub Actions から1時間ごとに実行されます。
#
# ・リニア：駅や工区ごとに最新ニュースを結びつけ、見出しに「貫通」「着工」「完成」などが
#   出たら状況の表示を自動で切り替えます。
# ・業績：JR東海が「決算短信」を公式発表したら、PDFを読み込んで表の数字を自動で書き換えます。
#   PDFの読み取りに失敗したときは、表はそのままにして「新しい決算が出ました」と知らせます。
import json, re, io, sys
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)

def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

# ------------------------------------------------------------------ リニア
# 見出しにこの言葉があれば状況を切り替える（上ほど優先）
MILESTONES = [
    (re.compile(r"開業"),               None,    None),          # 開業の話題は予定の話が多いので無視
    (re.compile(r"貫通"),               "done",  "貫通"),
    (re.compile(r"完成|竣工|完了"),      "done",  "完成"),
    (re.compile(r"起工式|着工|工事開始|掘削開始|掘進開始"), "start", "着工"),
]
# 「着工へ」「着工容認」など、まだ起きていない話は除く
NOT_YET = re.compile(r"へ$|へ[ 　、。]|容認|予定|見通し|目指|方針|計画|検討|要望|遅れ|延期|困難|できず|せず")

def update_linear(news):
    L = load("linear.json")
    items = [x for x in news if x.get("cat") == "linear" or "リニア" in x["title"]]
    changed = []
    for o in L["stations"] + L["works"]:
        hits = sorted([x for x in items if any(k in x["title"] for k in o["kw"])],
                      key=lambda x: x["date"], reverse=True)
        o["latest"] = ({"date": hits[0]["date"], "title": hits[0]["title"], "url": hits[0]["url"]}
                       if hits else None)
        for x in hits:
            if x["date"] <= o.get("status_date", ""):
                break
            if NOT_YET.search(x["title"]):
                continue
            for pat, status, label in MILESTONES:
                if pat.search(x["title"]):
                    if status:
                        m, d = int(x["date"][5:7]), int(x["date"][8:10])
                        o["status"] = status
                        o["label"] = f"{label}（{m}/{d}報道）"
                        o["status_date"] = x["date"]
                        o["status_src"] = x["url"]
                        changed.append(f"{o['name']} → {o['label']}")
                    break
            if o["status_date"] == x["date"]:
                break
    L["checked"] = NOW.isoformat(timespec="minutes")
    save("linear.json", L)
    print("リニア：", "、".join(changed) if changed else "状況の変化なし")

# ------------------------------------------------------------------ 業績
Z2H = str.maketrans("０１２３４５６７８９，．－△▲", "0123456789,.---")
NUM = r"([\d,]+)\s+(-?[\d.]+|-)"

def to_text(pdf_bytes):
    from pypdf import PdfReader
    page = PdfReader(io.BytesIO(pdf_bytes)).pages[0]
    t = page.extract_text() or ""
    t = t.translate(Z2H)
    t = re.sub(r"[ 　\t]+", " ", t)
    return t

def parse_tanshin(text):
    """決算短信1ページ目から、今期の実績と通期予想を読み取る"""
    flat = re.sub(r"\s+", " ", text)
    # 例：2027年3月期第1四半期 492,700 3.0 219,100 -0.9 ...
    m = re.search(r"(\d{4})年\s*3\s*月期\s*(第\s*([123])\s*四半期)?\s+" + r"\s+".join([NUM] * 4), flat)
    if not m:
        return None
    year, q = m.group(1), m.group(3)
    nums = m.groups()[3:]
    def pair(i):
        v = int(nums[i * 2].replace(",", ""))
        p = nums[i * 2 + 1]
        return [v // 100, None if p == "-" else float(p)]
    actual = [pair(i) for i in range(4)]
    fm = re.search(r"通期\s+" + r"\s+".join([NUM] * 4), flat)
    forecast = None
    if fm:
        fn = fm.groups()
        forecast = []
        for i in range(4):
            v = int(fn[i * 2].replace(",", ""))
            p = fn[i * 2 + 1]
            forecast.append([v // 100, None if p == "-" else float(p)])
    # 金額として変な値（営業収益が1000億円未満など）は読み違いとみなす
    if actual[0][0] < 1000:
        return None
    return {"year": int(year), "q": int(q) if q else None, "actual": actual, "forecast": forecast}

QLABEL = {1: "1Q（4〜6月）", 2: "中間（4〜9月）", 3: "3Q（4〜12月）"}

def apply_tanshin(F, r, url):
    fy = r["year"]
    if r["q"] is None:
        # 本決算：前期実績 ← 今回の通期実績、今期予想 ← 新しい予想、四半期の列は空に
        F["cols"] = [f"{fy}年3月期<br>実績", f"{fy+1}年3月期<br>会社予想", f"{fy+1}年3月期<br>四半期"]
        for i, row in enumerate(F["rows"]):
            row["v"] = [r["actual"][i], r["forecast"][i] if r["forecast"] else None, None]
        F["asof"] = f"{fy}年3月期決算を自動反映"
    else:
        F["cols"][2] = f"{fy}年3月期<br>{QLABEL[r['q']]}"
        if r["forecast"]:
            F["cols"][1] = f"{fy}年3月期<br>会社予想"
        for i, row in enumerate(F["rows"]):
            row["v"][2] = r["actual"][i]
            if r["forecast"]:
                row["v"][1] = r["forecast"][i]
        F["asof"] = f"{fy}年3月期 {QLABEL[r['q']].split('（')[0]}決算を自動反映"
    F["links"][0] = {"t": "最新の決算短信（PDF）", "u": url}

def update_finance(news):
    F = load("finance.json")
    done = set(F.get("processed", []))
    docs = [x for x in news if x.get("src") == "JR東海" and "決算短信" in x["title"]
            and x["url"].lower().endswith(".pdf") and x["url"] not in done]
    for x in sorted(docs, key=lambda x: x["date"]):
        note = None
        try:
            req = Request(x["url"], headers={"User-Agent": "Mozilla/5.0 (tokai-news bot)"})
            r = parse_tanshin(to_text(urlopen(req, timeout=60).read()))
        except Exception as e:
            print("決算短信を読み込めませんでした:", e)
            r = None
        if r:
            apply_tanshin(F, r, x["url"])
            print("業績：", F["asof"])
        else:
            note = {"date": x["date"], "title": x["title"], "url": x["url"]}
            print("業績：数字を読み取れなかったので、お知らせだけ表示します")
        F["notice"] = note
        F.setdefault("processed", []).append(x["url"])
    F["checked"] = NOW.isoformat(timespec="minutes")
    save("finance.json", F)

def main():
    news = load("news.json")["items"]
    for fn in (update_linear, update_finance):
        try:
            fn(news)
        except Exception as e:
            print(fn.__name__, "でエラー:", e)
    return 0

if __name__ == "__main__":
    sys.exit(main())
