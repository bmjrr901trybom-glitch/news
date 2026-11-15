"""RSSからニュースを集め、重要度順+ジャンル別のトップページ docs/index.html を生成する。
環境変数 ANTHROPIC_API_KEY があれば、Claudeで1行要約とジャンル分けを行う(なければルールのみ)。"""
import html, json, os, re, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# ===== 設定(ここを変えれば調整できます) =====
# (表示名, RSSのURL, 重み, ジャンル)  ※URLが変わった場合はここを直す
FEEDS = [
    ("NHK 主要",   "https://www3.nhk.or.jp/rss/news/cat0.xml", 1.0, "国内"),
    ("NHK 国際",   "https://www3.nhk.or.jp/rss/news/cat6.xml", 0.7, "国際"),
    ("NHK 経済",   "https://www3.nhk.or.jp/rss/news/cat5.xml", 0.7, "経済"),
    ("NHK スポーツ", "https://www3.nhk.or.jp/rss/news/cat7.xml", 0.7, "スポーツ"),
    ("Yahoo!ニュース 主要", "https://news.yahoo.co.jp/rss/topics/top-picks.xml", 1.0, "国内"),
    ("Yahoo!ニュース 国際", "https://news.yahoo.co.jp/rss/topics/world.xml", 0.7, "国際"),
    ("Yahoo!ニュース 経済", "https://news.yahoo.co.jp/rss/topics/business.xml", 0.7, "経済"),
    ("Yahoo!ニュース IT",   "https://news.yahoo.co.jp/rss/topics/it.xml", 0.7, "IT"),
    ("Yahoo!ニュース スポーツ", "https://news.yahoo.co.jp/rss/topics/sports.xml", 0.7, "スポーツ"),
    ("朝日新聞",   "https://www.asahi.com/rss/asahi/newsheadlines.rdf", 0.9, "国内"),
    ("ITmedia NEWS", "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml", 0.7, "IT"),
]
GENRES = ["国内", "国際", "経済", "IT", "スポーツ", "エンタメ", "その他"]
PER_FEED = 15       # 各フィードから使う件数
SAME_TOPIC = 0.30   # 見出しの類似度がこれ以上なら同じ話題とみなす
SHOW = 30           # ページに載せる総件数
PER_GENRE = 10      # ジャンル別タブで表示する最大件数
CLAUDE_MODEL = "claude-haiku-5-5"
OUT = "docs/index.html"
# ==============================================

