# 「今日のJR東海」：その日の主な話題を、AIが見出しだけをもとに3〜5行にまとめる
# GitHub Actions から実行。GitHub Models（GitHubの無料のAI）を使い、GITHUB_TOKEN で認証する。
# AIが使えないとき（混雑・上限・設定なし）は何もせず、前回のまとめをそのまま残す。
import json, os, re, sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
OUT = "digest.json"
MODEL = "openai/gpt-4.1-mini"
ENDPOINT = "https://models.github.ai/inference/chat/completions"
MIN_INTERVAL_HOURS = 3      # 同じ日のまとめを作り直す間隔（AIの利用回数を節約）
MAX_TOPICS = 15

def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def topics_for_today(items):
    """直近24時間の記事を話題（g）ごとにまとめ、報じた記事が多い順に並べる"""
    since = (NOW - timedelta(hours=24)).date().isoformat()
    groups = defaultdict(list)
    for x in items:
        if x["date"] >= since:
            groups[x.get("g", x["url"])].append(x)
    ranked = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    topics = []
    for g, xs in ranked[:MAX_TOPICS]:
        main = next((x for x in xs if x.get("src") == "JR東海"), None) or min(xs, key=lambda x: len(x["title"]))  # 公式発表か、いちばん短い（媒体名などが付いていない）見出し
        topics.append({"g": g, "title": main["title"], "n": len(xs), "cat": main.get("cat", "")})
    return topics

def ask_ai(topics, token):
    lines = "\n".join(f"{i+1}. {t['title']}（{t['n']}件の記事）" for i, t in enumerate(topics))
    system = ("あなたはJR東海関連ニュースの編集者です。渡された見出しだけを材料に、"
              "今日の主な出来事を日本語で3〜5行にまとめます。見出しに書かれていない事実、数字、理由、"
              "予想は絶対に足さないでください。1行は60文字以内の、です・ます調ではない短い文にします。"
              "記事の多い話題や、運行・安全・リニア・決算に関わる話題を優先します。")
    user = ("今日の見出し一覧:\n" + lines +
            '\n\n次の形のJSONだけを返してください: {"items":[{"n":見出し番号,"text":"まとめの1行"}]}')
    body = json.dumps({"model": MODEL, "temperature": 0.2,
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}).encode()
    req = Request(ENDPOINT, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    res = json.loads(urlopen(req, timeout=60).read().decode())
    text = res["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", text, re.S)
    data = json.loads(m.group(0))
    out = []
    for it in data.get("items", [])[:5]:
        n = int(it.get("n", 0))
        line = str(it.get("text", "")).strip()
        if 1 <= n <= len(topics) and line:
            out.append({"text": line[:80], "g": topics[n - 1]["g"], "title": topics[n - 1]["title"]})
    return out

def main():
    token = os.environ.get("GITHUB_TOKEN", "")
    news = load("news.json", {"items": []})["items"]
    prev = load(OUT, {})
    topics = topics_for_today(news)
    if len(topics) < 2:
        print("AIまとめ：今日の話題が少ないので作りません"); return 0
    key = "|".join(t["g"] for t in topics[:8])
    if prev.get("date") == NOW.date().isoformat():
        last = datetime.fromisoformat(prev.get("generated", "2000-01-01T00:00+09:00"))
        if prev.get("key") == key or NOW - last < timedelta(hours=MIN_INTERVAL_HOURS):
            print("AIまとめ：変化がないか、前回から時間がたっていないので据え置き"); return 0
    if not token:
        print("AIまとめ：GITHUB_TOKEN がないので作りません"); return 0
    try:
        items = ask_ai(topics, token)
    except Exception as e:
        print("AIまとめ：AIに接続できませんでした（前回のまとめを残します）:", e); return 0
    if not items:
        print("AIまとめ：うまくまとめられませんでした"); return 0
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"date": NOW.date().isoformat(), "generated": NOW.isoformat(timespec="minutes"),
                   "model": MODEL, "key": key, "items": items}, f, ensure_ascii=False, indent=1)
    print("AIまとめ：", *[i["text"] for i in items], sep="\n  ")
    return 0

if __name__ == "__main__":
    sys.exit(main())
