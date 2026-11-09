#!/usr/bin/env python3
"""Twice-daily headline aggregator using GDELT DOC 2.0 public news index."""
import datetime as dt
import hashlib
import html
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

from deep_translator import GoogleTranslator

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data"/"news.json"
API="https://api.gdeltproject.org/api/v2/doc/doc"
HK=ZoneInfo("Asia/Hong_Kong")
QUERIES=[
# Global affairs, major economic policy, international shocks and science/disasters.
("world", '(ceasefire OR sanctions OR diplomacy OR summit OR election OR war)', 2, 75),
("world", '("United Nations" OR "climate summit" OR earthquake OR "global economy")', 2, 65),
("world", '(international OR world) (conflict OR trade OR politics OR economy)', 2, 65),
("world", '(国际 OR 全球 OR 联合国 OR 外交 OR 战争 OR 地震)', 2, 65),
# Fallback youth reporting when direct public platform boards cannot be accessed.
("youth", '("小红书" OR "抖音") (热搜 OR 热议 OR 流行 OR 走红)', 3, 50),
("concert", '(演唱会 OR 巡演 OR 音乐节 OR 开票) (香港 OR 深圳 OR 广州 OR 澳门)', 14, 55),
("concert", '(BLACKPINK OR BTS OR aespa OR "Taylor Swift" OR "Billie Eilish" OR "周杰伦" OR "邓紫棋") (concert OR tour OR tickets OR 演唱会)', 14, 55),
("tech", '("artificial intelligence" OR "AI model" OR OpenAI OR Nvidia)', 3, 55),
("gaming", '(esports OR Valorant OR "Counter-Strike" OR Steam)', 4, 55),
("entertainment", '(K-pop OR cinema OR "pop music" OR movie)', 4, 55),
("finance", '(stocks OR inflation OR "central bank" OR "global economy")', 3, 55),
("sports", '(football OR basketball OR tennis OR "Formula 1")', 3, 55),
]
LIMIT={"world":7,"youth":3,"concert":3,"tech":3,"gaming":3,"entertainment":3,"finance":3,"sports":3}

# Search relevance is only a signal, not a claim about an artist's popularity.
YOUNG_ARTISTS = ("周杰伦", "林俊杰", "邓紫棋", "陈奕迅", "告五人", "五月天", "陶喆",
                 "薛之谦", "许嵩", "林家谦", "张敬轩", "MC张天赋", "陈蕾", "MIRROR",
                 "BLACKPINK", "BTS", "AESPA", "SEVENTEEN", "STRAY KIDS",
                 "TWICE", "IVE", "ENHYPEN", "TAYLOR SWIFT", "BILLIE EILISH",
                 "THE WEEKND", "OLIVIA RODRIGO", "SABRINA CARPENTER",
                 "DUA LIPA", "BRUNO MARS", "COLDPLAY", "ED SHEERAN")