def http(url, data=None, headers=None):
    h = {"User-Agent": "Mozilla/5.0 news-aggregator"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()

def parse(data):
    root = ET.fromstring(data)
    items = []
    for el in root.iter():
        if el.tag.split("}")[-1] != "item":
            continue
        f = {c.tag.split("}")[-1]: (c.text or "").strip() for c in el}
        if f.get("title") and f.get("link"):
            items.append((f["title"], f["link"]))
    return items

def grams(t):
    t = re.sub(r"[\s　【】「」『』()（）、。・:：!！?？\-—\"'“”]", "", t)
    return {t[i:i + 2] for i in range(len(t) - 1)}

def sim(a, b):
    return len(a & b) / max(1, min(len(a), len(b)))

def collect():
    clusters = []
    for name, url, w, genre in FEEDS:
        try:
            items = parse(http(url))[:PER_FEED]
        except Exception as e:
            print("取得失敗:", name, e)
            continue
        for rank, (title, link) in enumerate(items):
            pts = w * (PER_FEED - rank) / PER_FEED
            g = grams(title)
            for c in clusters:
                if name not in c["sources"] and sim(g, c["g"]) >= SAME_TOPIC:
                    c["sources"][name] = link
                    c["score"] += pts + 1.0
                    break
            else:
                clusters.append({"title": title, "link": link, "g": g, "genre": genre,
                                 "summary": "", "sources": {name: link}, "score": pts})
    clusters.sort(key=lambda c: -c["score"])
    return clusters[:SHOW]

def enrich(cl):
    """Claudeで1行要約とジャンル分け。キーが無い/失敗した場合は何もしない。"""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key or not cl:
        return
    lines = "\n".join("%d: %s" % (i, c["title"]) for i, c in enumerate(cl))
    prompt = ("次はニュースの見出し一覧です。各見出しについて、(1)見出しから読み取れる範囲だけで40字以内の日本語の1行要約、"
              "(2)ジャンル(%s のいずれか)を付けてください。見出しにない事実を推測で足さないこと。"
              "出力はJSON配列のみ(説明やコードブロックは不要)。形式: [{\"i\":0,\"summary\":\"...\",\"genre\":\"...\"}]\n\n%s"
              % ("/".join(GENRES), lines))
    body = json.dumps({"model": CLAUDE_MODEL, "max_tokens": 6000,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    try:
        res = json.loads(http("https://api.anthropic.com/v1/messages", body,
                              {"x-api-key": key, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"}))
        text = "".join(b.get("text", "") for b in res["content"])
        arr = json.loads(re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip())
        for o in arr:
            c = cl[int(o["i"])]
            c["summary"] = str(o.get("summary", ""))[:80]
            if o.get("genre") in GENRES:
                c["genre"] = o["genre"]
    except Exception as e:
        print("Claudeによる要約に失敗(ルールのみで続行):", e)

def chips(c):
    return "".join('<a class="chip" target="_blank" rel="noopener" href="%s">%s</a>'
                   % (html.escape(l), html.escape(n)) for n, l in c["sources"].items())

def render(cl):
    jst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y年%m月%d日 %H:%M")
    mx = max([c["score"] for c in cl] + [1])
    if not cl:
        return PAGE.replace("{{UPDATED}}", jst).replace("{{TABS}}", "").replace("{{BODY_HERO}}", "").replace("{{BODY}}", "<p>ニュースを取得できませんでした。</p>")
    t = cl[0]
    hero = ('<div class="hero"><div class="tag">TOP STORY ・ %s</div><h2><a href="%s" target="_blank" rel="noopener">%s</a></h2>%s<div class="meta">%s</div></div>'
            % (html.escape(t["genre"]), html.escape(t["link"]), html.escape(t["title"]),
               '<p class="sum">%s</p>' % html.escape(t["summary"]) if t["summary"] else "", chips(t)))
    body = ""
    seen = {}
    for c in cl[1:]:
        seen[c["genre"]] = seen.get(c["genre"], 0) + 1
        c["_hide"] = seen[c["genre"]] > PER_GENRE
        body += ('<div class="item" data-g="%s"%s><div class="rank"></div><div><h3><a href="%s" target="_blank" rel="noopener">%s</a></h3>%s'
                 '<div class="meta"><span class="g">%s</span><span class="bar"><i style="width:%d%%"></i></span>%s</div></div></div>'
                 % (html.escape(c["genre"]), ' data-x="1"' if c["_hide"] else "", html.escape(c["link"]), html.escape(c["title"]),
                    '<p class="sum">%s</p>' % html.escape(c["summary"]) if c["summary"] else "",
                    html.escape(c["genre"]), 100 * c["score"] / mx, chips(c)))
    genres = [g for g in GENRES if any(c["genre"] == g for c in cl)]
    tabs = "".join('<button data-g="%s">%s</button>' % (html.escape(g), html.escape(g)) for g in ["すべて"] + genres)
    return PAGE.replace("{{UPDATED}}", jst).replace("{{TABS}}", tabs).replace("{{BODY_HERO}}", hero).replace("{{BODY}}", body)

PAGE = """<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ニュースまとめ</title><style>
:root{--bg:#f6f5f1;--card:#fff;--tx:#1d1d1b;--mut:#6b6a66;--ac:#c2410c;--bd:#e2e0d9}
@media(prefers-color-scheme:dark){:root{--bg:#161615;--card:#212120;--tx:#f0efe9;--mut:#a09f98;--ac:#fb923c;--bd:#333331}}
body{margin:0;background:var(--bg);color:var(--tx);font:16px/1.6 "Hiragino Sans","Noto Sans JP",system-ui,sans-serif}
main{max-width:820px;margin:0 auto;padding:20px 16px 48px}h1{font-size:22px;margin:0}.sub{color:var(--mut);font-size:13px;margin:2px 0 16px}
a{color:inherit;text-decoration:none}a:hover{text-decoration:underline}
.hero{background:var(--card);border:1px solid var(--bd);border-left:5px solid var(--ac);border-radius:12px;padding:18px;margin-bottom:14px}
.tag{font-size:12px;color:var(--ac);font-weight:700}.hero h2{font-size:21px;margin:4px 0 8px;line-height:1.4}
.sum{margin:0 0 8px;font-size:14px;color:var(--mut)}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px}.tabs button{border:1px solid var(--bd);background:var(--card);color:var(--tx);border-radius:99px;padding:6px 14px;font-size:14px;cursor:pointer}
.tabs button.on{background:var(--ac);color:#fff;border-color:var(--ac)}
.item{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:12px 16px;margin-bottom:10px;display:flex;gap:14px}
.rank{font-size:22px;font-weight:800;color:var(--ac);min-width:30px}.item h3{font-size:16px;margin:0 0 4px;line-height:1.45}
.meta{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:12px}.g{color:var(--ac);font-weight:700}
.chip{border:1px solid var(--bd);border-radius:6px;padding:1px 8px}.bar{height:6px;width:90px;background:var(--bd);border-radius:3px;overflow:hidden}.bar i{display:block;height:100%;background:var(--ac)}
.note{font-size:12px;color:var(--mut);margin-top:22px}
</style></head><body><main><h1>📰 ニュースまとめ</h1><div class="sub">最終更新 {{UPDATED}}(日本時間)・毎朝自動更新</div>
{{BODY_HERO}}<div class="tabs" id="tabs">{{TABS}}</div><div id="list">{{BODY}}</div>
<div class="note">重要度は、各媒体の掲載順位と、複数媒体で報じられているかどうかから自動計算した目安です。要約がある場合はAIが見出しから作成したもので、詳細はリンク先をご確認ください。</div></main>
<script>
var cur="すべて",tabs=document.querySelectorAll("#tabs button"),items=document.querySelectorAll(".item");
function show(){var n=0;items.forEach(function(e){var ok=cur==="すべて"?true:(e.dataset.g===cur&&!e.dataset.x);
 e.style.display=ok?"":"none";if(ok){n++;e.querySelector(".rank").textContent=n}});
 tabs.forEach(function(b){b.classList.toggle("on",b.dataset.g===cur)})}
tabs.forEach(function(b){b.onclick=function(){cur=b.dataset.g;show()}});show();
</script></body></html>"""

if __name__ == "__main__":
    os.makedirs("docs", exist_ok=True)
    cl = collect()
    enrich(cl)
    page = render(cl)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(page)
    print("生成しました:", OUT)
