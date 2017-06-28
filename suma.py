import os, arcpy, arcinfo
from arcpy import env
from arcpy.sa import *

# Set the current workspace

env.overwriteOutput = True
env.workspace = r'G:\VDCNS\protocolo\pro'
env.extent = "MAXOF"

#Check out ArcGIS Spatial Analyst extension license
arcpy.CheckOutExtension("Spatial")


# Get a list of ESRI GRIDs from the workspace and print
#
rasterList = []
ruta = r'G:\VDCNS\protocolo\pro'
for i in os.listdir(ruta):

	nruta = os.path.join(ruta, i)

	if os.path.isdir(nruta):
		for r in os.listdir(nruta):

			if r.endswith('binwater.img'):
				if int(os.path.split(r)[1][:4]) < 2007:

					raster = os.path.join(nruta, r)
					rasterList.append(raster) #= arcpy.ListRasters("*", "TIF")

print len(rasterList)
# Execute CellStatistics
outCellStatistics = CellStatistics(rasterList, "SUM", "DATA")

# Save the output
outCellStatistics.save(r'G:\VDCNS\protocolo\pro\suma_waterbin_2007b.TIF')