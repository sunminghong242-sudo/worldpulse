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
("concert", '(concert OR "world tour" OR "music festival") ("Hong Kong" OR Shenzhen OR Guangzhou OR Macau)', 7, 35),
("concert", '(concert OR "music festival" OR "ticket sales") sourcelang:chinese', 7, 35),
("concert", '("world tour" OR "concert tickets" OR "live music festival")', 7, 25),
("tech", '("artificial intelligence" OR "AI model" OR OpenAI OR Nvidia)', 3, 30),
("tech", '(robotics OR artificial intelligence) sourcelang:chinese', 3, 25),
("gaming", '(esports OR Valorant OR "Counter-Strike" OR "video games")', 4, 35),
("gaming", '(Nintendo OR Steam OR PlayStation OR esports) sourcelang:chinese', 4, 25),
("entertainment", '(cinema OR "K-pop" OR movie OR "pop music")', 4, 30),
("entertainment", '(movie OR musician OR idol) sourcelang:chinese', 4, 25),
("finance", '(stocks OR inflation OR "central bank" OR "global economy")', 3, 30),
("sports", '(football OR basketball OR tennis OR "Formula 1")', 3, 30),
]
LIMIT={"world":18,"youth":12,"concert":18,"tech":12,"gaming":12,"entertainment":12,"finance":10,"sports":10}
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
    try:seen=dt.datetime.strptime(item.get("seendate",""),"%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
    except (ValueError,TypeError):return
    age=(now-seen).total_seconds()/3600
    if age>days*24 or age< -24:return
    key=re.sub(r"[^\w\u3400-\u9fff]+","",title.lower())
    source=plain(item.get("domain","")) or urllib.parse.urlsplit(url).hostname or "新闻来源"
    return {"id":hashlib.sha1(key.encode()).hexdigest()[:16],"category":cat,"title":title,"source":source,"url":url,"published_at":seen.isoformat(),"score":round(115-rank*1.2+max(0,22-age/3)+(8 if str(item.get("language","")).lower()=="chinese" else 0),2)}
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
    payload={"version":1,"status":"partial" if bad else "live","updated_at":hk.isoformat(timespec="seconds"),"edition":"早报" if 9<=hk.hour<21 else "晚报","timezone":"Asia/Hong_Kong","notice":"部分新闻源未响应，报道可能不完整。" if bad else "","methodology":"GDELT 新闻索引的搜索相关性和收录时间；非全网热度真实排行。","feed_successes":ok,"feed_failures":bad,"items":out}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    logging.info("Saved %s articles",len(out))
if __name__=="__main__":main()
