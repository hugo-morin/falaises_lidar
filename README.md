# falaises_lidar

Detection de falaises potentielles a partir des modeles numeriques de terrain
LiDAR du Quebec. Le projet part d'un vieux script exploratoire et le transforme
progressivement en pipeline reutilisable pour reperer des parois interessantes
pour l'escalade.

## Ce que fait le pipeline

1. Selectionne les tuiles LiDAR qui intersectent une region administrative ou
   un shapefile custom.
2. Telecharge les MNT disponibles pour ces tuiles.
3. Calcule la pente et l'orientation avec GDAL.
4. Vectorise les zones au-dessus d'un seuil de pente.
5. Filtre les polygones par surface et hauteur.
6. Ajoute l'orientation et la pente moyenne.
7. Fusionne les resultats, coupe sur la zone demandee, retire les carrieres et
   joint les attributs geologiques si la couche est fournie.

Les resultats sont des shapefiles et KML dans `output/<cible>/`.

## Installation

La pile geospatiale Python est plus simple a installer avec conda-forge.
Depuis la racine du depot:

```powershell
conda env create -f environment.yml
conda activate falaises-lidar
```

Pour mettre a jour l'environnement apres une modification de
`environment.yml`:

```powershell
conda env update -f environment.yml --prune
```

`mamba` ou `micromamba` peuvent remplacer `conda` si disponibles.

## Donnees

Le depot contient deja ces donnees auxiliaires dans `associated_data/`:

- `Index_MNT20k.zip`: index des tuiles MNT.
- `regions_admin.zip`: regions administratives.
- `carrieres.zip`: carrieres a exclure avec un buffer.

La couche geologique n'est pas incluse. Telecharger la couche
`Zone geologique.shp` depuis Donnees Quebec, puis passer son chemin avec
`--geology`.

Les MNT LiDAR sont telecharges a la demande depuis le gabarit d'URL configure
dans `PipelineConfig`.

## Utilisation

Traiter une region administrative:

```powershell
python Main.py --region-code 12
```

Traiter plusieurs regions:

```powershell
python Main.py --region-code 12 --region-code 15
```

Traiter une zone custom:

```powershell
python Main.py --shape C:\chemin\vers\clip.shp
```

Conserver les MNT telecharges pour relancer ou inspecter:

```powershell
python Main.py --region-code 12 --keep-mnt
```

Afficher toutes les options:

```powershell
python Main.py --help
```

## Parametres principaux

- `--workspace`: dossier de travail et de sortie, par defaut `output`.
- `--index`: index des tuiles, shapefile ou zip.
- `--regions`: regions administratives, shapefile ou zip.
- `--geology`: couche geologique optionnelle.
- `--quarries`: couche des carrieres, shapefile ou zip.
- `--min-slope`: pente minimale en degres, par defaut `70`.
- `--min-surface`: surface minimale en metres carres, par defaut `100`.
- `--min-height`: hauteur minimale en metres, par defaut `20`.
- `--quarry-distance`: buffer d'exclusion autour des carrieres, par defaut
  `1000`.
- `--keep-mnt`: conserve les MNT apres traitement.

## Structure du code

- `Main.py`: point d'entree compatible avec l'ancien nom de script.
- `cliff_lidar/cli.py`: interface en ligne de commande.
- `cliff_lidar/config.py`: objets de configuration.
- `cliff_lidar/processing.py`: logique geospatiale et raster.

## Verification rapide

Sans lancer le traitement LiDAR complet:

```powershell
python Main.py --help
python -c "from cliff_lidar.processing import normalize_tile_name; print(normalize_tile_name('31H01202'))"
```

Pour la suite, les bons prochains chantiers seraient d'ajouter des tests sur
les fonctions pures, une option de dry-run qui liste les tuiles sans telecharger
les MNT, puis une petite sortie GeoPackage plus robuste que les shapefiles.
