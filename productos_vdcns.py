######## PROTOCOLO AUTOMATICO PARA LA GENERACION DE INDICES APLICADOS #######
#######        A AGUAS CONTINENTALES CON LANDSAT 8 Y SENTINEL 2        ######
######                                                                  #####
####                        Autor: Diego Garcia Diaz                     ####
###                      email: diegogarcia@ebd.csic.es                   ###
##                  GitHub: https://github.com/Digdgeo/VDCNS               ##
#                        Sevilla 01/08/2016-28/02/2018                      #

# coding: utf-8

import os, shutil, re, time, subprocess, pandas, rasterio, sys, urllib, fiona, sqlite3, math, ogr, shapely
import numpy as np
import matplotlib.pyplot as plt
from osgeo import gdal, gdalconst
from datetime import datetime, date
from shapely.geometry import mapping, Polygon, MultiLineString


class Product(object):
    
    
    '''Esta clase genera los productos necesarios para el proyecto (Clorofila, Ficocianina, Turbidez y cota 
    del agua en el embalse. Estos valores se incluiran en la base de datos de las escenas usadas en el proyecto)'''
    
    def __init__(self, ruta_nor):
        
        self.shape = shape
        self.ruta_escena = ruta_nor
        self.escena = os.path.split(self.ruta_escena)[1]
        self.nor = os.path.split(self.ruta_escena)[0]
        self.raiz = os.path.split(self.nor)[0] 
        #print(self.raiz)
        self.nor = os.path.join(self.raiz, os.path.join('nor', self.escena))
        #print(self.nor)
        self.pro = os.path.join(self.raiz, 'pro')
        #print(self.pro)
        self.pro_escena = os.path.join(self.pro, self.escena)
        if not os.path.exists(self.pro_escena):
            os.makedirs(self.pro_escena)
        self.ori = os.path.join(self.raiz, os.path.join('ori', self.escena))
        self.data = os.path.join(self.raiz, 'data')
        self.temp = os.path.join(self.data, 'temp')
        self.productos = os.path.join(self.raiz, 'productos')
        self.vals = {}
        self.d = {}
        self.pro_esc = os.path.join(self.productos, self.escena)
        if not os.path.exists(self.pro_esc):
            os.makedirs(self.pro_esc)
            
        if 'l8oli' in self.escena:
            self.sat = 'L8'
        elif 'l7etm' in self.escena:
            self.sat = 'L7'
        elif 'l5tm' in self.escena:
            self.sat = 'L5'
        elif 'l4tm' in self.escena:
            self.sat = 'L4'
        else:
            print('no reconozco el satelite')

        if self.sat == 'L8':

            for i in os.listdir(self.nor):
                if re.search('img$', i):
                    
                    banda = i[-6:-4]
                                        
                    if banda == 'b2':
                        self.b2 = os.path.join(self.nor, i)
                    elif banda == 'b3':
                        self.b3 = os.path.join(self.nor, i)
                    elif banda == 'b4':
                        self.b4 = os.path.join(self.nor, i)
                    elif banda == 'b5':
                        self.b5 = os.path.join(self.nor, i)
                    elif banda == 'b6':
                        self.b6 = os.path.join(self.nor, i)
                    elif banda == 'b7':
                        self.b7 = os.path.join(self.nor, i)
                   
        else:

            for i in os.listdir(self.nor):
                if re.search('img$', i):
                    
                    banda = i[-6:-4]
                                        
                    if banda == 'b1':
                        self.b1 = os.path.join(self.nor, i)
                    elif banda == 'b2':
                        self.b2 = os.path.join(self.nor, i)
                    elif banda == 'b3':
                        self.b3 = os.path.join(self.nor, i)
                    elif banda == 'b4':
                        self.b4 = os.path.join(self.nor, i)
                    elif banda == 'b5':
                        self.b5 = os.path.join(self.nor, i)
                    elif banda == 'b7':
                        self.b7 = os.path.join(self.nor, i)


                        