CONCERT_TERMS = re.compile(r"演唱会|巡演|音乐节|开票|加场|售票|抢票|门票|演出|concert|world tour|live show|music festival|tour dates|tickets",re.I)
REGION_TERMS = re.compile(r"香港|深圳|广州|澳門|澳门|Hong Kong|Shenzhen|Guangzhou|Macau",re.I)
def request(q,days,n):
    params=urllib.parse.urlencode({"query":q,"mode":"ArtList","format":"json","sort":"HybridRel","timespan":str(days)+"d","maxrecords":n})
    req=urllib.request.Request(API+"?"+params,headers={"User-Agent":"WorldPulse/1.0 (news link index)", "Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=24) as res:
        body=res.read(4000000)
    return json.loads(body).get("articles",[])
def plain(s):
    return re.sub(r"\s+"," ",re.sub(r"<[^>]+>","",html.unescape(str(s)))).strip()
def article(item,cat,rank,now,days):
    title=plain(item.get("title",""))
    url=item.get("url","")
    if len(title)<8 or not url.startswith(("https://","http://")):return
    if cat=="concert" and not CONCERT_TERMS.search(title):return
    language=str(item.get("language","")).lower()
    if cat=="youth" and not re.search(r"小红书|抖音|douyin|xiaohongshu",title,re.I):return
    try:seen=dt.datetime.strptime(item.get("seendate",""),"%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
    except (ValueError,TypeError):return
    age=(now-seen).total_seconds()/3600
    if age>days*24 or age< -24:return
    key=re.sub(r"[^\w\u3400-\u9fff]+","",title.lower())
    source=plain(item.get("domain","")) or urllib.parse.urlsplit(url).hostname or "新闻来源"
    return {"id":hashlib.sha1(key.encode()).hexdigest()[:16],"category":cat,"title":title,"original_language":language,"source":source,"url":url,"published_at":seen.isoformat(),"score":round(115-rank*1.2+max(0,22-age/3)+(8 if str(item.get("language","")).lower()=="chinese" else 0)+(22 if cat=="concert" and any(a.lower() in title.lower() for a in YOUNG_ARTISTS) else 0)+(8 if cat=="concert" and REGION_TERMS.search(title) else 0),2)}
class MetaDescription(HTMLParser):
    def __init__(self):
        super().__init__()
        self.description=""
    def handle_starttag(self,tag,attrs):
        if tag.lower()!="meta" or self.description:return
        meta={k.lower():v for k,v in attrs if k and v}
        key=(meta.get("property") or meta.get("name") or "").lower()
        if key in ("og:description","twitter:description","description"):
            self.description=plain(meta.get("content",""))

def get_publisher_description(url):
    """Read only publisher-provided public HTML meta description, not article body."""
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; WorldPulseNews/1.0)","Accept":"text/html"})
        with urllib.request.urlopen(req,timeout=6) as r:
            if "html" not in r.headers.get("Content-Type","").lower():return ""
            charset=r.headers.get_content_charset() or "utf-8"
            body=r.read(110000)
        parser=MetaDescription()
        parser.feed(body.decode(charset,errors="replace"))
        return parser.description
    except (OSError,ValueError,LookupError,UnicodeError):
        return ""

def clean_headline(title):
    # Remove publisher names and split two Chinese clauses only when both are substantive.
    title=re.split(r"\s+[|｜_]\s+|\s+\|\s+| _ ",title,maxsplit=1)[0].strip()
    chunks=re.split(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])|[；;]\s*",title,maxsplit=1)
    if len(chunks)==2 and len(chunks[0])>=12 and len(chunks[1])>=10:
        return chunks[0].strip()
    return title or "新闻动态"

def short_summary(title,headline,description):
    """Extractive summaries only. Never invent facts that are absent from source."""
    desc=plain(description)
    if desc and len(desc)>=26 and desc.lower()!=title.lower():
        # Meta descriptions are short blurbs supplied by the linked publisher.
        desc=re.split(r"(?:相关阅读|点击查看|订阅我们|All rights reserved)",desc,maxsplit=1)[0].strip()
        if len(desc)>155:
            cut=max(desc.rfind("。",0,150),desc.rfind(".",0,150),desc.rfind("；",0,150))
            desc=desc[:cut+1] if cut>50 else desc[:150].rstrip()+"…"
        if len(desc)>=25:return desc,"媒体页面简介"
    # Without source metadata the original headline is the only verified content.
    # A standalone summary is *not* fabricated from a headline.
    if title.strip()!=headline.strip():
        if title.startswith(headline):
            detail=title[len(headline):].strip(" ：:，,；;。|｜_—- ")
            if len(detail)>=10 and len(detail)<=170 and not re.search(r"(网|新闻|日报|传媒|媒体)$",detail):
                return detail,"原标题提炼"
        return "目前仅检索到媒体标题，报道背景及细节请查看原文。","仅有标题"
    return "目前仅检索到媒体标题，报道背景及细节请查看原文。","仅有标题"

# GDELT supplies the language for most indexed articles. We keep English
# and Chinese unchanged, and translate all other identified languages into
# Simplified Chinese. Unsupported source languages are not published untranslated.
LANGUAGE_TAGS={"english","en","eng","chinese","zh","zh-cn","zh-tw","mandarin",
               "cantonese","traditional chinese","simplified chinese"}
CHINESE_TAGS={"chinese","zh","zh-cn","zh-tw","mandarin","cantonese",
              "traditional chinese","simplified chinese"}
def source_language(item):
    raw=str(item.get("original_language") or "").strip().lower()
    if raw:return raw
    title=item.get("title","")
    if re.search(r"[\u3040-\u30ff]",title):return "japanese"
    if re.search(r"[\uac00-\ud7af]",title):return "korean"
    if re.search(r"[\u0400-\u052f]",title):return "russian"
    if re.search(r"[\u0600-\u06ff]",title):return "arabic"
    if re.search(r"[\u0e00-\u0e7f]",title):return "thai"
    if re.search(r"[\u0370-\u03ff]",title):return "greek"
    # Don't guess Latin-script languages from short ambiguous headlines.
    return "unknown"

def to_simplified(text):
    if not text or not text.strip():return text
    translated=GoogleTranslator(source="auto",target="zh-CN").translate(text)
    if not isinstance(translated,str) or not translated.strip():
        raise ValueError("translation was empty")
    # If a translation service returns unchanged foreign-language text, this
    # does not count as a successful translation.
    if plain(translated).casefold()==plain(text).casefold():
        raise ValueError("translation unchanged")
    return plain(translated)

def translate_news(items,previous):
    cache={}
    for item in previous.get("items",[]):
        if item.get("translation_status")=="translated" and item.get("original_title"):
            cache[item["original_title"]]=(item.get("headline"),item.get("summary"),
                                            item.get("summary_basis","媒体页面简介"))
    failed=0
    for item in items:
        if item.get("source_type")=="social_trend":continue
        lang=source_language(item)
        item["display_language"]="中文" if lang in CHINESE_TAGS else ("English" if lang in ("english","en","eng") else lang)
        # An unidentified Latin headline could be English. We never translate
        # it based on a guess; known non-Chinese/English languages do translate.
        if lang in LANGUAGE_TAGS or lang=="unknown":
            item["translation_status"]="original"
            continue
        original=item["title"]
        item["original_title"]=original
        prior=cache.get(original)
        if prior:
            item["headline"],item["summary"],item["summary_basis"]=prior
            item["translation_status"]="translated"
            continue
        try:
            new_title=to_simplified(item.get("headline") or original)
            old_summary=item.get("summary","")
            basis=item.get("summary_basis","")
            if basis in ("媒体页面简介","原标题提炼") and old_summary:
                new_summary=to_simplified(old_summary)
            else:
                new_summary=old_summary
            item["headline"]=new_title
            item["summary"]=new_summary
            item["summary_basis"]=(basis or "来源标题")+" · 简体中文译文"
            item["translation_status"]="translated"
        except Exception as exc:
            # Keep raw text in original_title for auditing, but avoid showing
            # a non-Chinese/English headline as though it had been translated.
            item["translation_status"]="failed"
            failed+=1
            logging.warning("Translation failed for %s: %s",original[:55],exc)
        time.sleep(0.3)
    return [x for x in items if x.get("translation_status")!="failed"],failed

def add_editorial_fields(items):
    # Fetch a modest number of publisher snippets in parallel to limit load.
    with ThreadPoolExecutor(max_workers=6) as pool:
        selected=[x for x in items if x.get("source_type")!="social_trend"][:40]
        descriptions=list(pool.map(lambda x:get_publisher_description(x["url"]),selected))
    by_id={x["id"]:descriptions[i] for i,x in enumerate(selected)}
    for item in items:
        if item.get("source_type")=="social_trend":
            continue
        original=item["title"]
        headline=clean_headline(original)
        summary,basis=short_summary(original,headline,by_id.get(item["id"],""))
        item["headline"]=headline
        item["summary"]=summary
        item["summary_basis"]=basis
    return items

class PublicHotlist(HTMLParser):
    """Collect visible link titles and screen text, ignoring scripts/styles."""
    def __init__(self):
        super().__init__()
        self.skip=0
        self.text=[]
        self.links=[]
        self.href=None
        self.link_text=[]
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript"):
            self.skip+=1
            return
        if self.skip:return
        if tag=="a":
            self.href=dict(attrs).get("href","")
            self.link_text=[]
    def handle_data(self,data):
        if self.skip:return
        value=plain(data)
        if not value:return
        self.text.append(value)
        if self.href is not None:self.link_text.append(value)
    def handle_endtag(self,tag):
        if tag in ("script","style","noscript"):
            self.skip=max(0,self.skip-1)
            return
        if tag=="a" and self.href is not None:
            name=" ".join(self.link_text).strip()
            if name and self.href:self.links.append((name,self.href))
            self.href=None
            self.link_text=[]
def read_hotlist(url):
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; WorldPulse/1.0)","Accept":"text/html"})
    with urllib.request.urlopen(req,timeout=13) as res:
        charset=res.headers.get_content_charset() or "utf-8"
        payload=res.read(700000).decode(charset,errors="replace")
    parser=PublicHotlist()
    parser.feed(payload)
    return parser

