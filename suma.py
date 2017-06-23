import os, arcpy, arcinfo
from arcpy import env
from arcpy.sa import *

# Set the current workspace
# 
env.workspace = r'G:\VDCNS\protocolo\pro'
env.extent = "MAXOF"

#Check out ArcGIS Spatial Analyst extension license
arcpy.CheckOutExtension("Spatial")


# Get a list of ESRI GRIDs from the workspace and print
#
rasterList = arcpy.ListRasters()
ruta = r'G:\VDCNS\protocolo\pro'
for i in os.listdir(ruta):

	nruta = os.path.join(ruta, i)
	for r in os.listdir(nruta):

		if r.endswith('evi_reclass.img'):

			raster = os.path.join(nruta, r)
			rasterList.append(raster) #= arcpy.ListRasters("*", "TIF")

# Execute CellStatistics
outCellStatistics = CellStatistics(rasterList, "SUM", "DATA")

# Save the output 
outCellStatistics.save(r'G:\VDCNS\protocolo\pro\suma_evi.TIF')