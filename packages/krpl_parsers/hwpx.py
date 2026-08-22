"""HWPX(OWPML) 표 추출 — hwptable.tables() 와 동일한 형식(list[list[list[str]]]) 반환"""
import zipfile, re, xml.etree.ElementTree as ET
HP='{http://www.hancom.co.kr/hwpml/2011/paragraph}'

def _celltext(tc):
    return ' '.join(x.strip() for x in
                    (t.text or '' for t in tc.iter(HP+'t')) if x.strip())

def tables(path):
    z=zipfile.ZipFile(path)
    secs=sorted(n for n in z.namelist() if re.search(r'Contents/section\d+\.xml$',n))
    out=[]
    for s in secs:
        root=ET.fromstring(z.read(s))
        for tbl in root.iter(HP+'tbl'):
            nr=int(tbl.get('rowCnt') or 0); nc=int(tbl.get('colCnt') or 0)
            cells=[]
            for tr in tbl.findall(HP+'tr'):
                for tc in tr.findall(HP+'tc'):
                    a=tc.find(HP+'cellAddr'); sp=tc.find(HP+'cellSpan')
                    col=int(a.get('colAddr')) if a is not None else 0
                    row=int(a.get('rowAddr')) if a is not None else 0
                    cs=int(sp.get('colSpan')) if sp is not None else 1
                    rs=int(sp.get('rowSpan')) if sp is not None else 1
                    cells.append((col,row,cs,rs,_celltext(tc)))
            nr=max(nr,max((r+rs for _,r,_,rs in [(c[0],c[1],c[2],c[3]) for c in cells]),default=0))
            nc=max(nc,max((c+cs for c,_,cs,_ in [(x[0],x[1],x[2],x[3]) for x in cells]),default=0))
            g=[['']*nc for _ in range(nr)]
            for col,row,cs,rs,txt in cells:
                if row<nr and col<nc: g[row][col]=txt
            out.append(g)
    return out
