import os, arcpy, arcinfo
from arcpy import env
from arcpy.sa import *

# Set the current workspace
# 
env.workspace = r'O:\VDCNS\Landsat\extents'
env.extent = "MAXOF"

#Check out ArcGIS Spatial Analyst extension license
arcpy.CheckOutExtension("Spatial")


# Get a list of ESRI GRIDs from the workspace and print
#
rasterList = arcpy.ListRasters()
ruta = r'O:\VDCNS\Landsat\extents'
for i in os.listdir(ruta):

	nruta = os.path.join(ruta, i)
	for r in os.listdir(nruta):

		if r.startswith('suma') and r.endswith('.TIF'):

			raster = os.path.join(nruta, r)
			rasterList.append(raster) #= arcpy.ListRasters("*", "TIF")

# Execute CellStatistics
outCellStatistics = CellStatistics(rasterList, "SUM", "DATA")

# Save the output 
outCellStatistics.save(r'O:\VDCNS\Landsat\extents\suma_last.TIF')