def is_youth_topic(title):
    # Favor youth culture and everyday-life topics, not routine general news.
    return bool(re.search(r"游戏|电竞|LOL|BLG|T1|Faker|穿搭|出片|拍照|旅游|旅行|美食|音乐|演唱会|影视|电影|新剧|电视剧|偶像|追星|美妆|校园|大学|打工|上班|网红|博主|流行|热梗|舞蹈|萌宠|宠物|恋爱|NBA|篮球|足球|潮流|攻略|拍摄|发型|秋冬|美景|翻唱|AI|原神|三角洲|CS2|无畏契约|歌手|拼豆|二次元|二创|音乐节|装扮|时尚|颜值",title,re.I))
def hot_item(platform,title,url,rank,now,via):
    title=plain(title)
    if not 5<=len(title)<=90:return
    code=platform+"|"+title
    return {"id":hashlib.sha1(code.encode()).hexdigest()[:16],
            "category":"youth","platform":platform,"source_type":"social_trend",
            "title":title,"headline":title,
            "summary":f"该话题出现在{platform}公开热榜（采集时位列第{rank}名）。这里只展示话题，不代表相关说法已得到核实。",
            "summary_basis":"平台话题速览",
            "source":via,"url":url,"published_at":now.isoformat(),
            "score":200-rank}
