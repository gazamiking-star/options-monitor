import json, os, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
KST = timezone(timedelta(hours=9))

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0 options-monitor/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def top(rows, key, n=5):
    return sorted(rows, key=lambda r: r.get(key) or 0, reverse=True)[:n]

def summarize(raw):
    rows, spot = raw['rows'], float(raw['spot'])
    atm = min(rows, key=lambda r: abs(float(r['strike'])-spot))
    nearby = [r for r in rows if spot*0.85 <= float(r['strike']) <= spot*1.15]
    cw, pw = top(rows,'callOI',1)[0], top(rows,'putOI',1)[0]
    ncw, npw = top(nearby,'callOI',1)[0], top(nearby,'putOI',1)[0]
    return {
      'symbol':raw['symbol'],'name':raw.get('name'),'spot':spot,'expiry':raw.get('expiry'),'dte':raw.get('dte'),
      'maxPain':raw.get('maxPain'),'distance_to_max_pain_pct':round((float(raw['maxPain'])/spot-1)*100,2),
      'atm_strike':atm.get('strike'),'atm_call_iv':atm.get('callIV'),'atm_put_iv':atm.get('putIV'),
      'atm_gamma':(atm.get('call') or {}).get('gamma'),
      'call_wall_all':{'strike':cw.get('strike'),'oi':cw.get('callOI')},
      'put_wall_all':{'strike':pw.get('strike'),'oi':pw.get('putOI')},
      'call_wall_near':{'strike':ncw.get('strike'),'oi':ncw.get('callOI')},
      'put_wall_near':{'strike':npw.get('strike'),'oi':npw.get('putOI')},
      'top_call_oi':[{'strike':r['strike'],'oi':r.get('callOI',0)} for r in top(rows,'callOI')],
      'top_put_oi':[{'strike':r['strike'],'oi':r.get('putOI',0)} for r in top(rows,'putOI')],
      'top_call_volume':[{'strike':r['strike'],'vol':r.get('callVol',0)} for r in top(rows,'callVol')],
      'top_put_volume':[{'strike':r['strike'],'vol':r.get('putVol',0)} for r in top(rows,'putVol')],
      'captured_at_kst':datetime.now(KST).isoformat(timespec='seconds')
    }

def pct(a,b):
    return None if not a else (b/a-1)*100

def changes(old,new):
    if not old: return []
    out=[]
    sm=pct(old.get('spot'),new.get('spot'))
    if sm is not None and abs(sm)>=CFG['alert']['spot_move_pct']: out.append(f"현물 {sm:+.2f}%")
    if old.get('maxPain')!=new.get('maxPain'): out.append(f"맥스페인 {old.get('maxPain')}→{new.get('maxPain')}")
    for side in ('call_wall_near','put_wall_near'):
        o,n=old.get(side,{}),new.get(side,{})
        if o.get('strike')!=n.get('strike'): out.append(f"{side} {o.get('strike')}→{n.get('strike')}")
        m=pct(o.get('oi'),n.get('oi'))
        if m is not None and abs(m)>=CFG['alert']['wall_oi_change_pct']: out.append(f"{side} OI {m:+.1f}%")
    for key in ('atm_call_iv','atm_put_iv'):
        if old.get(key) is not None and new.get(key) is not None:
            d=(new[key]-old[key])*100
            if abs(d)>=CFG['alert']['atm_iv_change_points']: out.append(f"{key} {d:+.1f}pt")
    return out

def telegram(text):
    token, chat=os.getenv('TELEGRAM_BOT_TOKEN'), os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat: return
    body=urllib.parse.urlencode({'chat_id':chat,'text':text}).encode()
    urllib.request.urlopen(urllib.request.Request(f'https://api.telegram.org/bot{token}/sendMessage',data=body),timeout=20).read()

def dashboard(items):
    cards=[]
    for s in items:
        cards.append(f"<section><h2>{s['symbol']}</h2><b>Spot</b> {s['spot']} · <b>Max Pain</b> {s['maxPain']} ({s['distance_to_max_pain_pct']:+.2f}%)<br><b>근접 Call Wall</b> {s['call_wall_near']['strike']} / OI {s['call_wall_near']['oi']}<br><b>근접 Put Wall</b> {s['put_wall_near']['strike']} / OI {s['put_wall_near']['oi']}<br><b>ATM</b> {s['atm_strike']} · Call IV {s['atm_call_iv']} · Put IV {s['atm_put_iv']}<br><small>{s['captured_at_kst']}</small></section>")
    html="""<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>Options Monitor</title><style>body{font-family:system-ui;max-width:900px;margin:30px auto;padding:0 16px;background:#111;color:#eee}section{border:1px solid #444;border-radius:14px;padding:18px;margin:14px 0;background:#1b1b1b}h1,h2{margin-top:0}small{color:#aaa}</style><h1>무료 옵션 모니터</h1>"""+''.join(cards)
    (ROOT/'docs/index.html').write_text(html,encoding='utf-8')

def main():
    stamp=datetime.now(KST).strftime('%Y%m%d_%H%M%S'); alerts=[]; items=[]
    for symbol in CFG['symbols']:
        lp=ROOT/'data/latest'/f'{symbol}.json'
        old=json.loads(lp.read_text(encoding='utf-8')) if lp.exists() else None
        new=summarize(fetch(CFG['api_template'].format(symbol=symbol)))
        lp.write_text(json.dumps(new,ensure_ascii=False,indent=2),encoding='utf-8')
        hd=ROOT/'data/history'/symbol; hd.mkdir(parents=True,exist_ok=True)
        (hd/f'{stamp}.json').write_text(json.dumps(new,ensure_ascii=False,indent=2),encoding='utf-8')
        ch=changes(old,new)
        if ch: alerts.append(f"[{symbol}] "+' | '.join(ch))
        items.append(new)
    dashboard(items)
    if alerts: telegram('옵션 변화 감지\n'+'\n'.join(alerts))
    print(json.dumps({'updated':[x['symbol'] for x in items],'alerts':alerts},ensure_ascii=False))

if __name__=='__main__': main()
