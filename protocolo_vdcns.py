########  PROTOCOLO AUTOMATICO PARA LA CORRECCION RADIOMETRICA DE ESCENAS LANDSAT  #######
######                                                                              ######
####                        Autor: Diego Garcia Diaz                                  ####
###                      email: diegogarcia@ebd.csic.es                                ###
##                  GitHub: https://github.com/Digdgeo/VDCNS                            ##
#                        Sevilla 01/08/2016-28/02/2018                                   #

# coding: utf-8
%matplotlib inline

import os, shutil, pymongo, re, time, subprocess, pandas, rasterio, sys, urllib, sqlite3
import numpy as np
import matplotlib.pyplot as plt
from osgeo import gdal, gdalconst
#from pymasker import landsatmasker, confidence En principio Fmask ya no falla por lo que no es necesario
from datetime import datetime, date
from scipy import ndimage
from scipy.stats import linregress
from IPython.display import Image
from IPython.display import display


class Landsat(object):
    
     
    '''Esta clase esta hecha para corregir radiometricamente escenas Landsat 8, de cara a obtener las láminas de agua sobre 
    el embalse de toda la serie Landsat disponible'''
    
    
    def __init__(self, ruta, umbral=50, hist=1000, dtm = 'plano'):
        
        
        '''Instanciamos la clase con la escena que vayamos a procesar, hay que introducir la ruta a la escena en ori
        y de esa ruta el constructor obtiene el resto de rutas que necesita para ejecutarse. Los parametros marcados por defecto son el 
        umbral para la mascara de nubes Fmask y el numero de elementos a incluir en el histograma de las bandas'''
          
        self.ruta_escena = ruta
        self.ori = os.path.split(ruta)[0]
        self.escena = os.path.split(ruta)[1]
        self.raiz = os.path.split(self.ori)[0]
        self.geo = os.path.join(self.raiz, 'geo')
        self.rad = os.path.join(self.raiz, 'rad')
        self.nor = os.path.join(self.raiz, 'nor')
        self.data = os.path.join(self.raiz, 'data')
        self.umbral = umbral
        self.hist = hist
        if dtm == 'plano':
            self.dtm = os.path.join(self.data, 'temp\\Nodtm.img')
        else:
            self.dtm = os.path.join(self.data,'temp\\dtm_escena.img')

        #detectamos el satelite, contemplamos L4TM, L5TM, L7ETM y L8OLI
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
            
        print(self.sat)   
        
        self.mimport = os.path.join(self.ruta_escena, 'miramon_import')
        if not os.path.exists(self.mimport):
            os.makedirs(self.mimport)
            
        self.bat = os.path.join(self.ruta_escena, 'import.bat')
        self.bat2 = os.path.join(self.rad, 'importRad.bat')
        self.cloud_mask = None
        
        self.parametrosnor = {}
        self.iter = 1
        self.rois = os.path.join(self.data, 'rois_vdcns.img')
        
        
        for i in os.listdir(self.ruta_escena):
            if i.endswith('MTL.txt'):
                mtl = os.path.join(self.ruta_escena,i)
                arc = open(mtl,'r')
                for i in arc:
                    if 'LANDSAT_SCENE_ID' in i:
                        usgs_id = i[-23:-2]
                    elif 'CLOUD_COVER' in i:
                        cloud_scene = float(i[-6:-1])
                    elif 'PROCESSING_SOFTWARE_VERSION' in i:
                        lpgs = i.split('=')[1][2:-2]
                    elif 'UTM_ZONE' in i:
                        self.zone = int(i.split('=')[1][1:-1]) #vamos a distinguir si son escenas del uso 30 o 29 para ver que dtm usaremos luego
        arc.close()
        
        self.quicklook = os.path.join(self.ruta_escena, usgs_id + '.jpg')
        qcklk = open(self.quicklook,'wb')

        if self.sat == 'L8':
            s = "http://earthexplorer.usgs.gov/browse/landsat_8/" + self.escena[:4] + "/" + self.escena[-6:-3] + "/0" + self.escena[-2:] + "/" + usgs_id + ".jpg"
            #s = "http://earthexplorer.usgs.gov/browse/landsat_8/" + self.escena[:4] + "/200/0" + self.escena[-2:] + "/" + usgs_id + ".jpg"
        elif self.sat == 'L7':
            s = "http://earthexplorer.usgs.gov/browse/etm/202/32/" + self.escena[:4] + "/" + usgs_id + "_REFL.jpg"
        elif self.sat == 'L5' or self.sat == 'L4':
            s = "http://earthexplorer.usgs.gov/browse/tm/202/32/" + self.escena[:4] + "/" + usgs_id + "_REFL.jpg"
        
        print(s)
        qcklk.write(urllib.request.urlopen(s).read())
        
        display(Image(url=s, width=500))
        
        
        #self.newesc = {'_id': self.escena, 'usgs_id': usgs_id, 'Nubes': {'cloud_scene': cloud_scene},\
                       #'Iniciada': datetime.now()}
        
        self.newesc = {'_id': self.escena, 'usgs_id': usgs_id, 'Nubes': {}, 'Iniciada': datetime.now()}
        
        
        #iniciamos MongoDB
        #os.system('mongod')
        # Conectamos con MongoDB 
        connection = pymongo.MongoClient("mongodb://localhost")

        # DataBase: teledeteccion, Collection: landsat
        
        db=connection.teledeteccion
        vdcns = db.vdcns
        
        try:
        
            vdcns.insert_one(self.newesc)
        
        except Exception as e:
            
            vdcns.update_one({'_id':self.escena}, {'$set':{'Iniciada': datetime.now()}})
            #print "Unexpected error:", type(e), se Podria dar un error por clave unica, por eso en
            #ese caso, lo que hacemos es actualizar la fecha en la que tratamos la imagen
        
        
    def fmask(self):
            
            '''-----\n
            Este metodo genera el algortimo Fmask que sera el que vendra por defecto en la capa de calidad de
            las landsat a partir del otono de 2015'''
            
            os.chdir(self.ruta_escena)
                
            print('comenzando Fmask')
            
            try:
                
                print('comenzando Fmask')
                t = time.time()
                    #El valor (el ultimo valor, que es el % de confianza sobre el pixel (nubes)) se pedira desde la interfaz que se haga. 
                a = os.system('C:/"Program Files"/Fmask/application/Fmask 3 3 0 {}'.format(self.umbral))
                a
                if a == 0:
                    self.cloud_mask = 'Fmask'
                    print('Mascara de nubes (Fmask) generada en ' + str(t-time.time()) + ' segundos')
                    
                else:
                    t = time.time()
                    print('comenzando Fmask NoTIRS')
                    a = os.system('C:/Cloud_Mask/Fmask_3_2')
                    a
                    if a == 0:
                        self.cloud_mask = 'Fmask NoTIRS'
                        print('Mascara de nubes (Fmask NoTIRS) generada en ' + str(t-time.time()) + ' segundos')
                    else:
                        print('comenzando BQA')
                        for i in os.listdir(self.ruta_escena):
                            if i.endswith('BQA.TIF'):
                                masker = landsatmasker(os.path.join(self.ruta_escena, i))
                                mask = masker.getcloudmask(confidence.high, cirrus = True, cumulative = True)
                                masker.savetif(mask, os.path.join(self.ruta_escena, self.escena + '_Fmask.TIF'))
                        self.cloud_mask = 'BQA'
                        print('Mascara de nubes (BQA) generada en ' + str(t-time.time()) + ' segundos')
                                           
            except Exception as e:
                
                print("Unexpected error:", type(e), e)
                
            #Insertamos el umbral para Fmask en la base de datos: Si es de calidad pondremos 'BQA'
    
    
    def fmask_legend(self):
        
        '''-----\n
        Este metodo anade las lineas necesarias para que Envi reconozca que es una raster categorico con sus
        correspondientes valores (Sin definir, Agua, Sombra de nubes, Nieve, Nubes). Se aplicara tanto a la fmask 
        generada en ori, como a la reproyectada en nor'''
        
        for i in os.listdir(self.ruta_escena):
    
            if i.endswith('Fmask.hdr'):

                fmask = os.path.join(self.ruta_escena, i)
                doc = open(fmask, 'r')
                doc.seek(0)
                lineas = doc.readlines()
                
                for n,e in enumerate(lineas):#Establecemos el tipo como clasificacion, realmente, en Envi 5 al menos, no importa
                    if e.startswith('file type'):
                        lineas[n] = 'file type: ENVI Classification\n'

                nodata = '\ndata ignore value = 255\n'
                clases = 'classes = 5\n'
                lookup = 'class lookup = {255,255,255, 0,0,255, 0,0,0, 0,255,255, 150,150,150}\n'
                vals = 'class names = {Unclassified, Water, Shadow, Snow, Cloud}\n'

                lineas.append(nodata)
                lineas.append(clases)
                lineas.append(lookup)
                lineas.append(vals)

                doc.close()

                f = open(fmask, 'w')
                for linea in lineas:
                    f.write(linea)

                f.close()
                
            elif i.endswith('Fmask'):
                
                src = os.path.join(self.ruta_escena, i)
                dst = src + '.img'
                os.rename(src, dst)
                
    
    def get_hdr(self):
        
        '''-----\n
        Este metodo genera los hdr para cada banda, de cara a poder trabajar posteriormente con ellas en GDAL, ENVI u otro software'''
        
        print('comenzando get hdr')
        
        if self.sat == 'L8':
        
            dgeo = {'B1': '_r_b1.img', 'B2': '_r_b2.img', 'B3': '_r_b3.img', 'B4': '_r_b4.img', 'B5': '_r_b5.img',  \
                   'B6': '_r_b6.img', 'B7': '_r_b7.img', 'B8': '_r_b8.img', 'B9': '_r_b9.img',  \
                            'B10': '_r_b10.img', 'B11': '_r_b11.img', 'BQA': '_r_bqa.img'}
            
        elif self.sat == 'L7':
            
            dgeo = {'B1': '_r_b1.img', 'B2': '_r_b2.img', 'B3': '_r_b3.img', 'B4': '_r_b4.img', 'B5': '_r_b5.img',\
                'B6_VCID_1': '_r_b6.img', 'B6_VCID_2': '_r_b9.img', 'B7': '_r_b7.img', 'B8': '_r_b8.img'}
            
        else:
            
             dgeo = {'B1': '_r_b1.img', 'B2': '_r_b2.img', 'B3': '_r_b3.img', 'B4': '_r_b4.img', 'B5': '_r_b5.img',\
                'B6': '_r_b6.img', 'B7': '_r_b7.img'}
        
        for i in os.listdir(self.ruta_escena):
            
            if i.endswith('.TIF'):
                
                if len(i) == 28:
                    banda = i[-6:-4]
                elif len(i) == 29:
                    banda = i[-7:-4]
                else:
                    banda = i[-13:-4]
                    
                print(banda)
                
                if banda in dgeo.keys():
                
                    in_rs = os.path.join(self.ruta_escena, i)
                    out_rs = os.path.join(self.ruta_escena, self.escena + dgeo[banda])
                    string = 'gdal_translate -of ENVI --config GDAL_CACHEMAX 8000 --config GDAL_NUM_THREADS ALL_CPUS {} {}'.format(in_rs, out_rs)
                    print(string)
                    os.system(string)

        #ahora vamos a borrar los .img y xml que se han generado junto con los 
    
    def clean_ori(self):

        
        print('clean ori empezanco')
        
        for i in os.listdir(self.ruta_escena):

            if i.endswith('.img') and not 'Fmask' in i or i.endswith('.xml'):
                rs_dl = os.path.join(self.ruta_escena, i)
                print(rs_dl)
                os.remove(rs_dl)

                
    def createI_bat(self):
        
        '''-----\n
        Este metodo crea un archivo bat con los parametros necesarios para realizar la importacion'''
        
        print('comenzando create ibat')
        
        ruta = self.ruta_escena
        #estas son las variables que necesarias para crear el bat de Miramon
        tifimg = 'C:\\MiraMon\\TIFIMG'
        num1 = '9'
        num2 = '1'
        num3 = '0'
        salidapath = self.mimport #aqui va la ruta de salida de la escena
        dt = '/DT=c:\\MiraMon'

        for i in os.listdir(ruta):
            if i.endswith('B1.TIF'):
                banda1 = os.path.join(ruta, i)
            elif i.endswith('MTL.txt'):
                mtl = "/MD="+ruta+"\\"+i
            else: continue

        lista = [tifimg, num1, banda1,  salidapath, num2, num3, mtl, dt]
        print(lista)

        batline = (" ").join(lista)

        pr = open(self.bat, 'w')
        pr.write(batline)
        pr.close()


    def callI_bat(self):
        
        '''-----\n
        Este metodo llama ejecuta el bat de la importacion. Tarda entre 7 y 21 segundos en importar la escena'''

        #import os, time
        ti = time.time()
        a = os.system(self.bat)
        a
        if a == 0:
            print("Escena importada con exito en " + str(time.time()-ti) + " segundos")
        else:
            print("No se pudo importar la escena")
        #borramos el archivo bat creado para la importacion de la escena, una vez se ha importado esta
        os.remove(self.bat)
        
        
    def get_kl_csw(self):
        
        '''Este metodo obtiene los Kl para cada banda. Lo hace buscando los valores minimos dentro 
        de las zonas clasificadas como agua y sombra orografica, siempre y cuando la sombra orografica 
        no este cubierta por nubes ni sombra de nubes. La calidad de la mascara e muy importante, por eso
        a las escenas que no se puedan realizar con Fmask habria que revisarles el valor de kl.
        Tambien distingue Landsar 7 de Landsat 8, aplicandole tambien a las Landsat 7 la mascara de Gaps'''
    
        #Empezamos borrando los archivos de temp, la idea de esto es que al acabar una escena queden disponibles
        #por si se quiere comprobar algo. Ya aqui se borran antes de comenzar la siguiente
        t = time.time()

        temp = os.path.join(self.data, 'temp')
        for i in os.listdir(temp):
            arz = os.path.join(temp, i)
            os.remove(arz)

        #Hacemos el recorte al dtm para que tenga la misma extension que la escena y poder operar con los arrays
        t = time.time()
        shape = os.path.join(temp, 'poly_escena.shp')
        
        ruta = self.ruta_escena

        for i in os.listdir(ruta):

            if i.endswith('B1.TIF'):
                raster = os.path.join(ruta, i)

        cmd = ["gdaltindex", shape, raster]
        proc = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        stdout,stderr=proc.communicate()
        exit_code=proc.wait()

        if exit_code: 
            raise RuntimeError(stderr)
        else:
            print(stdout)
            print('marco generado')

        #ya tenemos el dtm recortado guardado en data/temp, ahora vamos a generar el hillshade.  
        #Para ello primero hay que recortar el dtm con el shape recien obtenido con la extension de la escena
        #vamos a usar la variable 'zone' para usar el dtm reproyectado al huso 30 o 29
        dtm_escena = os.path.join(temp, 'dtm_escena.img')
        if self.zone == 29:

            for i in os.listdir(self.data):
                if i.endswith('29c.img'):
                    dtm = os.path.join(self.data, i)
                    print(dtm)

        else:

            for i in os.listdir(self.data):
                if i.endswith('30c.img'):
                    dtm = os.path.join(self.data, i)
                    print(dtm)


        cmd = ["gdalwarp", "-dstnodata" , "0" , "-cutline", "-crop_to_cutline", "-of", "ENVI"]
        #cmd = ["gdalwarp", "-cutline", "-crop_to_cutline", "-of", "ENVI"] #PROBAR A DEJAR EL DTM ORIGINAL -9999 A VER SI SALE MEJOR
        cmd.append(dtm)
        cmd.append(dtm_escena)
        cmd.insert(4, shape) #seria el 4/2 con/sin el dst nodata
        proc = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        stdout,stderr=proc.communicate()
        exit_code=proc.wait()

        if exit_code: 
            raise RuntimeError(stderr)
        else:
            print(stdout)
            print('dtm_escena generado')

        #Ahora ya tenemos el dtm de la escena, a continuacion vamos a obtener el hillshade 
        #primero debemos tomar los parametros solares del MTL
        for i in os.listdir(ruta):
            if i.endswith('MTL.txt'):
                mtl = os.path.join(ruta,i)
                arc = open(mtl,'r')
                for i in arc:
                    if 'SUN_AZIMUTH' in i:
                        azimuth = float(i.split("=")[1])
                    elif 'SUN_ELEVATION' in i:
                        elevation = float(i.split("=")[1])

        #Una vez tenemos estos parametros generamos el hillshade
        salida = os.path.join(temp, 'hillshade.img')
        cmd = ["gdaldem", "hillshade", "-az", "-alt", "-of", "ENVI"]
        cmd.append(dtm_escena)
        cmd.append(salida)
        cmd.insert(3, str(azimuth))
        cmd.insert(5, str(elevation))
        proc = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        stdout,stderr=proc.communicate()
        exit_code=proc.wait()

        if exit_code: 
            raise RuntimeError(stderr)
        else:
            print(stdout)
            print('Hillshade generado')
        
        #Ahora vamos a hacer un recorte temporal al hillshade con la extension de las bandas de referencia OCT-2016
        #aunque la extension es siempre la misma y el mismo dtm, hay que hacerlo cada vez porque cambian las condiciones solares
        for i in os.listdir(temp):
            if i.endswith('shade.img'):
                hillshade = os.path.join(temp, i)
                
        shape = r'O:\VDCNS\protocolo\data\Rois_extent.shp'
        hill_rec = r'O:\VDCNS\protocolo\data\temp\rec_hill.img'
        cmd = ["gdalwarp", "-dstnodata" , "0" , "-cutline", "-crop_to_cutline", "-tr", "30", "30", "-of", "ENVI", "-tap"]
        #cmd = ["gdalwarp", "-cutline", "-crop_to_cutline", "-of", "ENVI"] #PROBAR A DEJAR EL DTM ORIGINAL -9999 A VER SI SALE MEJOR
        cmd.append(hillshade)
        cmd.append(hill_rec)
        cmd.insert(4, shape) #seria el 4/2 con/sin el dst nodata
        proc = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        stdout,stderr=proc.communicate()
        exit_code=proc.wait()

        if exit_code: 
            raise RuntimeError(stderr)
        else:
            print(stdout)
            print('recorte de hillshade generado')
        
        #Ahora recortamos a la extensión necesaria la mascara de nubes OCT-2016
        for i in os.listdir(self.ruta_escena):
            if i.endswith('Fmask.img'):
                clouds = os.path.join(self.ruta_escena, i)
                
        shape = r'O:\VDCNS\protocolo\data\Rois_extent.shp'
        clouds_rec = r'O:\VDCNS\protocolo\data\temp\clouds_rec.img'
        cmd = ["gdalwarp", "-dstnodata" , "0" , "-cutline", "-crop_to_cutline", "-tr", "30", "30", "-of", "ENVI", "-tap"]
        #cmd = ["gdalwarp", "-cutline", "-crop_to_cutline", "-of", "ENVI"] #PROBAR A DEJAR EL DTM ORIGINAL -9999 A VER SI SALE MEJOR
        cmd.append(clouds)
        cmd.append(clouds_rec)
        cmd.insert(4, shape) #seria el 4/2 con/sin el dst nodata
        proc = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        stdout,stderr=proc.communicate()
        exit_code=proc.wait()

        if exit_code: 
            raise RuntimeError(stderr)
        else:
            print(stdout)
            print('recorte de la mascara de nubes generado')
        
        #Ya estan el hillshade y la mascara de nubes recortados en data/temp. Tambien tenemos ya la Fmask generada en ori, 
        #asi que ya podemos operar con los arrays
        ruta = os.path.join(self.data, 'temp')
        for i in os.listdir(ruta):
            if i.endswith('clouds_rec.img'): #| i.endswith('_Fmask.TIF'): En princpio Fmask ya no falla
                rs = os.path.join(ruta, i)
                fmask = gdal.Open(rs)
                Fmask = fmask.ReadAsArray()
                print('min, max: ', Fmask.min(), Fmask.max())
        for i in os.listdir(temp):
            if i.endswith('rec_hill.img'):
                rst = os.path.join(temp, i)
                hillshade = gdal.Open(rst)
                Hillshade = hillshade.ReadAsArray()
                
                
        #Ahora debemos de hacer el recorte a cada una de las bandas para obtener despues los kl
        #creamos una lista con las bandas que van a pasar al corrad (sin termicas ni pancromatico)
        if self.sat == 'L8' or self.sat == 'L7':
            
            bands = [os.path.join(self.ruta_escena, i) for i in os.listdir(self.ruta_escena) if re.search('B..TIF', i) and not 'B8' in i]
            print('BANDS', bands)
            
        elif self.sat == 'L5' or self.sat == 'L4':
            
            bands = [os.path.join(self.ruta_escena, i) for i in os.listdir(self.ruta_escena) if re.search('B..TIF', i) and not 'B6' in i]
            print('BANDS', bands)
        
        else:
            
            print('No reconozco el satelite')
        #Ahora hacemos el recorte temporal a las bandas que necesitamos para calcular el kl
        for i in bands:
            
            banda = i[-6:-4]
            shape = r'O:\VDCNS\protocolo\data\Rois_extent.shp'
            salida = os.path.join(self.data, os.path.join('temp', 'rec_' + banda + '.img'))
            print('SALIDA', salida)
            #banda = r'O:\VDCNS\protocolo\data\temp\clouds_rec.img'
            cmd = ["gdalwarp", "-dstnodata" , "0" , "-cutline", "-crop_to_cutline", "-tr", "30", "30", "-of", "ENVI", "-tap"]
            #cmd = ["gdalwarp", "-cutline", "-crop_to_cutline", "-of", "ENVI"] #PROBAR A DEJAR EL DTM ORIGINAL -9999 A VER SI SALE MEJOR
            cmd.append(i)
            cmd.append(salida)
            cmd.insert(4, shape) #seria el 4/2 con/sin el dst nodata
            proc = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            stdout,stderr=proc.communicate()
            exit_code=proc.wait()

            if exit_code: 
                raise RuntimeError(stderr)
            else:
                print(stdout)
                print('recorte de la banda', i[-6:-4], 'generado')
        
        #Queremos los pixeles de cada banda que esten dentro del valor agua (1) y sin nada definido ((0) 
        #para las sombras) de la Fmask (con lo cual tambien excluimos las nubes y sombras de nubes). 
        #Junto con estos valores, queremos tambien los valores que caen en sombra (se ha decidido que 
        #el valor de corte mas adecuado es el percentil 20)

        #Arriba estamos diciendo que queremos el minimo del agua o de la escena completa sin nubes ni 
        #sombras ni agua pero en sombra orografica

        #Ahora vamos a aplicar la mascara y hacer los histogramas
        # if self.sat == 'L8': En principio solo seran Landsat 8
        ruta = os.path.join(self.data, 'temp')
        if self.sat == 'L8':
            
            bandas = ['B1', 'B2', 'B3', 'B4','B5', 'B6', 'B6', 'B7', 'B9']
            lista_kl = []
            print('entramos en el loop de las bandas')
            for i in os.listdir(ruta):
                #print('Ruta', ruta, i)
                if re.search('rec_B..img$', i):
                #if i.endswith('.TIF'):
                    
                    banda = i[-6:-4]
                    #print('BANDA', i)
                    #if banda in bands:
                    raster = os.path.join(self.data, os.path.join('temp', i))
                    raster = os.path.join(ruta, i)
                    bandraster = gdal.Open(raster)
                    data = bandraster.ReadAsArray()
                    #anadimos la distincion entre Fmask y BQA
                    if self.cloud_mask == 'Fmask' or self.cloud_mask == 'Fmask NoTIRS':
                        print('usando Fmask')
                        data2 = data[((Fmask==1) | (((Fmask==0)) & (Hillshade<(np.percentile(Hillshade, 20)))))]

                    else:
                        print('usando BQA\ngenerando water mask')

                        for i in os.listdir(ruta):
                            if i.endswith('BQA.TIF'):
                                masker = landsatmasker(os.path.join(ruta, i))  
                                maskwater = masker.getwatermask(confidence.medium) #cogemos la confianza media, a veces no hay nada en la alta
                                #print 'watermin, watermax: ', maskwater.min(), maskwater.max()

                                data2 = data[((data != 0) & ((maskwater==1) | (((Fmask==0)) & (Hillshade<(np.percentile(Hillshade, 20))))))]
                                print('data2: ', data2.min(), data2.max(), data2.size)

                    lista_kl.append(data2.min())#anadimos el valor minimo (podria ser perceniles) a la lista de kl
                    lista = sorted(data2.tolist())
                    print('lista: ', lista[:10])
                    #nmask = (data2<lista[1000])#probar a coger los x valores mas bajos, a ver hasta cual aguanta bien
                    data3 = data2[data2<lista[self.hist]]
                    print('data3: ', data3.min(), data3.max())

                    df = pandas.DataFrame(data3)
                    #plt.figure(); df.hist(figsize=(10,8), bins = 100)#incluir titulo y rotulos de ejes
                    plt.figure(); df.hist(figsize=(10,8), bins = 50, cumulative=False, color="Red"); 
                    plt.title(self.escena + '_gr_' + banda, fontsize = 18)
                    plt.xlabel("Pixel Value", fontsize=16)  
                    plt.ylabel("Count", fontsize=16)
                    path_rad = os.path.join(self.rad, self.escena)
                    if not os.path.exists(path_rad):
                        os.makedirs(path_rad)
                    name = os.path.join(path_rad, self.escena + '_r_'+ banda.lower() + '.png')
                    plt.savefig(name)

            plt.close('all')
            print('Histogramas generados')

            #Hasta aqui tenemos los histogramas generados y los valores minimos guardados en lista_kl, ahora 
            #debemos escribir los valores minimos de cada banda en el archivo kl.rad
            for i in os.listdir(self.rad):

                    if i.endswith('l8.rad'):

                        archivo = os.path.join(self.rad, i)
                        dictio = {6: lista_kl[0], 7: lista_kl[1], 8: lista_kl[2], 9: lista_kl[3],\
                        10: lista_kl[4], 11: lista_kl[5], 12: lista_kl[6], 14: lista_kl[7]}


                        rad = open(archivo, 'r')
                        rad.seek(0)
                        lineas = rad.readlines()

                        for l in range(len(lineas)):

                            if l in dictio.keys():
                                lineas[l] = lineas[l].rstrip()[:-4] + str(dictio[l]) + '\n'
                            else: continue

                        rad.close()

                        f = open(archivo, 'w')
                        for linea in lineas:
                            f.write(linea)

                        f.close()

                        src = os.path.join(self.rad, i)
                        dst = os.path.join(path_rad, self.escena + '_kl.rad')
                        shutil.copy(src, dst)
            
        else: #if self.sat == 'L7' or self.sat == 'L5' or self.sat == 'L4:
            
            outfile = os.path.join(self.data, os.path.join('temp', 'gaps.img'))
            print('usando l4, l5 o l7')
            bandas = ['B1', 'B2', 'B3', 'B4', 'B5', 'B7']
            lista_kl = []
            #gaps balck borders
            listaz = []
            bands = ['B1', 'B2', 'B3', 'B4', 'B5', 'B7']
            #ruta_gap = r'O:\VDCNS\protocolo\ori\20030915l5tm202_32'
            gap_bandas = [i for i in os.listdir(self.ruta_escena) if i.endswith('.TIF') and not i.endswith('B6.TIF')]
            mydict = dict(zip(bands, gap_bandas))
            for n, e in enumerate(mydict):
                #print('MYDICTEEE', mydict[e])
                with rasterio.open(os.path.join(self.ruta_escena, mydict[e])) as src:
                        bands[n] = src.read()
                        bands[n][bands[n]>=1] = 1
                        listaz.append(bands[n])

            gaps = sum(listaz)
            print ('GAPS: ', gaps.min(), gaps.max(), gaps.mean(), type(gaps))
            gaps[gaps<6] = 0
            gaps[gaps == 6] = 1
            erode = ndimage.grey_erosion(gaps, size=(5,5,1))
            profile = src.meta
            profile.update(dtype=rasterio.uint16)

            with rasterio.open(outfile, 'w', **profile) as dst:
                dst.write(erode.astype(rasterio.uint16))

            #Ahora vamos a recortar la capa de erode, de modo que vamos a usar los 2 criterios
            #la mascara a la zona minima cubierta y la "erosion" de los NoDatas
            shape = r'O:\VDCNS\protocolo\data\Rois_extent.shp'
            gaps = os.path.join(self.data, os.path.join('temp', 'gaps.img'))
            gaps_rec = os.path.join(self.data, os.path.join('temp', 'rec_gaps.img'))
            cmd = ["gdalwarp", "-dstnodata" , "0" , "-cutline", "-crop_to_cutline", "-tr", "30", "30", "-of", "ENVI", "-tap"]
            #cmd = ["gdalwarp", "-cutline", "-crop_to_cutline", "-of", "ENVI"] #PROBAR A DEJAR EL DTM ORIGINAL -9999 A VER SI SALE MEJOR
            cmd.append(gaps)
            cmd.append(gaps_rec)
            cmd.insert(4, shape) #seria el 4/2 con/sin el dst nodata
            proc = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            stdout,stderr=proc.communicate()
            exit_code=proc.wait()

            if exit_code: 
                raise RuntimeError(stderr)
            else:
                print(stdout)
                print('recorte de hillshade generado')
            
            for i in os.listdir(ruta):
                if i.endswith('rec_gaps.img'): 
                    #| i.endswith('_Fmask.TIF'): En princpio Fmask ya no falla
                    rs = os.path.join(ruta, i)
                    gap = gdal.Open(rs)
                    erode = gap.ReadAsArray()
                    
            #Ahora obtenemos el valor del kl para cada banda
            print('entramos en el loop de las bandas')
            for i in os.listdir(ruta):
                #print('Ruta', ruta, i)
                if re.search('rec_B..img$', i):
                #if i.endswith('.TIF'):
                    
                    banda = i[-6:-4]
                    #print('BANDA', i)
                    #if banda in bands:
                    raster = os.path.join(self.data, os.path.join('temp', i))
                    print('RASTER', raster)
                    bandraster = gdal.Open(raster)
                    data = bandraster.ReadAsArray()

                    gapraster = gdal.Open(outfile)
                    gapdata = gapraster.ReadAsArray()
                    #anadimos la distincion entre Fmask y BQA
                    if self.cloud_mask == 'Fmask' or self.cloud_mask == 'Fmask NoTIRS':
                        print('usando Fmask')
                        #Si es anterior al gapfill
                        data2 = data[(erode == 1) & ((Fmask==1) | (((Fmask==0)) & (Hillshade<(np.percentile(Hillshade, 20)))))]
                        #si es posterior al gapfill
                        #data2 = data[((Fmask==1) | (Fmask==0)) & (Hillshade<(np.percentile(Hillshade, 20)))]
                    else:
                        print('usando BQA\ngenerando water mask')

                        for i in os.listdir(ruta):
                            if i.endswith('BQA.TIF'):
                                masker = landsatmasker(os.path.join(ruta, i))  
                                maskwater = masker.getwatermask(confidence.medium) #cogemos la confianza media, a veces no hay nada en la alta
                                #print 'watermin, watermax: ', maskwater.min(), maskwater.max()

                                data2 = data[((data != 0) & ((maskwater==1) | (((Fmask==0)) & (Hillshade<(np.percentile(Hillshade, 20))))))]
                                print('data2: ', data2.min(), data2.max(), data2.size)

                    lista_kl.append(data2.min())#anadimos el valor minimo (podria ser perceniles) a la lista de kl
                    lista = sorted(data2.tolist())
                    print('lista: ', lista[:10])
                    #nmask = (data2<lista[1000])#probar a coger los x valores mas bajos, a ver hasta cual aguanta bien
                    data3 = data2[data2<lista[10000]]
                    print('data3: ', data3.min(), data3.max())

                    df = pandas.DataFrame(data3)
                    #plt.figure(); df.hist(figsize=(10,8), bins = 100)#incluir titulo y rotulos de ejes
                    plt.figure(); df.hist(figsize=(10,8), bins = 50, cumulative=False, color="Red"); 
                    plt.title(self.escena + '_gr_' + banda, fontsize = 18)
                    plt.xlabel("Pixel Value", fontsize=16)  
                    plt.ylabel("Count", fontsize=16)
                    path_rad = os.path.join(self.rad, self.escena)
                    if not os.path.exists(path_rad):
                        os.makedirs(path_rad)
                    name = os.path.join(path_rad, self.escena + '_r_'+ banda.lower() + '.png')
                    plt.savefig(name)

            plt.close('all')
            print('Histogramas generados')

            

            #Hasta aqui tenemos los histogramas generados y los valores minimos guardados en lista_kl, ahora 
            #debemos escribir los valores minimos de cada banda en el archivo kl.rad
            for i in os.listdir(self.rad):

                if i.endswith('l7.rad'):

                    archivo = os.path.join(self.rad, i)
                    dictio = {5: lista_kl[0], 6: lista_kl[1], 7: lista_kl[2], 8: lista_kl[3], 9: lista_kl[4], 10: lista_kl[5]}

                    rad = open(archivo, 'r')
                    rad.seek(0)
                    lineas = rad.readlines()

                    for n, e in enumerate(lineas):

                        if n in dictio.keys():
                            print(lineas[n])
                            lineas[n] = lineas[n].split('=')[0] + '=' + str(dictio[n]) + '\n'
                            print(lineas[n])
                    rad.close()

                    f = open(archivo, 'w')
                    for linea in lineas:
                        f.write(linea)

                    f.close()

                    src = os.path.join(self.rad, i)
                    dst = os.path.join(path_rad, self.escena + '_kl.rad')
                    shutil.copy(src, dst)

        print('modificados los metadatos del archivo kl.rad\nProceso finalizado en ' + str(time.time()-t) + ' segundos')
        #print(lista_kl)
        
    def get_clouds(self):
        
        '''Obtenemos la cobertura de nubes en la escena y lo incluimos en la base de datos'''
        temp = os.path.join(self.data, 'temp')
        nubes = os.path.join(temp, 'clouds_rec.img')
        hill = os.path.join(temp, 'rec_hill.img')
        cota318 = os.path.join(self.data, 'cota318raster.tif')
        
        #De aqui hacemos la mascara de NoData para que el porcenaje lo calcule con el numero de pixeles correctos
        with rasterio.open(hill) as hills:
            HILL = hills.read()
            
        with rasterio.open(nubes) as clouds:
            CLOUD = clouds.read()
            nubes = CLOUD[(CLOUD == 2) | (CLOUD == 4)]
            cobertura = nubes.size * 100 / CLOUD[HILL != 0].size
            print('Cobertura de nubes en la escena:', cobertura)
        
        with rasterio.open(cota318) as cota:
            MASK = cota.read()
            nubes_vdcns = CLOUD[(MASK == 1) & ((CLOUD == 2) | (CLOUD == 4))]
            cobertura_vdcns = nubes_vdcns.size * 100 / MASK[MASK == 1].size
            print('Cobertura de nubes sobre el embalse:', cobertura_vdcns)
            
        #Insertamos los datos en MongoDB
        connection = pymongo.MongoClient("mongodb://localhost")
        db=connection.teledeteccion
        vdcns = db.vdcns
        
        try:
        
            vdcns.update_one({'_id':self.escena}, {'$set':{'Nubes': {'Escena': cobertura, 'Embalse': cobertura_vdcns }}}) 
            
        except Exception as e:
            
            print("Unexpected error:", type(e), e)
        
        
    def move_hdr(self):

        '''-----\n
        Este metodo mueve los hdr generados anteriormente a la carpeta de la escena en rad, que es donde seran necesarios para
        trabajar con GDAL'''

        path_escena_rad = os.path.join(self.rad, self.escena)

        for i in os.listdir(self.ruta_escena):

            if i.endswith('.hdr') and not 'Fmask' in i:

                #bandar = i.replace('_b', '_r_b') Ya tiene la nomenclatura correcta, borrar linea
                hdr = os.path.join(self.ruta_escena, i)
                dst = os.path.join(path_escena_rad, i)
                os.rename(hdr, dst)
                print(hdr, 'movido a rad')

        
    def modify_rel_I(self):

        '''-----\n
        Este metodo modifica el rel de geo para que tenga los valores correctos'''

        process = '\n[QUALITY:LINEAGE:PROCESS2]\nnOrganismes=1\nhistory=reproyeccion\npurpose=reproyeccion por convolucion cubica\ndate=' + str(time.strftime("%Y%m%d %H%M%S00")) + '\n'
        tech = '\n[QUALITY:LINEAGE:PROCESS2:ORGANISME_1]\nIndividualName=Auto Protocol Not so Proudly made by Diego Garcia Diaz\nPositionName=Tecnico LAST\nOrganisationName=(CSIC) LAST-EBD (APP)\n'
        pro = process + tech + '\n'

        ruta = self.mimport
        for i in os.listdir(ruta):
            if i.endswith('rel'):
                rel_file = os.path.join(ruta, i)

        rel = open(rel_file, 'r')
        lineas = rel.readlines()

        if self.sat == 'L8':

            dgeo = {'B1-CA': '_g_b1', 'B10-LWIR1': '_g_b10', 'B11-LWIR2': '_g_b11', 'B2-B': '_g_b2', 'B3-G': '_g_b3', 'B4-R': '_g_b4', 'B5-NIR': '_g_b5', 'B6-SWIR1': '_g_b6', 'B7-SWIR2': '_g_b7',\
                    'B8-PAN': '_g_b8', 'B9-CI': '_g_b9', 'BQA-CirrusConfidence': '_g_BQA-Cirrus', 'BQA-CloudConfidence': '_g_BQA-Cloud', 'BQA-DesignatedFill': '_g_BQA-DFill',\
                    'BQA-SnowIceConfidence': '_g_BQA-SnowIce', 'BQA-TerrainOcclusion': '_g_BQA-Terrain', 'BQA-WaterConfidence': '_g_BQA-Water'}

            for l in range(len(lineas)):


                if lineas[l].startswith('IndexsNomsCamps'):
                    lineas[l] = 'IndexsNomsCamps=1-CA,2-B,3-G,4-R,5-NIR,6-SWIR1,7-SWIR2,9-CI\n'
                elif lineas[l].startswith('NomFitxer=LC8_202034'):
                    bandname = lineas[l][30:-8]
                    lineas[l] = 'NomFitxer='+self.escena+dgeo[bandname]+'.img\n'
                elif lineas[l] == '[ATTRIBUTE_DATA:8-PAN]\n':
                    start_b8 = l
                elif lineas[l] == '[ATTRIBUTE_DATA:9-CI]\n':
                    end_b8 = l
                elif lineas[l].startswith('NomCamp_10-LWIR1=10-LWIR1'):
                    start_band_name = l
                elif lineas[l].startswith('NomCamp_17=QA-CloudConfidence'):
                    end_band_name = l+1
                elif lineas[l].startswith('[ATTRIBUTE_DATA:10-LWIR1]'):
                    start_end = l
                else: continue

            rel.close()

            new_list = lineas[:start_band_name]+lineas[end_band_name:start_b8]+lineas[end_b8:start_end]
            new_list.remove('NomCamp_8-PAN=8-PAN\n')

            f = open(rel_file, 'w')
            for linea in new_list:
                f.write(linea)

            f.close()

        elif self.sat == 'L7': 


            dgeo = {'B1-B': '_g_b1', 'B2-G': '_g_b2', 'B3-R': '_g_b3', 'B4-IRp': '_g_b4', 'B5-IRm1': '_g_b5', 'B6-IRt': '_g_b6', 'B7-IRm2': '_g_b7',\
                'B8-PAN': '_g_b8', 'B9-IRt_HG': '_g_b9'}

            for l in range(len(lineas)):

                if lineas[l].startswith('IndexsNomsCamps'):
                    lineas[l] = 'IndexsNomsCamps=1-B,2-G,3-R,4-IRp,5-IRm1,7-IRm2\n'
                elif lineas[l].startswith('NomFitxer=LE7_202034'):
                    bandname = lineas[l][30:-8]
                    lineas[l] = 'NomFitxer='+self.escena+dgeo[bandname]+'.img\n'
                elif lineas[l] == '[ATTRIBUTE_DATA:6-IRt]\n':
                    start_b6 = l-1
                elif lineas[l] == '[ATTRIBUTE_DATA:7-IRm2]\n':
                    start_b7 = l
                elif lineas[l] == ('[ATTRIBUTE_DATA:8-PAN]\n'):
                    start_b8 = l
                else: continue

            rel.close()

            new_list = lineas[:start_b6]+lineas[start_b7:start_b8]
            new_list.remove('NomCamp_6-IRt=6-IRt\n')
            new_list.remove('NomCamp_9-IRt_HG=9-IRt_HG\n')
            new_list.remove('NomCamp_8-PAN=8-PAN\n')

            f = open(rel_file, 'w')
            for linea in new_list:
                f.write(linea)

            f.close()


        else: 


            dgeo = {'B1-B': '_g_b1', 'B2-G': '_g_b2', 'B3-R': '_g_b3', 'B4-IRp': '_g_b4', 'B5-IRm1': '_g_b5', 'B6-IRt': '_g_b6', 'B7-IRm2': '_g_b7'}

            for l in range(len(lineas)):


                if lineas[l].startswith('IndexsNomsCamps'):
                    lineas[l] = 'IndexsNomsCamps=1-B,2-G,3-R,4-IRp,5-IRm1,7-IRm2\n'
                elif lineas[l].startswith('NomFitxer=LT5_202034'):
                    bandname = lineas[l][30:-8]
                    lineas[l] = 'NomFitxer='+self.escena+dgeo[bandname]+'.img\n'
                elif lineas[l] == '[ATTRIBUTE_DATA:6-IRt]\n':
                    start_b6 = l-1
                elif lineas[l] == '[ATTRIBUTE_DATA:7-IRm2]\n':
                    start_b7 = l
                else: continue

            rel.close()

            new_list = lineas[:start_b6]+lineas[start_b7:]
            new_list.remove('NomCamp_6-IRt=6-IRt\n')

            f = open(rel_file, 'w')
            for linea in new_list:
                f.write(linea)

            f.close()

    def get_Nodtm(self):
        
        '''-----\n
        Este metodo genera un dtm con valor 0  con la extension de la escena que estemos tratando'''
        
        shape = r'O:\VDCNS\protocolo\data\temp\poly_escena.shp'
        nodtm = r'O:\VDCNS\protocolo\data\temp\Nodtm.img' 

        cmd = ["gdal_rasterize -tr 30 30 -ot Byte -of ENVI -burn 0 -l poly_escena", shape, nodtm]


        s = (" ").join(cmd)
        a = os.system(s)
        a
        if a == 0:
            print('Nodtm generado')
        else:
            print('Something went wrong with Nodtm')
        
        #Ahora vamos a generar el .doc para el Nodtm
        for i in os.listdir(self.mimport):
            if re.search('B1.*doc$', i):
                #if i.endswith('B1-CA_00.doc'):
                b1 = os.path.join(self.mimport, i)
        
        dst = nodtm[:-4] + '.doc'
        shutil.copy(b1, dst)
        
        #Ahora vamos a modificar el doc para que tenga los valores adecuados
        archivo = r'O:\VDCNS\protocolo\data\temp\Nodtm.doc'

        doc = open(archivo, 'r')
        doc.seek(0)
        lineas = doc.readlines()

        for l in range(len(lineas)):

            if lineas[l].startswith('file title'):
                lineas[l] = 'file title  : \n'
            elif lineas[l].startswith('data type'):
                lineas[l] = 'data type   : byte\n'
            elif lineas[l].startswith('value units'):
                lineas[l] = 'value units : m\n'
            elif lineas[l].startswith('min. value  :'):
                lineas[l] = 'min. value  : 0\n'  
            elif lineas[l].startswith('max. value  :'):
                lineas[l] = 'max. value  : 0\n'
            elif lineas[l].startswith('flag value'):
                lineas[l] = 'flag value  : none\n'
            elif lineas[l].startswith('flag def'):
                lineas[l] = 'flag def\'n  : none\n'
            else: continue

        doc.close()

        f = open(archivo, 'w')
        for linea in lineas:
            f.write(linea)

        f.close()
        print('modificados los metadatos de ', i)


    def get_dtm(self):

        '''------\n
        Este metodo genera el doc necesario para poder usar el dtm de la escena en el corrad'''

        #primero vamos a leer el dtm de la escena para obtener su minimo y maximo
        with rasterio.open(os.path.join(self.data, os.path.join('temp', 'dtm_escena.img'))) as src:
            dtm = src.read()
            minimo = dtm.min()
            maximo = dtm.max()

        #Ahora copiamos un doc de ori
        for i in os.listdir(self.mimport):
            if re.search('B1.*doc$', i):
                src = os.path.join(self.mimport, i)
                dst = os.path.join(self.data, os.path.join('temp', 'dtm_escena.doc'))
                shutil.copy(src, dst)

        #Ahora editamos el doc para que tenga los valores correctos
        archivo = r'O:\VDCNS\protocolo\data\temp\dtm_escena.doc'

        doc = open(archivo, 'r')
        doc.seek(0)
        lineas = doc.readlines()

        for l, e in enumerate(lineas):

            if e.startswith('file title'):
                lineas[l] = 'file title  : \n'
            elif e.startswith('data type'):
                lineas[l] = 'data type   : integer\n'
            elif e.startswith('value units'):
                lineas[l] = 'value units : m\n'
            elif e.startswith('min. value  :'):
                lineas[l] = 'min. value  : {}\n'.format(minimo)  
            elif e.startswith('max. value  :'):
                lineas[l] = 'max. value  : {}\n'.format(maximo)
            else: continue

        doc.close()

        f = open(archivo, 'w')
        for linea in lineas:
            f.write(linea)

        f.close()
        print('modificados los metadatos de ', i)

        
    def createR_bat(self):
        
        '''-----\n
        Este metodo crea el bat para realizar la correcion radiometrica'''

        #Incluimos reflectividades por arriba y por debajo de 100 y 0
        path_escena_rad = os.path.join(self.rad, self.escena)
        corrad = 'C:\MiraMon\CORRAD'
        num1 = '1'
        #dtm = os.path.join(self.rad, 'sindato.img')
        if self.sat == 'L8':
            kl = os.path.join(self.rad, 'kl_l8.rad')
        else:
            kl = os.path.join(self.rad, 'kl_l7.rad')
        
        #REF_SUP y REF_INF es xa el ajuste o no a 0-100, mirar si se quiere o no
        string = '/MULTIBANDA /CONSERVAR_MDT /LIMIT_LAMBERT=73.000000 /REF_SUP_100 /REF_INF_0 /DT=c:\MiraMon'

        for i in os.listdir(self.mimport):
            if re.search('B1-.*img$', i):
                print(i)
                banda1 = os.path.join(self.mimport, i)
            else: continue
        #dtm_ = r'C:\Embalses\data\temp\dtm_escena.img'
        print('el dtm usado es ', self.dtm)
        lista = [corrad, num1, banda1, path_escena_rad, self.dtm, kl, string]
        print(lista)

        batline = (" ").join(lista)

        pr = open(self.bat2, 'w')
        pr.write(batline)
        pr.close()
        

    def callR_bat(self):

        '''-----\n
        Este metodo ejecuta el bat que realiza la correcion radiometrica'''
        
        ti = time.time()
        print('Llamando a Miramon... Miramon!!!!!!')
        a = os.system(self.bat2)
        a
        if a == 0:
            print("Escena corregida con exito en " + str(time.time()-ti) + " segundos")
        else:
            print("No se pudo realizar la correccion de la escena")
        #borramos el archivo bat creado para la importacion de la escena, una vez se ha importado esta
        os.remove(self.bat2)
        
                      
    def rename_rad(self):
        
        '''-----\n
        Este metodo hace el rename de las imagenes corregidas radiometricamente a la nomenclatura "yyyymmddsatpath_row_banda"'''
        
        drad = {'B1': '_r_b1', 'B2': '_r_b2', 'B3': '_r_b3', 'B4': '_r_b4', 'B5': '_r_b5', \
                'B6': '_r_b6', 'B7': '_r_b7', 'B9': '_r_b9'}
        
        path_escena_rad = os.path.join(self.rad, self.escena)
        
        for i in os.listdir(path_escena_rad):
            
            if i.endswith('.doc') or i.endswith('.img'):
                
                print(i)
                if self.sat != 'L4':
                    
                    if len(i) == 33:
                        banda = i[-11:-9]
                    elif len(i) == 34:
                        banda = i[-12:-10]
                    elif len(i) == 35:
                        banda = i[-13:-11]
                    elif len(i) == 36:
                        banda = i[-14:-12]
                    else:
                        banda = i[-15:-13]
                
                else:
                    
                    if len(i) == 32:
                        banda = i[-11:-9]
                    elif len(i) == 33:
                        banda = i[-12:-10]
                    elif len(i) == 34:
                        banda = i[-13:-11]
                    elif len(i) == 35:
                        banda = i[-14:-12]
                    elif len(i) == 36:
                        banda = i[-15:-13]
                    else:
                        banda = i[-16:-14]
                        
                if banda in drad.keys():  

                    print(banda)
                    #print 'diccionario: ', i
                    in_rs = os.path.join(path_escena_rad, i)
                    out_rs = os.path.join(path_escena_rad, self.escena + drad[banda] + i[-4:])
                    os.rename(in_rs, out_rs)

            elif i.endswith('.rel'):

                rel = os.path.join(path_escena_rad, i)
                dst = os.path.join(path_escena_rad, self.escena + '_BI.rel')
                os.rename(rel, dst)
    
    def modify_hdr_rad(self): 
        
        '''-----\n
        Este metodo edita los hdr para que tengan el valor correcto (FLOAT) para poder ser entendidos por GDAL.
        Hay que ver si hay que establecer primero el valor como No Data'''
                
        path_escena_rad = os.path.join(self.rad, self.escena)
        for i in os.listdir(path_escena_rad):
        
            if i.endswith('.hdr'):

                archivo = os.path.join(path_escena_rad, i)
                hdr = open(archivo, 'r')
                hdr.seek(0)
                lineas = hdr.readlines()
                for l in range(len(lineas)):
                    if l == 8:
                        lineas[l] = 'data type = 4\n'
                lineas.append('data ignore value = -3.40282347e+38') 
                 
                hdr.close()

                f = open(archivo, 'w')
                for linea in lineas:
                    f.write(linea)

                f.close()
                print('modificados los metadatos de ', i)
    

    def correct_sup_inf(self):
        
        '''-----\n
        Este metodo soluciona el problema de los pixeles con alta y baja reflectividad, llevando los bajos a valor 0 
        y los altos a 100. La salida sigue siendo en float32 (reales entre 0.0 y 100.0)'''
        
        path_escena_rad = os.path.join(self.rad, self.escena)
        for i in os.listdir(path_escena_rad):
       
            if i.endswith('.img'):
                
                banda = os.path.join(path_escena_rad, i)
                outfile = os.path.join(path_escena_rad, 'crt_' + i)
                            
                with rasterio.open(banda) as src:

                    NB = src.read()
                    NB[NB <= 0.0] = 0
                    NB = NB * 100
                    a = np.around(NB)
                    b = a.astype(int)
                    
                    profile = src.meta
                    profile.update(dtype=rasterio.uint16)

                    with rasterio.open(outfile, 'w', **profile) as dst:
                        dst.write(b.astype(rasterio.uint16))

                            
    def modify_rel_R(self):

        '''-----\n
        Este metodo modifica el rel de rad para que tenga los nombres de las bandas con la nueva nomenclatura. Tambien pasa el NoData a 0 y los
        valores minimos y maximos de cada banda a 0 y 1'''

        path_rad = os.path.join(self.rad, self.escena)

        equiv = {'b1': '1-CA', 'b2': '2-B', 'b3': '3-G', 'b4': '4-R', 'b5': '5-NIR', \
                 'b6': '6-SWIR1', 'b7': '7-SWIR2', 'b9': '9-CI'}
        drad = {}
        drad_min = {}
        drad_max = {}
        l = []

        for i in os.listdir(path_rad):
            
            if i.endswith('.rel'):
                rel = os.path.join(path_rad, i)
            elif i.endswith('.img') and not i.startswith('crt_'):
                banda = str(i[-6:-4])
                print(banda, equiv[banda])
                drad[banda] = 'C:\Miramon\canvirel 1 ' + rel + ' ATTRIBUTE_DATA:' + equiv[banda] +  ' NomFitxer ' + i
                drad_min[banda] = 'C:\Miramon\canvirel 1 ' + rel + ' ATTRIBUTE_DATA:' + equiv[banda] +  ' min ' + '0'
                drad_max[banda] = 'C:\Miramon\canvirel 1 ' + rel + ' ATTRIBUTE_DATA:' + equiv[banda] +  ' max ' + '10000'
                
        for i in sorted(drad.values()):
            l.append(i + '\n')
        for i in sorted(drad_min.values()):
            l.append(i + '\n')
        for i in sorted(drad_max.values()):
            l.append(i + '\n')
        
        l.append('C:\Miramon\canvirel 1 ' + rel + ' ATTRIBUTE_DATA TipusCompressio uinteger\n')
        l.append('C:\Miramon\canvirel 1 ' + rel + ' ATTRIBUTE_DATA NODATA 0\n')
        l.append('C:\Miramon\canvirel 1 ' + rel + ' ATTRIBUTE_DATA unitats Refls')  
            
        bat = open(r'O:\VDCNS\protocolo\data\temp\rename_rad.bat', 'w')
        bat.seek(0)
        for i in l:
            #print i
            bat.write(i)
        bat.close()

        os.system(r'O:\VDCNS\protocolo\data\temp\rename_rad.bat')

    def clean_rad(self):
        
        '''-----\n
        Este metodo borra los archivos originales saldos del corrad y renombra el resultado de pasarlo a valores
        entre 0 y 10000'''
        
        path_rad = os.path.join(self.rad, self.escena)
        
        for i in os.listdir(path_rad):

            if re.search('^[0-9].*img$', i) or re.search('^[0-9].*hdr$', i) or re.search('^[0-9].*doc$', i):

                arc = os.path.join(path_rad, i)
                os.remove(arc)

            elif re.search('^crt_', i):
                
                arc = os.path.join(path_rad, i)
                dst = os.path.join(path_rad, i[4:])
                os.rename(arc, dst)

    
    def reproject_rad_bands(self):
        
        '''reproyectamos las bandas corregidas radiometricamente con el extent necesario'''
                        
        path_rad_escena = os.path.join(self.rad, self.escena)

        for i in os.listdir(path_rad_escena):
            if self.sat == 'L8':
                lista = [os.path.join(path_rad_escena, i) for i in os.listdir(path_rad_escena) if re.search('b[2-7].img$', i)]
            else:
                lista = [os.path.join(path_rad_escena, i) for i in os.listdir(path_rad_escena) \
                         if re.search('b[1-7].img$', i) if not 'b6.img' in i]
        
        for i in lista:
            
            banda = i[-6:-4]
            shape = r'O:\VDCNS\protocolo\data\Rois_extent.shp'
            salida = os.path.join(self.data, os.path.join('temp', 'rec_' + banda + '_rad.img'))           

            cmd = ["gdalwarp", "-dstnodata" , "0" , "-cutline", "-crop_to_cutline", "-tr", "30", "30", "-of", "ENVI", "-tap"]
            
            cmd.append(i)
            cmd.append(salida)
            cmd.insert(4, shape)
            
            a = (" ").join(cmd)
            print(a) 
            os.system(a)
        
        
        
    ########NORMALIZACION
    def normalize(self):
        
        '''-----\n
        Este metodo controlo el flujo de la normalizacion, si no se llegan a obtener los coeficientes (R>0.85 y N_Pixeles >= 10,
        va pasando hacia el siguiente nivel, hasta que se logran obtener esos valores o hasta que se llega al ultimo paso)'''
        
        path_rad_escena = os.path.join(self.rad, self.escena)
                
        bandasl8 = ['b2', 'b3', 'b4', 'b5', 'b6', 'b7']
        bandasl7 = ['b1', 'b2', 'b3', 'b4', 'b5', 'b7']
        
        if self.sat == 'L8':
            print('landsat 8\n')
            lstbandas = bandasl8
        else:
            print('landsat', self.sat, '\n')
            lstbandas = bandasl7
        
        #Vamos a pasar las bandas recortadas desde temp
        temp = os.path.join(self.data, 'temp')
        for i in os.listdir(temp):
            
            banda = os.path.join(temp, i)
            banda_num = banda[-10:-8]
        
            if banda_num in lstbandas and i.endswith('_rad.img'):
                
                print(banda, ' desde normalize')
                print('Iteracion', self.iter)
                self.nor1(banda, self.rois)
                #Esto es un poco feo, pero funciona. Probar a hacerlo con una lista de funciones
                if banda_num not in self.parametrosnor.keys():
                    self.iter = 1
                    self.iter += 1
                    print('Iteracion', self.iter)
                    self.nor1(banda, self.rois, std = 86)
                    if banda_num not in self.parametrosnor.keys():
                        self.iter += 1
                        print('Iteracion', self.iter)
                        self.nor1(banda, self.rois, std = 129)
                        if banda_num not in self.parametrosnor.keys():
                            print('No se ha podido normalizar la banda ', banda_num)
                                    
            #Una vez acabados los bucles guardamos los coeficientes en un txt. Redundante pero asi hay 
            #que hacerlo porque quiere David
            path_nor = os.path.join(self.nor, self.escena)
            if not os.path.exists(path_nor):
                os.makedirs(path_nor)
            arc = os.path.join(path_nor, 'coeficientes.txt')
            f = open(arc, 'w')
            for i in sorted(self.parametrosnor.items()):
                f.write(str(i)+'\n')
            f.close()  
            
           
            '''connection = pymongo.MongoClient("mongodb://localhost")
            db=connection.teledeteccion
            landsat = db.landsat

            try:

                landsat.update_one({'_id':self.escena}, {'$set':{'Info.Pasos.nor': {'Normalize': 'True', 'Nor-Values': self.parametrosnor, 'Fecha': datetime.now()}}})

            except Exception as e:
                print "Unexpected error:", type(e), e'''
                
    def nor1(self, banda, mascara, std = 43):
        
        '''-----\n
        Este metodo busca obtiene los coeficientes necesarios para llevar a cabo la normalizacion,
        tanto en nor1 como en nor1bis'''

        print('comenzando nor1')
        
        #Ruta a las bandas usadas para normalizar
        ref = os.path.join(self.data, '20000712l7etm202_32')
        path_b1 = os.path.join(ref, 'ref_b1_tap.img')
        path_b2 = os.path.join(ref, 'ref_b2_tap.img')
        path_b3 = os.path.join(ref, 'ref_b3_tap.img')
        path_b4 = os.path.join(ref, 'ref_b4_tap.img')
        path_b5 = os.path.join(ref, 'ref_b5_tap.img')
        path_b7 = os.path.join(ref, 'ref_b7_tap.img')
        
        dnorbandasl8 = {'b2': path_b1, 'b3': path_b2, 'b4': path_b3, 'b5': path_b4, 'b6': path_b5, 'b7': path_b7}
        dnorbandasl7 = {'b1': path_b1, 'b2': path_b2, 'b3': path_b3, 'b4': path_b4, 'b5': path_b5, 'b7': path_b7}
        
        if self.sat == 'L8':
            dnorbandas = dnorbandasl8
        else:
            dnorbandas = dnorbandasl7
            
        path_nor = os.path.join(self.nor, self.escena)
        temp = os.path.join(self.data, 'temp')
        for i in os.listdir(temp):
            
            if i.endswith('clouds_rec.img'):
                mask_nubes = os.path.join(temp, i)
                print('Mascara de nubes: ', mask_nubes)
                            
        with rasterio.open(mask_nubes) as nubes:
            CLOUD = nubes.read()
            print('CLOUD shape', CLOUD.shape)
                
        #Abrimos el raster con los rois
        with rasterio.open(self.rois) as pias:
            PIAS = pias.read()
            print('PIAS shape', PIAS.shape)

        banda_num = banda[-10:-8]
        print(banda_num)
        if banda_num in dnorbandas.keys():
            with rasterio.open(banda) as current:
                CURRENT = current.read()
                print('Banda actual: ', banda, 'Shape:', CURRENT.shape)
            #Aqui con el diccionario nos aseguramos de que estamos comparando cada banda con su homologa del 20020718
            with rasterio.open(dnorbandas[banda_num]) as ref:
                REF = ref.read()
                print('Referencia: ', dnorbandas[banda_num], 'Shape:', REF.shape)
            #Ya tenemos todas las bandas de la imagen actual y de la imagen de referencia leidas como array
            REF2 = REF[(CURRENT != 10001) & ((PIAS != 0) & ((CLOUD == 0) | (CLOUD == 1)))]
            BANDA2 = CURRENT[(CURRENT != 10001) & ((PIAS != 0) & ((CLOUD == 0) | (CLOUD == 1)))]
            PIAS2 = PIAS[(CURRENT != 10001) & ((PIAS != 0) & ((CLOUD == 0) | (CLOUD == 1)))]
            
            #Realizamos la primera regresion
            slope, intercept, r_value, p_value, std_err = linregress(BANDA2,REF2)
            print ('\n++++++++++++++++++++++++++++++++++')
            print('slope: '+ str(slope), 'intercept:', intercept, 'r', r_value, 'N:', PIAS2.size)
            print ('++++++++++++++++++++++++++++++++++\n')
            
            esperado = BANDA2 * slope + intercept
            residuo = REF2 - esperado
                        
            #Ahora calculamos el residuo para hacer la segunda regresion

            mask_current_PIA_NoData_STD = np.ma.masked_where(abs(residuo)>=43, BANDA2)
            mask_ref_PIA_NoData_STD = np.ma.masked_where(abs(residuo)>=43,REF2)
            mask_pias_PIA_NoData_STD = np.ma.masked_where(abs(residuo)>=43,PIAS2)

            current_PIA_NoData_STD = np.ma.compressed(mask_current_PIA_NoData_STD)
            ref_PIA_NoData_STD = np.ma.compressed(mask_ref_PIA_NoData_STD)
            pias_PIA_NoData_STD = np.ma.compressed(mask_pias_PIA_NoData_STD)

            #Hemos enmascarado los resiudos, ahora calculamos la 2 regresion
            slope, intercept, r_value, p_value, std_err = linregress(current_PIA_NoData_STD,ref_PIA_NoData_STD)
            print ('\n++++++++++++++++++++++++++++++++++')
            print ('slope: '+ str(slope), 'intercept:', intercept, 'r', r_value, 'N:', len(ref_PIA_NoData_STD))
            print ('++++++++++++++++++++++++++++++++++\n')
            
            
            #Comprobamos el numero de pixeles por cada area pseudo invariante
            values = {}
            values_str = {1: 'Embalses', 2: 'Asfalto', 3: 'Urbano', 4: 'Vegetacion', 5: 'Mineria',\
                          6: 'Canchales', 7: 'Suelos de Montana'}
            
            print('Vamos a sacar el count de cada zona (dict)')
            for i in range(1,8):

                mask_pia_= np.ma.masked_where(pias_PIA_NoData_STD != i, pias_PIA_NoData_STD)
                PIA = np.ma.compressed(mask_pia_)
                a = PIA.tolist()
                values[values_str[i]] = len(a)
                print('Values_dict:', values)
            #pasamos las claves de cada zona a string
            #for i in values.keys():
                #values[values_str[i]] = values.pop(i)
            #print(values,)  #imprime el count de pixeles xa cada zona
            print(banda_num)
            #Generamos el raster de salida despues de aplicarle la ecuacion de regresion. Esto seria el nor2
            #Por aqui hay que ver como se soluciona
            if r_value > 0.85 and min(values.values()) >= 10:
                self.parametrosnor[banda_num]= {'Parametros':{'slope': slope, 'intercept': intercept, 'r': r_value, \
                                                'N': len(ref_PIA_NoData_STD), 'iter': self.iter}, 'Tipo_Area': values}
                
                print('parametros en nor1: ', self.parametrosnor)
                print('\comenzando nor2 con la banda:', banda[-10:-8], '\n')
                #Hemos calculado la regresion con las bandas recortadas con Rois_extent
                #Ahora vamos a pasar las bandas de rad (completas) para aplicar la ecuacion de regresion
                rutarad = os.path.join(self.rad, self.escena)
                print('Ruta Rad:', rutarad)
                for r in os.listdir(rutarad):
                    if banda[-10:-8] in r and r.endswith('.img'):
                        print('banda:', r)
                        raster = os.path.join(rutarad, r)
                        print('La banda que se va a normalizar es:', raster)
                        self.nor2l8(raster, slope, intercept)#Aqui hay que cambiar para que llame a las bandas de rad
                        print('\nNormalizacion de ', banda_num, ' realizada.\n')
                        
                    plt.scatter(current_PIA_NoData_STD, ref_PIA_NoData_STD)
            else:
                pass
                                       
                    
    def nor2l8(self, banda, slope, intercept):
    
        '''-----\n
        Este metodo aplica la ecuacion de la recta de regresion a cada banda (siempre que los haya podido obtener), y posteriormente
        reescala los valores para seguir teniendo un byte (0-255)'''
        
        #path_geo = os.path.join(self.geo, self.escena)
        print('estamos en nor2!')
        path_nor_escena = os.path.join(self.nor, self.escena)
        if not os.path.exists(path_nor_escena):
            os.makedirs(path_nor_escena)
        banda_num = banda[-6:-4]
        outFile = os.path.join(path_nor_escena, self.escena + '_grn1_' + banda_num + '.img')
        print('Outfile', outFile)
        
        #metemos la referencia para el NoData, vamos a coger la banda 5 en geo (... Y por que no?)
        for i in os.listdir(self.ruta_escena):
            if i.endswith('B5.TIF'):
                
                ref = os.path.join(self.ruta_escena, i)
        
        with rasterio.open(ref) as src:
            ref_rs = src.read()
        
        with rasterio.open(banda) as src:

            rs = src.read()
            rs = rs*slope+intercept

            nd = (ref_rs == 0)
            min_msk =  (rs < 0)             
            max_msk = (rs>=10001)

            rs[min_msk] = 0
            rs[max_msk] = 10001

            rs = np.around(rs)
            rs[nd] = 10001

            profile = src.meta
            profile.update(dtype=rasterio.uint16)

            with rasterio.open(outFile, 'w', **profile) as dst:
                dst.write(rs.astype(rasterio.uint16))
        #No data en 254!!


    def run(self):

        self.fmask()
        self.fmask_legend()
        self.get_hdr()
        self.clean_ori()
        self.createI_bat()
        self.callI_bat()
        self.get_kl_csw()
        self.get_clouds()
        self.get_Nodtm()
        self.get_dtm()
        self.modify_rel_I()
        self.createR_bat()
        self.callR_bat()
        self.rename_rad()
        self.move_hdr()
        self.modify_hdr_rad()
        self.correct_sup_inf()
        self.modify_rel_R()
        self.clean_rad()
        self.reproject_rad_bands()
        self.normalize()
        
        #Sacamos los valores del kl.
        print('vamos a anadir los valores del kl')
        path_rad = os.path.join(self.rad, self.escena)
        for i in os.listdir(path_rad):
            
            if i.endswith('.rad') :
                rad = os.path.join(path_rad, i)
                f = open(rad, 'r')
                lista = []
                for l in f:
                    if re.search('Kl=', l) and not l.startswith(';'):
                        kl = int(l.split('=')[1].rstrip())
                        lista.append(kl)       
                f.close()
                
        bandas = ['b1', 'b2', 'b3', 'b4', 'b5', 'b6', 'b7', 'b9']
        bandasl7 = ['b1', 'b2', 'b3', 'b4', 'b5', 'b7']
        
        if self.sat == 'L8':
            kl_values = dict(zip(bandas, lista))
        else:
            kl_values = dict(zip(bandasl7, lista))
                
        #Insertamos los datos en MongoDB
        connection = pymongo.MongoClient("mongodb://localhost")
        db=connection.teledeteccion
        vdcns = db.vdcns
        
        try:
        
            vdcns.update_one({'_id':self.escena}, {'$set':{'kl': {'Kl-Values': kl_values}}})
            
        except Exception as e:
            print("Unexpected error:", type(e), e)