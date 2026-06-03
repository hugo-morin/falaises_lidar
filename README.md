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
6. Ajoute l'orientation, la pente moyenne et un score de priorite.
7. Fusionne les resultats, coupe sur la zone demandee, retire les carrieres et
   joint les attributs geologiques si la couche est fournie.

Les resultats sont des shapefiles, KML et GeoPackage dans `output/<cible>/`.

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

Les donnees auxiliaires doivent etre placees localement dans `associated_data/`.
Ce dossier est ignore par git pour eviter de versionner des archives
geospatiales volumineuses.

Formats de predilection:

- GeoPackage (`.gpkg`) pour les couches vectorielles nouvelles ou volumineuses.
- CSV pour les tables simples comme la liste des URLs LiDAR.
- ZIP de shapefile (`.zip`) seulement quand c'est le format source le plus
  pratique ou deja supporte par le pipeline.

Donnees attendues:

| Fichier local | Source | Format prefere | Utilisation |
| --- | --- | --- | --- |
| `associated_data/Index_MNT20k.zip` | [Donnees lidar du Quebec](https://www.donneesquebec.ca/recherche/dataset/donnees-lidar-du-quebec) | GPKG ou ZIP/SHP | Index des tuiles MNT. |
| `associated_data/URL_Lidar.csv` | [Donnees lidar du Quebec](https://www.donneesquebec.ca/recherche/dataset/donnees-lidar-du-quebec) | CSV | URLs officielles des produits LiDAR par tuile. |
| `associated_data/regions_admin.zip` | [Decoupages administratifs](https://www.donneesquebec.ca/recherche/fr/dataset/decoupages-administratifs) | ZIP/SHP ou GPKG | Regions administratives pour `--region-code`. |
| `associated_data/carrieres.zip` | [Indices, gites, mines et carrieres](https://www.donneesquebec.ca/recherche/dataset/indices-gites-et-gisements) | ZIP/SHP | Carrieres a exclure avec un buffer. |
| `associated_data/Zone geologique.shp` | [Geologie du socle](https://www.donneesquebec.ca/recherche/dataset/geologie-du-socle) | SHP ou GPKG | Jointure geologique optionnelle avec `--geology`. |
| `associated_data/ReseauRoutier_RTSS.gpkg` | [Reseau routier - RTSS](https://www.donneesquebec.ca/recherche/dataset/reseau-routier-rtss) | GPKG | Couche d'acces routier, pour les prochains enrichissements. |
| `associated_data/AQreseau_GPKG.zip` | [Adresses Quebec](https://www.donneesquebec.ca/recherche/dataset/adresses-quebec) | GPKG zippe | Reseau routier complementaire, pour les prochains enrichissements. |
| `associated_data/registre_aires_prot_GPKG.zip` | [Registre des aires protegees et des AMCE au Quebec](https://www.donneesquebec.ca/recherche/fr/dataset/aires-protegees-au-quebec) | GPKG zippe | Contraintes environnementales, pour les prochains enrichissements. |
| `associated_data/quebec-260601-free.shp.zip` | [Geofabrik - Quebec OpenStreetMap](https://download.geofabrik.de/north-america/canada/quebec.html) | ZIP/SHP | Donnees OSM complementaires, pour les prochains enrichissements. |

Les MNT LiDAR sont telecharges a la demande depuis `URL_Lidar.csv` quand il est
present. Si une tuile n'y est pas trouvee, le pipeline utilise le gabarit d'URL
configure dans `PipelineConfig`.

## Utilisation

Traiter une region administrative:

```powershell
python Main.py --region-code 12
```

Traiter plusieurs regions:

```powershell
python Main.py --region-code 12 --region-code 15
```

Traiter une tuile LiDAR precise:

```powershell
python Main.py --tile 31J01SE
```

Traiter une zone custom:

```powershell
python Main.py --shape C:\chemin\vers\clip.shp
```

Conserver les MNT telecharges pour relancer ou inspecter:

```powershell
python Main.py --region-code 12 --keep-mnt
```

Lister les tuiles d'une cible sans telecharger ni traiter de rasters:

```powershell
python Main.py --region-code 12 --dry-run
```

Tester seulement les premieres tuiles d'une region avant un traitement complet:

```powershell
python Main.py --region-code 14 --max-tiles 2
```

Afficher toutes les options:

```powershell
python Main.py --help
```

## Parametres principaux

- `--workspace`: dossier de travail et de sortie, par defaut `output`.
- `--index`: index des tuiles, shapefile ou zip.
- `--regions`: regions administratives, shapefile ou zip.
- `--lidar-urls`: CSV des URLs LiDAR par tuile, par defaut
  `associated_data/URL_Lidar.csv`.
- `--geology`: couche geologique optionnelle.
- `--quarries`: couche des carrieres, shapefile ou zip.
- `--min-slope`: pente minimale en degres, par defaut `70`.
- `--min-surface`: surface minimale en metres carres, par defaut `100`.
- `--min-height`: hauteur minimale en metres, par defaut `15`.
- `--score-slope-weight`: poids donne a la pente moyenne dans le score de
  priorite, par defaut `0.7`.
- `--score-height-cap`: hauteur ou la portion hauteur du score atteint son
  maximum, par defaut `50`.
- `--quarry-distance`: buffer d'exclusion autour des carrieres, par defaut
  `1000`.
- `--dry-run`: liste les tuiles selectionnees et la couverture du CSV d'URLs.
- `--max-tiles`: limite le traitement aux N premieres tuiles selectionnees,
  utile pour un test de fumee.
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
pytest
```

Pour la suite, les bons prochains chantiers seraient d'ajouter des tests sur
les integrations de couches d'acces et d'aires protegees, puis une sortie de
rapport qui trie les falaises par score dans chaque region.
