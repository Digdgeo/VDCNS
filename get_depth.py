import os, rasterio, fiona
import numpy as np

agua = r'H:\VDCNS\protocolo\pro\19840910l5tm202_32\19840910l5tm202_32_water_reclass_3.img'
dtm = r'H:\VDCNS\protocolo\data\dtm_mtn_30'
outfile = r'H:\VDCNS\protocolo\pro\19840910l5tm202_32\depth2.img'

for i in os.listdir(os.path.split(agua)[0]):
    if i.endswith('contour.shp'):
        contour = os.path.join(os.path.split(agua)[0], i)
        
#cogemos la cota del agua del shape
myshp = fiona.open(contour)

for i in myshp:
    cota = i['properties']['cota']
    
    
with rasterio.open(agua) as water:
    WT = water.read()
    WT[WT != 1] = 0
    
    Water_High = np.where(WT == 1, cota, 0)

with rasterio.open(dtm) as mdt:
    DTM = mdt.read()
    DTM[WT != 1] = np.nan
    
    depth = Water_High - DTM
    
    profile = water.meta
    profile.update(dtype = rasterio.float32)
    
    with rasterio.open(outfile, 'w', **profile) as dst:
        dst.write(depth.astype(rasterio.float32))