class get_water_level(Product):
    
    '''En esta clase se implementa todo el codigo necesario para llevar a cabo la generacion 
    de las laminas de agua con su cota asignada'''
                        
    def get_water_rec(self, shape):

        '''Primero hacemos el recorte a la cota 318, habria que introducir la ruta del shape
        con el cual queramos hacer el recorte'''

        
                
        if self.sat == 'L8':
            banda = self.b6

        else:
            banda = self.b5
            print(banda)
                    
            #except Exception as e:
                #print('Error', e)
                #print('No ha NIR noramlizado en la escena', self.escena)
                
        #print('banda', banda, self.sat)     
        #shape = r'O:\VDCNS\protocolo\data\cota_318p.shp'
        salida = os.path.join(self.pro_escena, self.escena + '_water_rec_b5.img')
        cmd = ["gdalwarp", "-dstnodata" , "0" , "-cutline", "-crop_to_cutline", "-tr", "30", "30", "-of", "ENVI", "-tap"]
        
        cmd.append(banda)
        cmd.append(salida)
        cmd.insert(4, shape) #seria el 4/2 con/sin el dst nodata
        #print(cmd)
        proc = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        stdout,stderr=proc.communicate()
        exit_code=proc.wait()

        if exit_code: 
            raise RuntimeError(stderr)
        else:
            print(stdout)
            print('recorte de la banda', banda[-6:-4], 'generado')
                

    def reclass_water(self):

        '''Hacemos el reclassify a las bandas recortadas para '''
        reclass = os.path.join(self.pro_escena, self.escena + '_water_reclass.img')
        print(reclass)
        
        for i in os.listdir(self.pro_escena):
            
            if re.search('_water_rec_b..img$', i):

                raster = os.path.join(self.pro_escena, i)

        with rasterio.open(raster) as src:
            B5 = src.read()

            B5[(B5 <= 2000) & (B5 > 0)] = 1
            B5[B5 > 2000] = 0
            
            profile = src.meta
            profile.update(dtype=rasterio.int16)

        with rasterio.open(reclass, 'w', **profile) as dst:
            dst.write(B5.astype(rasterio.int16))

    
    def polygonize(self):
        
        '''Este metodo sirve para vecorizar la lamina de agua obtenida'''
            
        outShp = os.path.join(self.pro_escena, self.escena + '_poly.shp')

        for i in os.listdir(self.pro_escena):
            if re.search('water_reclass.img$', i):
                print(i)
                water = os.path.join(self.pro_escena, i)

        sourceRaster = gdal.Open(water)
        band = sourceRaster.GetRasterBand(1)
        bandArray = band.ReadAsArray()

        driver = ogr.GetDriverByName("ESRI Shapefile")
        if os.path.exists(outShp):
            driver.DeleteDataSource(outShp)
        outDatasource = driver.CreateDataSource(outShp)
        outLayer = outDatasource.CreateLayer("polygonized", srs= None)
        gdal.Polygonize( band, None, outLayer, -1, [], callback=None )
        outDatasource.Destroy()
        sourceRaster = None
            
    def get_vector_mask_pg(self):
        
        '''Este metodo sirve para seleccionar la lamina de agua vectorial adecuada (la que tenga la segunda mayor area)'''
        
        out = os.path.join(self.pro_escena, self.escena[:8] + '_watervec.shp')
        
        for i in os.listdir(self.pro_escena):
            if i.endswith('poly.shp'):
                shp = os.path.join(self.pro_escena, i)
                
        myshp = fiona.open(shp)

        areas = []
        selection = []

        for i in myshp.values():

            geom1 = i['geometry']
            a1 = Polygon(geom1['coordinates'][0])
            #print('\nArea', a1.area, '\n')
            areas.append(a1.area)

        #print(sorted(areas))

        for i in myshp.values():

            geom1 = i['geometry']
            a1 = Polygon(geom1['coordinates'][0])

            if a1.area == sorted(areas)[-2]:
                selection.append(i)


        with fiona.open(shp, 'r') as source:

            # **source.meta is a shortcut to get the crs, driver, and schema
            # keyword arguments from the source Collection.
            with fiona.open(out, 'w', **source.meta) as sink:


                for f in source:

                    geom1 = f['geometry']
                    a1 = Polygon(geom1['coordinates'][0])
                    if a1.area == sorted(areas)[-2]:
                        sink.write(f)
        
    def get_vector_mask_pl(self, ratio):
        
        '''En este metodo elegimos el poligono de la mascara de agua y 
        lo pasamos a vectorial (suavizando tambien la geometria)'''
        
        outshp = os.path.join(self.pro_escena, self.escena[:10] + '_WaterMask50.shp')
        
        for i in os.listdir(self.pro_escena):
            
            if i.endswith('_watervec.shp'):
                
                shape = os.path.join(self.pro_escena, i)
                print(shape)
                myshp = fiona.open(shape)
            
        for i in myshp:
            geom1 = i['geometry']
            #print(geom1)
            #print(geom1)
            line = MultiLineString(geom1['coordinates'])
            line10 = line.simplify(ratio)
        

        # Define a polygon feature geometry with one attribute
        schema = {
            'geometry': 'MultiLineString',
            'properties': {'id': 'int'}}

        # Write a new Shapefile
        with fiona.open(outshp, 'w', 'ESRI Shapefile', schema) as c:
            ## If there are multiple geometries, put the "for" loop here
            c.write({
                'geometry': mapping(line10),
                'properties': {'id': 123},
            })
        
        
    def run_water_mask():
        
        self.get_water_rec()
        self.reclass_water()
        self.polygonize()
        self.get_vector_mask_pg()
        self.get_vector_mask_pl(17)
        
        