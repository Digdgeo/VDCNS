import os
import arcpy
from arcpy import env
from arcpy.sa import *


env.workspace = r'I:\ndvi_PIR\ndvi_nor_rec'

for escena in os.listdir(env.workspace):
    
    if os.path.isdir(os.path.join(env.workspace, escena)):
    
        red = None
        nir = None
        
        for banda in os.listdir(os.path.join(env.workspace, escena)):
                        
            if banda.endswith('b3.TIF'):
                red = arcpy.sa.Raster(os.path.join(os.path.join(env.workspace, escena), banda))
            elif banda.endswith('b4.TIF'):
                nir = arcpy.sa.Raster(os.path.join(os.path.join(env.workspace, escena), banda))

        out_NDVI = os.path.join(os.path.join(env.workspace, escena), str(escena) + '_ndvi.TIF')
        print(out_NDVI)
        
        try:
        
            num = arcpy.sa.Float(nir-red)
            denom = arcpy.sa.Float(nir+red)
            NDVI = arcpy.sa.Divide(num, denom)

            NDVI.save(out_NDVI)
            print('Guardado!')
        
        except Exception as e:
            print(e) 
            continue
                
            