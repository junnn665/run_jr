# 「今日のJR東海」：その日の主な話題を、AIが見出しだけをもとに3〜5行にまとめる
# GitHub Actions から実行。prepare で聞く内容を作り、公式の actions/ai-inference でAIに聞き、finish で保存する。
# AIが使えないとき（混雑・上限・設定なし）は何もせず、前回のまとめをそのまま残す。
import json, os, re, sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
OUT = "digest.json"
MODEL = "openai/gpt-4.1-mini"   # GitHub の無料のAI（actions/ai-inference で呼ぶ）
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

def note(prev, msg):
    """うまくいかなかった理由を digest.json に残す（前回のまとめはそのまま）"""
    print("AIまとめ：", msg)
    prev = dict(prev)
    prev["last_try"] = NOW.isoformat(timespec="minutes")
    prev["last_error"] = str(msg)[:300]
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(prev, f, ensure_ascii=False, indent=1)
    return 0

def build_prompt(topics):
    lines = "\n".join(f"{i+1}. {t['title']}（{t['n']}件の記事）" for i, t in enumerate(topics))
    return ("あなたはJR東海関連ニュースの編集者です。下の見出しだけを材料に、今日の主な出来事を日本語で3〜5行にまとめます。"
            "見出しに書かれていない事実、数字、理由、予想は絶対に足さないでください。1行は60文字以内の、"
            "です・ます調ではない短い文にします。記事の多い話題や、運行・安全・リニア・決算に関わる話題を優先します。\n\n"
            "今日の見出し一覧:\n" + lines +
            '\n\n次の形のJSONだけを返してください（説明文やコードブロックは不要）: {"items":[{"n":見出し番号,"text":"まとめの1行"}]}')

def parse_reply(text, topics):
    m = re.search(r"\{.*\}", text or "", re.S)
    data = json.loads(m.group(0))
    out = []
    for it in data.get("items", [])[:5]:
        n = int(it.get("n", 0))
        line = str(it.get("text", "")).strip()
        if 1 <= n <= len(topics) and line:
            out.append({"text": line[:80], "g": topics[n - 1]["g"], "title": topics[n - 1]["title"]})
    return out

def set_output(k, v):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{k}={v}\n")

def prepare():
    """AIに聞くかどうかを決めて、聞く内容（プロンプト）をファイルに書く"""
    news = load("news.json", {"items": []})["items"]
    prev = load(OUT, {})
    topics = topics_for_today(news)
    tmp = os.environ.get("RUNNER_TEMP", ".")
    if len(topics) < 2:
        return note(prev, f"今日の話題が少ないので作りません（{len(topics)}件）")
    key = "|".join(t["g"] for t in topics[:8])
    if prev.get("date") == NOW.date().isoformat() and prev.get("items") and prev.get("ai", True):
        last = datetime.fromisoformat(prev.get("generated", "2000-01-01T00:00+09:00"))
        if prev.get("key") == key or NOW - last < timedelta(hours=MIN_INTERVAL_HOURS):
            print("AIまとめ：変化がないか、前回から時間がたっていないので据え置き"); return 0
    with open(os.path.join(tmp, "digest_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(build_prompt(topics))
    with open(os.path.join(tmp, "digest_topics.json"), "w", encoding="utf-8") as f:
        json.dump({"key": key, "topics": topics}, f, ensure_ascii=False)
    set_output("run", "true")
    print(f"AIまとめ：{len(topics)}件の話題をAIに渡します")
    return 0

def clean_title(t):
    t = re.sub(r"^(【[^】]*】|画像ギャラリー\s*[|｜]?|画像\s*[|｜])\s*", "", t)
    t = re.sub(r"\s*[（(][^）)]*(新聞|ニュース|NEWS|News|通信|テレビ|TV|Powered|Watch|オンライン)[^）)]*[）)]\s*$", "", t)
    t = re.sub(r"\s*[|｜]\s*[^|｜]{1,30}$", "", t)
    t = re.sub(r"[：:]ニュース$", "", t)
    return t.strip()

def fallback(meta, prev, reason):
    """AIが使えないときは、記事の多い話題を上から5つ並べる（見出しそのままなので内容は正確）"""
    items = [{"text": clean_title(t["title"])[:80], "g": t["g"], "title": t["title"], "n": t["n"]}
             for t in meta["topics"][:5]]
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"date": NOW.date().isoformat(), "generated": NOW.isoformat(timespec="minutes"),
                   "ai": False, "key": meta["key"], "items": items, "ai_error": reason[:200]},
                  f, ensure_ascii=False, indent=1)
    print("AIまとめ：AIが使えないので記事の多い話題を並べました（" + reason + "）")
    return 0

def finish():
    """AIの返事を読み取って digest.json に保存する"""
    prev = load(OUT, {})
    tmp = os.environ.get("RUNNER_TEMP", ".")
    meta = load(os.path.join(tmp, "digest_topics.json"), None)
    if not meta:
        return note(prev, "準備したファイルが見つかりません")
    text = ""
    rf = os.environ.get("AI_RESPONSE_FILE", "")
    if rf and os.path.exists(rf):
        text = open(rf, encoding="utf-8").read()
    text = text or os.environ.get("AI_RESPONSE", "")
    if not text:
        return fallback(meta, prev, f"AIから返事がありませんでした（{os.environ.get('AI_OUTCOME', '')}）")
    try:
        items = parse_reply(text, meta["topics"])
    except Exception as e:
        return fallback(meta, prev, f"AIの返事を読み取れませんでした: {e} {text[:80]}")
    if not items:
        return fallback(meta, prev, "うまくまとめられませんでした")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"date": NOW.date().isoformat(), "generated": NOW.isoformat(timespec="minutes"),
                   "ai": True, "model": MODEL, "key": meta["key"], "items": items}, f, ensure_ascii=False, indent=1)
    print("AIまとめ：", *[i["text"] for i in items], sep="\n  ")
    return 0

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "prepare":
        return prepare()
    if mode == "finish":
        return finish()
    print("使い方: python ai_digest.py prepare | finish")
    return 0

if __name__ == "__main__":
    sys.exit(main())
