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

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data"/"news.json"
API="https://api.gdeltproject.org/api/v2/doc/doc"
HK=ZoneInfo("Asia/Hong_Kong")
QUERIES=[
("world", '(election OR diplomacy OR summit OR "global economy")', 3, 35),
("world", '(diplomacy OR geopolitics OR economy) sourcelang:chinese', 3, 25),
("youth", '(viral OR influencer OR TikTok OR Instagram OR "social media")', 3, 30),
("youth", '(TikTok OR "K-pop" OR anime OR streetwear) sourcelang:chinese', 4, 25),
# Concerts for pop-loving listeners aged approximately 20-30. Prioritize HK/Guangdong.
("concert", '(演唱会 OR 巡演 OR 音乐节 OR 开票) (香港 OR 深圳 OR 广州 OR 澳门)', 14, 45),
("concert", '("周杰伦" OR "林俊杰" OR "邓紫棋" OR "陈奕迅" OR "告五人" OR "五月天" OR "陶喆" OR "薛之谦") (演唱会 OR 巡演 OR 开票)', 14, 45),
("concert", '(BLACKPINK OR BTS OR aespa OR SEVENTEEN OR "Taylor Swift" OR "Billie Eilish" OR "The Weeknd" OR "Olivia Rodrigo") (concert OR tour OR tickets)', 14, 45),
("concert", '(concert OR "world tour" OR "music festival") ("Hong Kong" OR Shenzhen OR Guangzhou OR Macau)', 14, 35),
("tech", '("artificial intelligence" OR "AI model" OR OpenAI OR Nvidia)', 3, 30),
("tech", '(robotics OR artificial intelligence) sourcelang:chinese', 3, 25),
("gaming", '(esports OR Valorant OR "Counter-Strike" OR "video games")', 4, 35),
("gaming", '(Nintendo OR Steam OR PlayStation OR esports) sourcelang:chinese', 4, 25),
("entertainment", '(cinema OR "K-pop" OR movie OR "pop music")', 4, 30),
("entertainment", '(movie OR musician OR idol) sourcelang:chinese', 4, 25),
("finance", '(stocks OR inflation OR "central bank" OR "global economy")', 3, 30),
("sports", '(football OR basketball OR tennis OR "Formula 1")', 3, 30),
]
LIMIT={"world":18,"youth":12,"concert":24,"tech":12,"gaming":12,"entertainment":12,"finance":10,"sports":10}
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
    try:seen=dt.datetime.strptime(item.get("seendate",""),"%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
    except (ValueError,TypeError):return
    age=(now-seen).total_seconds()/3600
    if age>days*24 or age< -24:return
    key=re.sub(r"[^\w\u3400-\u9fff]+","",title.lower())
    source=plain(item.get("domain","")) or urllib.parse.urlsplit(url).hostname or "新闻来源"
    return {"id":hashlib.sha1(key.encode()).hexdigest()[:16],"category":cat,"title":title,"source":source,"url":url,"published_at":seen.isoformat(),"score":round(115-rank*1.2+max(0,22-age/3)+(8 if str(item.get("language","")).lower()=="chinese" else 0)+(22 if cat=="concert" and any(a.lower() in title.lower() for a in YOUNG_ARTISTS) else 0)+(8 if cat=="concert" and REGION_TERMS.search(title) else 0),2)}
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
    # Remove the publisher's byline after common vertical-bar/underscore separators.
    title=re.split(r"\\s+[|｜_]\\s+|\\s+\\|\\s+| _ ",title,maxsplit=1)[0].strip()
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
        return title.strip()[:170],"原标题速览"
    return "目前仅检索到媒体标题，报道背景及细节请查看原文。","仅有标题"

def add_editorial_fields(items):
    # Fetch a modest number of publisher snippets in parallel to limit load.
    with ThreadPoolExecutor(max_workers=6) as pool:
        selected=items[:65]
        descriptions=list(pool.map(lambda x:get_publisher_description(x["url"]),selected))
    by_id={x["id"]:descriptions[i] for i,x in enumerate(selected)}
    for item in items:
        original=item["title"]
        headline=clean_headline(original)
        summary,basis=short_summary(original,headline,by_id.get(item["id"],""))
        item["headline"]=headline
        item["summary"]=summary
        item["summary_basis"]=basis
    return items

def main():
    logging.basicConfig(level=logging.INFO,format="%(levelname)s %(message)s")
    now=dt.datetime.now(dt.timezone.utc)
    old={}
    if OUT.exists():
        try:old=json.loads(OUT.read_text(encoding="utf8"))
        except (ValueError,OSError):pass
    groups={cat:[] for cat in LIMIT}
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
    out=[]
    global_seen=set()
    for cat,items in groups.items():
        seen=set()
        for x in sorted(items,key=lambda x:x["score"],reverse=True):
            if x["id"] in seen or x["id"] in global_seen:continue
            seen.add(x["id"]);global_seen.add(x["id"])
            out.append(x)
            if len(seen)>=LIMIT[cat]:break
    out.sort(key=lambda x:x["score"],reverse=True)
    if out:
        add_editorial_fields(out)
    if len(out)<10:
        if old.get("items"):
            old["status"]="stale"
            old["notice"]="新闻源暂不可用，正在展示最近一次成功更新的内容。"
            old["last_attempt_at"]=now.astimezone(HK).isoformat()
            OUT.parent.mkdir(parents=True,exist_ok=True)
            OUT.write_text(json.dumps(old,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        logging.warning("No usable update: only %s articles",len(out))
        return
    hk=now.astimezone(HK)
    payload={"version":1,"status":"partial" if bad else "live","updated_at":hk.isoformat(timespec="seconds"),"edition":"早报" if 9<=hk.hour<21 else "晚报","timezone":"Asia/Hong_Kong","notice":"部分新闻源未响应，报道可能不完整。" if bad else "","methodology":"GDELT 新闻索引排序；标题来自原报道，摘要优先采用媒体网页公开简介，不可获取时明确标注仅有标题，不编造细节。","feed_successes":ok,"feed_failures":bad,"items":out}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    logging.info("Saved %s articles",len(out))
if __name__=="__main__":main()