def fetch_douyin(now):
    # Official Douyin public hot-billboard page; can change or block automated access.
    link="https://www.iesdouyin.com/share/billboard/?id=0&share_app_name=douyin"
    p=read_hotlist(link)
    words=p.text
    results=[]
    for idx,x in enumerate(words):
        m=re.fullmatch(r"(\d{1,2})\.",x)
        if not m:continue
        rank=int(m.group(1))
        if not 1<=rank<=50 or idx+1>=len(words):continue
        name=words[idx+1]
        if not re.search(r"[\u3400-\u9fffA-Za-z]",name):continue
        row=hot_item("抖音",name,link,rank,now,"抖音公开热点榜")
        if row:results.append(row)
    if len(results)<3:raise ValueError("Douyin public chart was not readable")
    return results
def fetch_xiaohongshu(now):
    # Third-party public index, attributed as such; links go to Xiaohongshu search.
    link="https://www.tunbang.com/hot/xiaohongshu"
    p=read_hotlist(link)
    results=[]
    for name,href in p.links:
        absolute=urllib.parse.urljoin(link,href)
        host=(urllib.parse.urlsplit(absolute).hostname or "").lower()
        if not (host=="xiaohongshu.com" or host.endswith(".xiaohongshu.com")):continue
        if not 5<=len(name)<=70:continue
        row=hot_item("小红书",name,absolute,len(results)+1,now,"豚榜·小红书公开榜单聚合")
        if row:results.append(row)
    if len(results)<3:raise ValueError("Xiaohongshu trend list was not readable")
    return results[:20]
