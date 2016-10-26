######## PROTOCOLO AUTOMATICO PARA LA CORRECCION RADIOMETRICA DE ESCENAS LANDSAT 8 #######
######                                                                              ######
####                        Autor: Diego Garcia Diaz                                  ####
###                      email: digd.geografo@gmail.com                                ###
##            GitHub: https://github.com/Digdgeo/Landsat8_Corrad_Embalses               ##
#                        Sevilla 01/01/2016-31/03/2016                                   #

# coding: utf-8

import os, shutil, re, time, subprocess, pandas, rasterio, sys, urllib, sqlite3
import numpy as np
import matplotlib.pyplot as plt
from osgeo import gdal, gdalconst
from pymasker import landsatmasker, confidence
from datetime import datetime, date
from IPython.display import Image
from IPython.display import display

class Landsat(object):
    
     
    '''Esta clase esta hecha para corregir radiometricamente escenas Landsat 8, de cara a obtener coeficientes de dsitintos parametros fisico-quimicos
    en algunos Embalses de la cuenca del Guadalquivir.

    El unico software necesario es Miramon, que se utiliza por su gestion de Metadatos. Se emplea en la Importacion y en la Correccion Radiometrica
    y se llama mediante archivos bat. Para el resto de procesos se usan GDAL, Rasterio y otras librerias de Python. En general se tratan los rasters
    como arrays, lo que produce un rendimiento en cuanto a la velocidad de procesado bastante elevado. Para la normalizacion se emple tambien una 
    mascara de nubes, que se obtiene empleando Fmask o la banda de calidad de Landsat 8 si fallara Fmask.

    El script requiere una estructura de carpetas en un mismo nivel (/ori, /rad y /data). En /data deben de estar los archivos necesarios para
    llevar a cabo el proceso:

        1) Shape con los limites de los Embalses a tratar
        2) Shape de puntos con los lugares de los que hay datos de campo, para hacer un "extract_values_to_point"
        3) Modelo Digital del Terreno lo bastante amplio como para englobar cualquier escena *
        *) Al tener escenas en huso 29 y huso 30 se ha optado por tener 2 dtms (de la peninsula completa) uno en 29 y otro en 30, automaticamente se elige el adecuado

    Ademas de estos requisitos, en la carpeta /rad debe de haber un archivos kl_l8.rad donde se guardaran temporalmente los valores
    del objeto oscuro (proceso empleado para la Correccion Radiometrica). 

    Al finalizar el proceso tendremos en ori, y rad las bandas (de la 1  la 9 sin la pancromatica) en formato img + doc + rel + hdr pasadas ya de niveles digitales
    a reflectancia en superficie y toda la informacion del proceso almacenada en una base de datos SQLite'''
    
    
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
        self.data = os.path.join(self.raiz, 'data')
        self.umbral = umbral
        self.hist = hist
        if dtm == 'plano':
            self.dtm = os.path.join(self.data, 'temp\Nodtm.img')
        else:
            self.dtm = os.path.join(self.data, 'temp\dtm_escena.img')

        #metemos una variable que almacene el tipo de satelite
        if 'l8oli' in self.escena:
            self.sat = 'L8'
        else:
            print 'no reconozco el satelite'
            
        if self.sat == 'L8':
            self.mimport = os.path.join(self.ruta_escena, 'miramon_import')
        if not os.path.exists(self.mimport):
            os.makedirs(self.mimport)
            
        self.bat = os.path.join(self.ruta_escena, 'import.bat')
        self.bat2 = os.path.join(self.rad, 'importRad.bat')
        self.cloud_mask = None 
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
            s = "http://earthexplorer.usgs.gov/browse/etm/202/34/" + self.escena[:4] + "/" + usgs_id + "_REFL.jpg"
        elif self.sat == 'L5':
            s = "http://earthexplorer.usgs.gov/browse/tm/202/34/" + self.escena[:4] + "/" + usgs_id + "_REFL.jpg"

        qcklk.write(urllib.urlopen(s).read())
        
        display(Image(url=s, width=500))

        #BASE DE DATOS SQLITE!
        #
        #
        #Creamos la base de datos y la primera tabla Escenas
        conn = sqlite3.connect(r'C:\Embalses\data\Embalses.db')
        cur = conn.cursor()
        print "Opened database successfully"

        conn.execute('''CREATE TABLE IF NOT EXISTS 'Escenas' (
                        'Escena'    TEXT NOT NULL PRIMARY KEY UNIQUE,
                        'Sat' TEXT,
                        'Path'  TEXT,
                        'Row'   TEXT,
                        'Fecha_Escena'  DATE,
                        'Fecha_Procesado'   DATETIME
                        )''');

        print "Table Escenas created successfully"

        conn.execute('''CREATE TABLE IF NOT EXISTS 'Kl' (
                        'id_escena' TEXT NOT NULL UNIQUE,
                        'B1'    INTEGER,
                        'B2'    INTEGER,
                        'B3'    INTEGER,
                        'B4'    INTEGER,
                        'B5'    INTEGER,
                        'B6'    INTEGER,
                        'B7'    INTEGER,
                        'B9'    INTEGER,
                        PRIMARY KEY(id_escena)
                        )''');

        print "Table Kl created successfully"

        conn.execute('''CREATE TABLE IF NOT EXISTS 'Puntos' (
                        'id'    INTEGER PRIMARY KEY,
                        'Coordenada_X'    DECIMAL,
                        'Coordenada_Y' DECIMAL,
                        'Nombre' TEXT,
                        'Huso' TEXT
                        )''');

        print "Table Puntos created successfully"

        conn.execute('''CREATE TABLE  IF NOT EXISTS  'Indices' (
                        'id'    TEXT PRIMARY KEY,
                        'Indice'    TEXT UNIQUE
                        )''');

        print "Table Indices created successfully"

        conn.execute('''CREATE TABLE  IF NOT EXISTS 'Puntos_Indices' (
                        'id_indices'    TEXT,
                        'id_puntos'    INTEGER,
                        'id_escenas' TEXT,
                        'Valor' REAL,
                        PRIMARY KEY ('id_indices', 'id_puntos', 'id_escenas')
                        )''');

        print "Table Puntos-Indices created successfully"

        conn.execute('''CREATE TABLE  IF NOT EXISTS 'Reflectividades' (
                        'id_puntos' INTEGER,
                        id_escenas TEXT,
                        'B1'    REAL,
                        'B2'    REAL,
                        'B3'    REAL,
                        'B4'    REAL,
                        'B5'    REAL,
                        'B6'    REAL,
                        'B7'    REAL,
                        'B8'   REAL,
                        'B8A'   REAL,
                        'B9'    REAL,
                        'B10'    REAL,
                        'B11'   REAL,
                        'B12'    REAL,
                        PRIMARY KEY ('id_puntos', 'id_escenas') 
                        )''');

        print "Table Reflectividades created successfully"

        try:

            cur.execute('''INSERT OR REPLACE INTO Escenas (Escena, Sat, Path, Row, Fecha_Escena, Fecha_Procesado) 
                VALUES ( ?, ?, ?, ?, ?, ?)''', (self.escena, self.sat, str(self.escena[-6:-3]), str(self.escena[-2:]), \
                    date(int(self.escena[:4]), int(self.escena[4:6]), int(self.escena[6:8])), datetime.now() ));

 
        except Exception as e: 
            
            print e

        conn.commit()
        conn.close()
            
            
    -
                
    def fmask_doc(self):
        
        '''-----\n
        Este metodo anade el archivo .doc necesario para que MIramon entienda el raster al tiempo que reconoce que
        se tratar de una raster categorico con sus correspondientes valores (Sin definir, Agua, Sombra de nubes, Nieve, Nubes).'''
        
    def get_hdr(self):
        
        '''-----\n
        Este metodo genera los hdr para cada banda, de cara a poder trabajar posteriormente con ellas en GDAL, ENVI u otro software'''
        
        dgeo = {'B1': '_r_b1.img', 'B2': '_r_b2.img', 'B3': '_r_b3.img', 'B4': '_r_b4.img', 'B5': '_r_b5.img',  \
                   'B6': '_r_b6.img', 'B7': '_r_b7.img', 'B8': '_r_b8.img', 'B9': '_r_b9.img',  \
                            'B10': '_r_b10.img', 'B11': '_r_b11.img', 'BQA': '_r_bqa.img'}
        
        for i in os.listdir(self.ruta_escena):
            
            if i.endswith('.TIF'):
                
                if len(i) == 28:
                    banda = i[-6:-4]
                elif len(i) == 29:
                    banda = i[-7:-4]
                else:
                    banda = i[-13:-4]
                    
                print banda
                
                if banda in dgeo.keys():
                
                    in_rs = os.path.join(self.ruta_escena, i)
                    out_rs = os.path.join(self.ruta_escena, self.escena + dgeo[banda])
                    string = 'gdal_translate -of ENVI --config GDAL_CACHEMAX 8000 --config GDAL_NUM_THREADS ALL_CPUS {} {}'.format(in_rs, out_rs)
                    print string
                    os.system(string)

        #ahora vamos a borrar los .img y xml que se han generado junto con los 
    
    def clean_ori(self):

        for i in os.listdir(self.ruta_escena):

            if i.endswith('.img') and not 'Fmask' in i or i.endswith('.xml'):
                rs_dl = os.path.join(self.ruta_escena, i)
                print rs_dl
                os.remove(rs_dl)

    def createI_bat(self):
        
        '''-----\n
        Este metodo crea un archivo bat con los parametros necesarios para realizar la importacion'''
        
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
        print lista

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
            print "Escena importada con exito en " + str(time.time()-ti) + " segundos"
        else:
            print "No se pudo importar la escena"
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
            print stdout
            print 'marco generado'

        #ya tenemos el dtm recortado guardado en data/temp, ahora vamos a generar el hillshade.  
        #Para ello primero hay que recortar el dtm con el shape recien obtenido con la extension de la escena
        #vamos a usar la variable 'zone' para usar el dtm reproyectado al huso 30 o 29
        dtm_escena = os.path.join(temp, 'dtm_escena.img')
        if self.zone == 29:

            for i in os.listdir(self.data):
                if i.endswith('29c.img'):
                    dtm = os.path.join(self.data, i)
                    print dtm

        else:

            for i in os.listdir(self.data):
                if i.endswith('30c.img'):
                    dtm = os.path.join(self.data, i)
                    print dtm


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
            print stdout
            print 'dtm_escena generado'

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
            print stdout
            print 'Hillshade generado'

        #Ya esta el hillshade en data/temp. Tambien tenemos ya la Fmask generada en ori, 
        #asi que ya podemos operar con los arrays
        for i in os.listdir(ruta):
            if i.endswith('MTLFmask.img') | i.endswith('_Fmask.TIF'):
                rs = os.path.join(ruta, i)
                fmask = gdal.Open(rs)
                Fmask = fmask.ReadAsArray()
                print 'min, max: ', Fmask.min(), Fmask.max()
        for i in os.listdir(temp):
            if i.endswith('shade.img'):
                rst = os.path.join(temp, i)
                print rst
                hillshade = gdal.Open(rst)
                Hillshade = hillshade.ReadAsArray()

        #Queremos los pixeles de cada banda que esten dentro del valor agua (1) y sin nada definido ((0) 
        #para las sombras) de la Fmask (con lo cual tambien excluimos las nubes y sombras de nubes). 
        #Junto con estos valores, queremos tambien los valores que caen en sombra (se ha decidido que 
        #el valor de corte mas adecuado es el percentil 20)

        #Arriba estamos diciendo que queremos el minimo del agua o de la escena completa sin nubes ni 
        #sombras ni agua pero en sombra orografica

        #Ahora vamos a aplicar la mascara y hacer los histogramas
        # if self.sat == 'L8': En principio solo seran Landsat 8
        bandas = ['B1', 'B2', 'B3', 'B4','B5', 'B6', 'B6', 'B7', 'B9']
        lista_kl = []
        for i in os.listdir(ruta):
            banda = i[-6:-4]
            if banda in bandas:
                raster = os.path.join(ruta, i)
                bandraster = gdal.Open(raster)
                data = bandraster.ReadAsArray()
                #anadimos la distincion entre Fmask y BQA
                if self.cloud_mask == 'Fmask' or self.cloud_mask == 'Fmask NoTIRS':
                    print 'usando Fmask'
                    data2 = data[((Fmask==1) | (((Fmask==0)) & (Hillshade<(np.percentile(Hillshade, 20)))))]

                else:
                    print 'usando BQA\ngenerando water mask'

                    for i in os.listdir(ruta):
                        if i.endswith('BQA.TIF'):
                            masker = landsatmasker(os.path.join(ruta, i))  
                            maskwater = masker.getwatermask(confidence.medium) #cogemos la confianza media, a veces no hay nada en la alta
                            #print 'watermin, watermax: ', maskwater.min(), maskwater.max()

                            data2 = data[((data != 0) & ((maskwater==1) | (((Fmask==0)) & (Hillshade<(np.percentile(Hillshade, 20))))))]
                            print 'data2: ', data2.min(), data2.max(), data2.size

                lista_kl.append(data2.min())#anadimos el valor minimo (podria ser perceniles) a la lista de kl
                lista = sorted(data2.tolist())
                print 'lista: ', lista[:10]
                #nmask = (data2<lista[1000])#probar a coger los x valores mas bajos, a ver hasta cual aguanta bien
                data3 = data2[data2<lista[self.hist]]
                print 'data3: ', data3.min(), data3.max()

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
        print 'Histogramas generados'

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

        print 'modificados los metadatos del archivo kl.rad\nProceso finalizado en ' + str(time.time()-t) + ' segundos'
        print lista_kl
        
                
        #Metemos los valores del objeto oscuro en la Base de Datos
        conn = sqlite3.connect(r'C:\Embalses\data\Embalses.db')
        cur = conn.cursor()
        print "Opened database successfully"

        try:
                
            cur.execute('''INSERT OR REPLACE INTO Kl (id_escena, B1, B2, B3, B4, B5, B6, B7, B9) 
                VALUES ( ?, ?, ?, ?, ?, ?, ?, ?, ? )''', (self.escena, int(lista_kl[0]), int(lista_kl[1]), int(lista_kl[2]), int(lista_kl[3]), int(lista_kl[4]), \
                    int(lista_kl[5]), int(lista_kl[6]), int(lista_kl[7]) ));

        except Exception as e: 
    
            print e

        conn.commit()
        conn.close()


        

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
                print hdr, 'movido a rad'

        
    def modify_rel_I(self):
        
        '''-----\n
        Este metodo escinde las bandas no usadas en la Correccion Radiometrica del rel de la escena importada'''

        for i in os.listdir(self.mimport):
            if i.endswith('.rel'):
                relf = os.path.join(self.mimport, i)
        
        bat = r'C:\Embalses\data\temp\canvi.bat'
        open(bat, 'a').close()
        claves = ['8-PAN', '10-LWIR1', '11-LWIR2', 'QA']
        rel = open(relf, 'r')
        s = 'C:\MiraMon\canvirel 1 ' + relf + ' ATTRIBUTE_DATA IndexsNomsCamps 1-CA,2-B,3-G,4-R,5-NIR,6-SWIR1,7-SWIR2,9-CI\n'

        b8 = 'C:\MiraMon\canvirel 2 ' + relf + ' ATTRIBUTE_DATA NomCamp_8-PAN\n'
        b10 = 'C:\MiraMon\canvirel 2 ' + relf + ' ATTRIBUTE_DATA NomCamp_10-LWIR1\n'
        b11 = 'C:\MiraMon\canvirel 2 ' + relf + ' ATTRIBUTE_DATA NomCamp_11-LWIR2\n'
        b12 = 'C:\MiraMon\canvirel 2 ' + relf + ' ATTRIBUTE_DATA NomCamp_12\n'
        b13 = 'C:\MiraMon\canvirel 2 ' + relf + ' ATTRIBUTE_DATA NomCamp_13\n'
        b14 = 'C:\MiraMon\canvirel 2 ' + relf + ' ATTRIBUTE_DATA NomCamp_14\n'
        b15 = 'C:\MiraMon\canvirel 2 ' + relf + ' ATTRIBUTE_DATA NomCamp_15\n'
        b16 = 'C:\MiraMon\canvirel 2 ' + relf + ' ATTRIBUTE_DATA NomCamp_16\n'
        b17 = 'C:\MiraMon\canvirel 2 ' + relf + ' ATTRIBUTE_DATA NomCamp_17\n'

        lbat = [s, b8, b10, b11, b12, b13, b14, b15, b16, b17]

        lrel = rel.readlines()
        for i in lrel:
            for c in claves:
                if i.startswith('[') and c in i:
                    lbat.append(os.path.join('C:\MiraMon\canvirel 3 ' + relf + ' ' + i[1:-2] +'\n')) 
        rel.close()

        f = open(bat, 'w')
        for linea in lbat:
            f.write(linea)
        f.close()
        
        a = os.system(bat)
        a
        if a == 0:    
            print 'modificados los metadatos del bat'
        else:
            print 'canvirel didn\'t work'
        
        
    def get_Nodtm(self):
        
        '''-----\n
        Este metodo genera un dtm con valor 0  con la extension de la escena que estemos tratando'''
        
        shape = r'C:\Embalses\data\temp\poly_escena.shp'
        nodtm = r'C:\Embalses\data\temp\Nodtm.img' 

        cmd = ["gdal_rasterize -tr 30 30 -ot Byte -of ENVI -burn 0 -l poly_escena", shape, nodtm]


        s = (" ").join(cmd)
        a = os.system(s)
        a
        if a == 0:
            print 'Nodtm generado'
        else:
            print 'Something went wrong with Nodtm'
        
        #Ahora vamos a generar el .doc para el Nodtm
        for i in os.listdir(self.mimport):
            if i.endswith('B1-CA_00.doc'):
                b1 = os.path.join(self.mimport, i)
        
        dst = nodtm[:-4] + '.doc'
        shutil.copy(b1, dst)
        
        #Ahora vamos a modificar el doc para que tenga los valores adecuados
        archivo = r'C:\Embalses\data\temp\Nodtm.doc'

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
        print 'modificados los metadatos de ', i


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
            if i.endswith('B1-CA_00.doc'):
                src = os.path.join(self.mimport, i)
                dst = os.path.join(self.data, os.path.join('temp', 'dtm_escena.doc'))
                shutil.copy(src, dst)

        #Ahora editamos el doc para que tenga los valores correctos
        archivo = r'C:\Embalses\data\temp\dtm_escena.doc'

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
        print 'modificados los metadatos de ', i

        
    def createR_bat(self):
        
        '''-----\n
        Este metodo crea el bat para realizar la correcion radiometrica'''

        #Incluimos reflectividades por arriba y por debajo de 100 y 0
        path_escena_rad = os.path.join(self.rad, self.escena)
        corrad = 'C:\MiraMon\CORRAD'
        num1 = '1'
        #dtm = os.path.join(self.rad, 'sindato.img')
        kl = os.path.join(self.rad, 'kl_l8.rad')
        
        #REF_SUP y REF_INF es xa el ajuste o no a 0-100, mirar si se quiere o no
        string = '/MULTIBANDA /CONSERVAR_MDT /LIMIT_LAMBERT=73.000000 /REF_SUP_100 /REF_INF_0 /DT=c:\MiraMon'

        for i in os.listdir(self.mimport):
            if i.endswith('B1-CA_00.img'):
                banda1 = os.path.join(self.mimport, i)
            else: continue
        #dtm_ = r'C:\Embalses\data\temp\dtm_escena.img'
        print 'el dtm usado es ', self.dtm
        lista = [corrad, num1, banda1, path_escena_rad, self.dtm, kl, string]
        print lista

        batline = (" ").join(lista)

        pr = open(self.bat2, 'w')
        pr.write(batline)
        pr.close()
        

    def callR_bat(self):

        '''-----\n
        Este metodo ejecuta el bat que realiza la correcion radiometrica'''
        
        ti = time.time()
        print 'Llamando a Miramon... Miramon!!!!!!'
        a = os.system(self.bat2)
        a
        if a == 0:
            print "Escena corregida con exito en " + str(time.time()-ti) + " segundos"
        else:
            print "No se pudo realizar la correccion de la escena"
        #borramos el archivo bat creado para la importacion de la escena, una vez se ha importado esta
        os.remove(self.bat2)
        
        
    def rename_rad(self):
        
        '''-----\n
        Este metodo hace el rename de las imagenes corregidas radiometricamente a la nomenclatura "yyyymmddsatpath_row_banda"'''
        
        drad = {'B1': '_r_b1', 'B2': '_r_b2', 'B3': '_r_b3', 'B4': '_r_b4', 'B5': '_r_b5', 'B6': '_r_b6', 'B7': '_r_b7', 'B9': '_r_b9'}
        
        path_escena_rad = os.path.join(self.rad, self.escena)
        
        for i in os.listdir(path_escena_rad):
            
            if i.endswith('.doc') or i.endswith('.img'):
                
                print i
                
                if len(i) == 33:
                    banda = i[-11:-9]
                elif len(i) == 34:
                    banda = i[-12:-10]
                elif len(i) == 35:
                    banda = i[-13:-11]
                else:
                    banda = i[-15:-13]

                if banda in drad.keys():  

                    print banda
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
                print 'modificados los metadatos de ', i
    

    def correct_sup_inf(self):
        
        '''-----\n
        Este metodo soluciona el problema de los pixeles con alta y baja reflectividad, llevando los bajos a valor 0 
        y los altos a 100. La salida sigue siendo en float32 (reales entre 0.0 y 100.0)'''
        
        path_escena_rad = os.path.join(self.rad, self.escena)
        for i in os.listdir(path_escena_rad):
       
            if i.endswith('.img'):
                
                banda = os.path.join(path_escena_rad, i)
                outfile = os.path.join(path_escena_rad, 'crt_' + i)
                
                with rasterio.drivers():
                    with rasterio.open(banda) as src:
                        rs = src.read()
                        rs = rs/100
                        rs = np.where(((rs>rs.min()) & (rs<=0)), 0.0001, rs)
                        rs = np.where(rs>1, 1, rs)
                        rs = np.where(rs==rs.min(), 0, rs)

                        profile = src.meta
                        profile.update(dtype=rasterio.float32)

                        with rasterio.open(outfile, 'w', **profile) as dst:
                            dst.write(rs.astype(rasterio.float32))

                            
    def modify_rel_R(self):

        '''-----\n
        Este metodo modifica el rel de rad para que tenga los nombres de las bandas con la nueva nomenclatura. Tambien pasa el NoData a 0 y los
        valores minimos y maximos de cada banda a 0 y 1'''

        path_rad = os.path.join(self.rad, self.escena)

        equiv = {'b1': '1-CA', 'b2': '2-B', 'b3': '3-G', 'b4': '4-R', 'b5': '5-NIR', 'b6': '6-SWIR1', 'b7': '7-SWIR2', 'b9': '9-CI'}
        drad = {}
        drad_min = {}
        drad_max = {}
        l = []

        for i in os.listdir(path_rad):
            
            if i.endswith('.rel'):
                rel = os.path.join(path_rad, i)
            elif i.endswith('.img') and not i.startswith('crt_'):
                banda = str(i[-6:-4])
                print banda, equiv[banda]
                drad[banda] = 'C:\Miramon\canvirel 1 ' + rel + ' ATTRIBUTE_DATA:' + equiv[banda] +  ' NomFitxer ' + i
                drad_min[banda] = 'C:\Miramon\canvirel 1 ' + rel + ' ATTRIBUTE_DATA:' + equiv[banda] +  ' min ' + '0.0001'
                drad_max[banda] = 'C:\Miramon\canvirel 1 ' + rel + ' ATTRIBUTE_DATA:' + equiv[banda] +  ' max ' + '1'
                
        for i in sorted(drad.values()):
            l.append(i + '\n')
        for i in sorted(drad_min.values()):
            l.append(i + '\n')
        for i in sorted(drad_max.values()):
            l.append(i + '\n')
            
        l.append('C:\Miramon\canvirel 1 ' + rel + ' ATTRIBUTE_DATA NODATA 0\n')
        l.append('C:\Miramon\canvirel 1 ' + rel + ' ATTRIBUTE_DATA unitats Refls')  
            
        bat = open(r'C:\Embalses\data\temp\rename_rad.bat', 'w')
        bat.seek(0)
        for i in l:
            #print i
            bat.write(i)
        bat.close()

        os.system(r'C:\Embalses\data\temp\rename_rad.bat')

    def clean_rad(self):
        
        '''-----\n
        Este metodo borra los archivos originales saldos del corrad y renombra el resultado de pasarlo a valores entre 0 y 1'''
        
        path_rad = os.path.join(self.rad, self.escena)
        
        for i in os.listdir(path_rad):

            if re.search('^[0-9].*img$', i) or re.search('^[0-9].*hdr$', i) or re.search('^[0-9].*doc$', i):

                arc = os.path.join(path_rad, i)
                os.remove(arc)

            elif re.search('^crt_', i):
                
                arc = os.path.join(path_rad, i)
                dst = os.path.join(path_rad, i[4:])
                os.rename(arc, dst)

    def sr_sac(self):
        pass


    def run(self):

        self.fmask()
        self.fmask_legend()
        self.get_hdr()
        self.clean_ori()
        self.createI_bat()
        self.callI_bat()
        self.get_kl_csw()
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
