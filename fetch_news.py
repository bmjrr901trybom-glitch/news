"""RSSからニュースを集め、重要度順のトップページ docs/index.html を生成する。"""
import html, re, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# (表示名, RSSのURL, 重み)  ※URLが変わった場合はここを直す
FEEDS = [
    ("NHK 主要", "https://www3.nhk.or.jp/rss/news/cat0.xml", 1.0),
    ("NHK 国際", "https://www3.nhk.or.jp/rss/news/cat6.xml", 0.8),
    ("Yahoo!ニュース 主要", "https://news.yahoo.co.jp/rss/topics/top-picks.xml", 1.0),
    ("朝日新聞", "https://www.asahi.com/rss/asahi/newsheadlines.rdf", 0.9),
]
PER_FEED = 15      # 各フィードから使う件数
SAME_TOPIC = 0.30  # 見出しの類似度がこれ以上なら同じ話題とみなす
SHOW = 12          # 表示する件数
OUT = "docs/index.html"

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 news-aggregator"})
    with urllib.request.urlopen(req, timeout=20) as r:
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
    clusters = []  # {title, link, g, sources{name:link}, score}
    for name, url, w in FEEDS:
        try:
            items = parse(fetch(url))[:PER_FEED]
        except Exception as e:
            print("取得失敗:", name, e)
            continue
        for rank, (title, link) in enumerate(items):
            pts = w * (PER_FEED - rank) / PER_FEED  # 上位ほど高得点
            g = grams(title)
            for c in clusters:
                if name not in c["sources"] and sim(g, c["g"]) >= SAME_TOPIC:
                    c["sources"][name] = link
                    c["score"] += pts + 1.0         # 複数媒体で報道なら加点
                    break
            else:
                clusters.append({"title": title, "link": link, "g": g,
                                 "sources": {name: link}, "score": pts})
    clusters.sort(key=lambda c: -c["score"])
    return clusters[:SHOW]

def chips(c):
    return "".join('<a class="chip" target="_blank" rel="noopener" href="%s">%s</a>'
                   % (html.escape(l), html.escape(n)) for n, l in c["sources"].items())

def render(cl):
    jst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y年%m月%d日 %H:%M")
    mx = max([c["score"] for c in cl] + [1])
    if not cl:
        body = "<p>ニュースを取得できませんでした。</p>"
    else:
        t = cl[0]
        body = ('<div class="hero"><div class="tag">TOP STORY</div><h2><a href="%s" target="_blank" rel="noopener">%s</a></h2><div class="meta">%s</div></div>'
                % (html.escape(t["link"]), html.escape(t["title"]), chips(t)))
        for i, c in enumerate(cl[1:], 1):
            body += ('<div class="item"><div class="rank">%d</div><div><h3><a href="%s" target="_blank" rel="noopener">%s</a></h3>'
                     '<div class="meta"><span class="bar"><i style="width:%d%%"></i></span>%s</div></div></div>'
                     % (i, html.escape(c["link"]), html.escape(c["title"]), 100 * c["score"] / mx, chips(c)))
    return PAGE.replace("{{UPDATED}}", jst).replace("{{BODY}}", body)

PAGE = """<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ニュースまとめ</title><style>
:root{--bg:#f6f5f1;--card:#fff;--tx:#1d1d1b;--mut:#6b6a66;--ac:#c2410c;--bd:#e2e0d9}
@media(prefers-color-scheme:dark){:root{--bg:#161615;--card:#212120;--tx:#f0efe9;--mut:#a09f98;--ac:#fb923c;--bd:#333331}}
body{margin:0;background:var(--bg);color:var(--tx);font:16px/1.6 "Hiragino Sans","Noto Sans JP",system-ui,sans-serif}
main{max-width:820px;margin:0 auto;padding:20px 16px 48px}h1{font-size:22px;margin:0}.sub{color:var(--mut);font-size:13px;margin:2px 0 16px}
a{color:inherit;text-decoration:none}a:hover{text-decoration:underline}
.hero{background:var(--card);border:1px solid var(--bd);border-left:5px solid var(--ac);border-radius:12px;padding:18px;margin-bottom:14px}
.tag{font-size:12px;color:var(--ac);font-weight:700}.hero h2{font-size:21px;margin:4px 0 10px;line-height:1.4}
.item{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:12px 16px;margin-bottom:10px;display:flex;gap:14px}
.rank{font-size:22px;font-weight:800;color:var(--ac);min-width:30px}.item h3{font-size:16px;margin:0 0 6px;line-height:1.45}
.meta{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:12px}
.chip{border:1px solid var(--bd);border-radius:6px;padding:1px 8px}.bar{height:6px;width:90px;background:var(--bd);border-radius:3px;overflow:hidden}.bar i{display:block;height:100%;background:var(--ac)}
.note{font-size:12px;color:var(--mut);margin-top:22px}
</style></head><body><main><h1>📰 ニュースまとめ</h1><div class="sub">最終更新 {{UPDATED}}(日本時間)・毎朝自動更新</div>
{{BODY}}<div class="note">重要度は、各媒体の掲載順位と、複数媒体で報じられているかどうかから自動計算した目安です。見出しのリンク先で内容をご確認ください。</div></main></body></html>"""

if __name__ == "__main__":
    import os
    os.makedirs("docs", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(render(collect()))
    print("生成しました:", OUT)
