
import os, re, rasterio
import numpy as np

def reclass_bands(path):
    
    #definimos la salida
    outpath = os.path.join(path, 'extents')
    if not os.path.exists(outpath):
        os.makedirs(outpath)
    
    #recorremos la ruta con las escenas
    for e in os.listdir(path):
        
        npath = os.path.join(path, e)
            
        if os.path.isdir(npath) and re.search('^[0-9]', e):
            
            #definimos las bandas que queremos usar
            if 'l8oli' in e:
                
                bandas = ['B2.TIF', 'B3.TIF', 'B4.TIF', 'B5.TIF', 'B6.TIF', 'B7.TIF']
            
            else:
                
                bandas = ['B1.TIF', 'B2.TIF', 'B3.TIF', 'B4.TIF', 'B5.TIF', 'B7.TIF']
            
            #recorremos cada banda
            for r in os.listdir(npath):
                
                banda = r[-6:]
                
                if banda in bandas:
                    
                    
                    raster = os.path.join(npath, r)
                    outras = os.path.join(outpath, r)
                    
                    if not os.path.exists(outras):
                    
                        #abrimos con rasterio y guardamos el raster reclasificado (byte)
                        with rasterio.open(raster) as src:

                            BANDA = src.read()
                            BANDA[BANDA > 0] = 1

                            profile = src.meta
                            profile.update(dtype=rasterio.ubyte)

                            with rasterio.open(outras, 'w', **profile) as dst:
                                dst.write(BANDA.astype(rasterio.ubyte))
                                
                    