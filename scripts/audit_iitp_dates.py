import json, re, time, ssl, urllib.request
from datetime import datetime

ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
data = json.load(open(r"D:\RFP-Targeter\data\raw\audit\iitp.json", encoding="utf-8"))

MONTHS = {m:i for i,m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"],1)}

def site_date(html):
    # last dt/dd pair labelled 작성일 -> 'Jun 24, 2026'
    pairs = re.findall(r'<dt class="tit">\s*([^<]*?)\s*</dt>\s*<dd class="con">\s*([^<]*?)\s*</dd>', html)
    for label,val in pairs:
        m = re.match(r'([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})', val.strip())
        if m:
            mon = MONTHS.get(m.group(1))
            if mon:
                return f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}"
    return None

results=[]
for i,row in enumerate(data):
    url=row["url"]
    try:
        req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
        html=urllib.request.urlopen(req, context=ctx, timeout=90).read().decode('utf-8','replace')
        sd=site_date(html)
        results.append({"id":row["id"],"title":row["title"],"posted_at":row["posted_at"],"site_date":sd,"ok":sd is not None})
    except Exception as e:
        results.append({"id":row["id"],"title":row["title"],"posted_at":row["posted_at"],"site_date":None,"ok":False,"err":str(e)})
    time.sleep(0.7)

json.dump(results, open(r"D:\RFP-Targeter\data\raw\audit\iitp_result.json","w",encoding="utf-8"), ensure_ascii=False, indent=2)

checked=sum(1 for r in results if r["ok"])
mism=[r for r in results if r["ok"] and r["site_date"]!=r["posted_at"]]
unr=[r for r in results if not r["ok"]]
print("TOTAL",len(results),"CHECKED",checked,"MISMATCH",len(mism),"UNREACHABLE",len(unr))
for r in mism:
    d=(datetime.fromisoformat(r["site_date"])-datetime.fromisoformat(r["posted_at"])).days
    print("MISM",r["id"],r["posted_at"],"->",r["site_date"],"diff",d)
for r in unr:
    print("UNR",r["id"],r.get("err"))
