import olefile, zlib, struct
T_PARA_HDR, T_PARA_TXT, T_CTRL, T_LIST, T_TABLE = 0x42,0x43,0x47,0x48,0x4D
# HWP5 문단 텍스트 제어문자 (한글문서파일형식 5.0 spec)
CHAR_CTRL   = {0,10,13,24,25,26,27,28,29,30,31}        # 1 wchar
INLINE_CTRL = {4,5,6,7,8,9,19,20}                       # 8 wchar
EXT_CTRL    = {1,2,3,11,12,14,15,16,17,18,21,22,23}     # 8 wchar

def _text(pl):
    o=[];i=0
    while i+1<len(pl):
        c=pl[i]|(pl[i+1]<<8)
        if c<32:
            if c in (10,13): o.append('\n'); i+=2
            elif c in CHAR_CTRL:   i+=2
            elif c in INLINE_CTRL: i+=16
            elif c in EXT_CTRL:    i+=16; o.append(' ')
            else: i+=2
        else: o.append(chr(c)); i+=2
    return ''.join(o)

def _recs(data):
    i=0
    while i+4<=len(data):
        h=struct.unpack('<I',data[i:i+4])[0]
        tag=h&0x3FF; lvl=(h>>10)&0x3FF; sz=(h>>20)&0xFFF; i+=4
        if sz==0xFFF: sz=struct.unpack('<I',data[i:i+4])[0]; i+=4
        yield tag,lvl,data[i:i+sz]; i+=sz

def tables(path):
    """HWP 파일의 모든 표를 grid(list[list[str]])로 반환"""
    f=olefile.OleFileIO(path)
    comp=bool(f.openstream('FileHeader').read()[36]&1)
    secs=sorted([s for s in f.listdir() if s[0]=='BodyText'],
                key=lambda s:int(''.join(c for c in s[1] if c.isdigit()) or 0))
    res=[]
    for s in secs:
        d=f.openstream(s).read()
        if comp: d=zlib.decompress(d,-15)
        stack=[]   # (level, cells, nRows, nCols)
        cur=None   # (level, col,row,cs,rs, buf)
        for tag,lvl,pl in _recs(d):
            if tag==T_TABLE and len(pl)>=8:
                attr,nr,nc=struct.unpack('<IHH',pl[:8])
                stack.append([lvl,[],nr,nc]); cur=None
            elif tag==T_LIST and stack and lvl==stack[-1][0] and len(pl)>=16:
                if cur: stack[-1][1].append(cur)
                col,row,cs,rs=struct.unpack('<4H',pl[8:16])
                cur=[col,row,cs,rs,[]]
            elif tag==T_PARA_TXT and cur is not None and stack and lvl>stack[-1][0]:
                cur[4].append(_text(pl))
            elif tag==T_PARA_HDR and stack and lvl<=stack[-1][0]-1:
                if cur: stack[-1][1].append(cur); cur=None
                lv,cells,nr,nc=stack.pop(); res.append(_grid(cells,nr,nc))
            elif tag==T_CTRL and stack and lvl<=stack[-1][0]-1:
                if cur: stack[-1][1].append(cur); cur=None
                lv,cells,nr,nc=stack.pop()
                res.append(_grid(cells,nr,nc))
        while stack:
            if cur: stack[-1][1].append(cur); cur=None
            lv,cells,nr,nc=stack.pop(); res.append(_grid(cells,nr,nc))
    f.close()
    return res

def _grid(cells,nr,nc):
    nr=max(nr, max((c[1]+c[3] for c in cells), default=0))
    nc=max(nc, max((c[0]+c[2] for c in cells), default=0))
    g=[['']*nc for _ in range(nr)]
    for col,row,cs,rs,buf in cells:
        if row<nr and col<nc:
            g[row][col]=' '.join(x.strip() for x in ''.join(buf).split('\n') if x.strip())
    return g
