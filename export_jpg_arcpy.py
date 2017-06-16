import arcpy, os

mxd = arcpy.mapping.MapDocument("CURRENT")
df = arcpy.mapping.ListDataFrames(mxd)[0]
rasters = arcpy.mapping.ListLayers(mxd, "*.rst", df)

#Partimos de la base de que estan todos los rasters desactivados y con el zoom y el extent que queremos exportar

for layer in rasters:
  
    #Seleccionamos la ruta de salida, si fijamos el env podria quedarse solo con el nombre
  	out = os.path.join(r'C:\Path\of\the\file', str(layer)[:-4] + '.jpg') 
	layer.visible = True

	arcpy.RefreshTOC()
	arcpy.RefreshActiveView()

	arcpy.mapping.ExportToJPEG(mxd, out, df, df_export_width=1600, df_export_height=1200, world_file=True)

	layer.visible = False

	arcpy.RefreshTOC()
	arcpy.RefreshActiveView()
	