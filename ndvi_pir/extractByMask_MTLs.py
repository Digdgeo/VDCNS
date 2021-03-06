import os
import arcpy
from arcpy import env
from arcpy.sa import *


env.workspace = r"Z:\Proyectos\marina_valdecanas\capas\teledeteccion\Landsat\ori"

shp = r'I:\ndvi_PIR\recorte.shp'
dates = [i for i in range(2007,2009)]
rasters = []

for r in os.listdir(env.workspace):

    if int(r[:4]) in dates:
        print(r)
        for f in os.listdir(os.path.join(env.workspace, r)):
            if f.endswith('MTL.txt'):
                mtl = os.path.join(os.path.join(env.workspace, r), f)
                out = os.path.join(r'I:\ndvi_PIR\ndvis', r + '.TIF')
                print(mtl)
                
                outExtractByMask = ExtractByMask(mtl, shp)
                outExtractByMask.save(out)
                
                