import os
import arcpy
from arcpy import env
from arcpy.sa import *


env.workspace = r"Z:\Proyectos\marina_valdecanas\capas\teledeteccion\Landsat\nor"
outpath = r'I:\ndvi_PIR\ndvi_nor_rec'

shp = r'I:\ndvi_PIR\recorte.shp'
dates = [i for i in range(2000,2007)]
rasters = []

for r in os.listdir(env.workspace):

    if int(r[:4]) in dates:
        print(r)
        npath = os.path.join(env.workspace, r)
        noutpath = os.path.join(outpath, r)
        if not os.path.exists(noutpath):
            os.makedirs(noutpath)
        for f in os.listdir(npath):

            try:

                if f.endswith('.img'):
                    banda = os.path.join(npath, f)
                    out = os.path.join(noutpath, f[:-4] + '.TIF')
                    print(banda)

                    outExtractByMask = ExtractByMask(banda, shp)
                    outExtractByMask.save(out)

            except Exception as e:

                print(e)
                continue