def get_youth_trends(now):
    feeds=[]
    for name,func in (("Douyin",fetch_douyin),("Xiaohongshu",fetch_xiaohongshu)):
        try:
            rows=func(now)
            feeds.append(rows)
            logging.info("%s hot topics: %d",name,len(rows))
        except (OSError,ValueError,UnicodeError) as exc:
            logging.warning("%s trends unavailable: %s",name,exc)
            feeds.append([])
    dy,xhs=feeds
    # Aim for two Douyin stories plus one Xiaohongshu story, balancing two sites.
    selected=[]
    for pool,quota in ((dy,2),(xhs,1)):
        preferred=[i for i in pool if is_youth_topic(i["title"])]
        selected.extend((preferred or pool)[:quota])
    if len(selected)<3:
        fallback=[i for i in dy+xhs if i["id"] not in {x["id"] for x in selected}]
        selected.extend(fallback[:3-len(selected)])
    return selected[:3]

def main():
    logging.basicConfig(level=logging.INFO,format="%(levelname)s %(message)s")
    now=dt.datetime.now(dt.timezone.utc)
    old={}
    if OUT.exists():
        try:old=json.loads(OUT.read_text(encoding="utf8"))
        except (ValueError,OSError):pass
    groups={cat:[] for cat in LIMIT}
    groups["youth"].extend(get_youth_trends(now))
    ok=bad=0
    for i,(cat,q,days,n) in enumerate(QUERIES):
        if i:time.sleep(5.25)
        try:
            rows=request(q,days,n)
            for j,row in enumerate(rows):
                x=article(row,cat,j,now,days)
                if x:groups[cat].append(x)
            ok+=1
            logging.info("%s: %s hits",cat,len(rows))
        except (OSError,ValueError,TypeError) as exc:
            bad+=1
            logging.warning("%s: %s",cat,exc)
    # Preserve recent verified stories when a public index is temporarily unavailable.
    for cat,quota in LIMIT.items():
        if len(groups[cat])>=quota:continue
        for previous in old.get("items",[]):
            if previous.get("category")!=cat:continue
            if cat=="youth" and previous.get("platform") not in ("抖音","小红书"):continue
            try:
                age=(now-dt.datetime.fromisoformat(previous["published_at"])).total_seconds()/3600
                if age<0 or age>36:continue
            except (KeyError,TypeError,ValueError):continue
            groups[cat].append(previous)
    out=[]
    global_seen=set()
    for cat,items in groups.items():
        seen=set()
        for x in sorted(items,key=lambda x:x["score"],reverse=True):
            if x["id"] in seen or x["id"] in global_seen:continue
            seen.add(x["id"]);global_seen.add(x["id"])
            out.append(x)
            if len(seen)>=LIMIT[cat]:break
    # Make the home selection deterministic: global stories first, then youth trends.
    out.sort(key=lambda x:(list(LIMIT).index(x["category"]),-x["score"]))
    if out:
        add_editorial_fields(out)
        out,translation_failures=translate_news(out,old)
    else:
        translation_failures=0
    if not out:
        if old.get("items"):
            old["status"]="stale"
            old["notice"]="新闻源暂不可用，正在展示最近一次成功更新的内容。"
            old["last_attempt_at"]=now.astimezone(HK).isoformat()
            OUT.parent.mkdir(parents=True,exist_ok=True)
            OUT.write_text(json.dumps(old,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        logging.warning("No usable update: only %s articles",len(out))
        return
    hk=now.astimezone(HK)
    payload={"version":1,"status":"partial" if bad else "live","updated_at":hk.isoformat(timespec="seconds"),"edition":"早报" if 9<=hk.hour<21 else "晚报","timezone":"Asia/Hong_Kong","notice":"部分新闻源未响应，报道可能不完整。" if bad else "","methodology":"首页全球 7 篇、内地年轻人热点 3 篇，其他栏目各最多 3 篇。中文与英文原样显示；其他已识别语种翻译成简体中文，无法翻译的条目不显示。世界新闻来自 GDELT，摘要不编造未核实细节。","feed_successes":ok,"feed_failures":bad,"translation_failures":translation_failures,"items":out}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    logging.info("Saved %s articles",len(out))
if __name__=="__main__":main()
