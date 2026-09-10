import sys,json,math,collections
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'hospital_size_deps'))
import xlrd
from pyproj import Geod,Transformer,CRS
from shapely.geometry import Polygon
from shapely.ops import transform
b=xlrd.open_workbook('data/hospital/baidu_maps_hospital_202608_sample.xls',formatting_info=True)
s=b.sheet_by_index(0)
rows=[s.row_values(i) for i in range(s.nrows)]
g=Geod(ellps='WGS84'); sizes=[]; issues=[]; checks=[]
for i,row in enumerate(rows[1:],2):
 v=row[20]
 if not v or str(v).strip() in ('[]','null'):
  sizes.append(None); issues.append([i,'缺失边界']); continue
 try:
  p=json.loads(v)
  assert len(set(map(tuple,p)))>=3
  assert all(len(q)==2 and all(isinstance(x,(int,float)) and math.isfinite(x) for x in q) and -180<=q[0]<=180 and -90<=q[1]<=90 for q in p)
  poly=Polygon(p)
  assert poly.is_valid and not poly.is_empty, '无效多边形'
  area=abs(g.polygon_area_perimeter(*zip(*p))[0])
  assert area>0
  sizes.append(area)
  t=Transformer.from_crs('EPSG:4326',CRS.from_proj4(f'+proj=laea +lat_0={poly.centroid.y} +lon_0={poly.centroid.x} +datum=WGS84'),always_xy=True)
  checks.append(abs(transform(t.transform,poly).area-area)/area)
 except Exception as e:
  sizes.append(None); issues.append([i,'无效边界: '+str(e)])
valid=[x for x in sizes if x is not None]
stats={'total':len(sizes),'valid':len(valid),'missing':sum(x[1]=='缺失边界' for x in issues),'invalid':sum(x[1]!='缺失边界' for x in issues),'mean':sum(valid)/len(valid),'min':min(valid),'max':max(valid),'max_relative_check':max(checks)}
out={'sheet':s.name,'rows':rows,'sizes':sizes,'stats':stats,'issues':issues,'widths':{str(k):v.width/256 for k,v in s.colinfo_map.items()}}
Path('.codex_tmp/hospital_size.json').write_text(json.dumps(out,ensure_ascii=False),encoding='utf-8')
print(json.dumps(stats)); print('invalid rows', [x for x in issues if x[1]!='缺失边界'])
