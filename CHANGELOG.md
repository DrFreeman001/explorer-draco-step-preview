# Journal des versions

## 0.2.1 — novembre 2026

- L'installateur signale « 3D Viewer » de Microsoft s'il est installé (il garde le volet d'aperçu des STL, OBJ et 3MF) et propose d'ouvrir « Applications installées » pour le retirer.
- README : cette consigne est remontée dans la section Installation.

## 0.2.0 — novembre 2026

- Nouveaux formats : PLY, glTF (GLB, et GLTF à données intégrées ; compression Draco comprise), AMF (ZIP compris).
- Couleurs des projets Bambu Studio, OrcaSlicer et PrusaSlicer : filament de chaque objet et pièce, peinture multicolore.
- Dimensions en millimètres et nombre de triangles en bas du volet d'aperçu.
- Textes en français ou en anglais selon la langue de Windows.
- Clic droit sur un dossier : « Refaire les miniatures 3D », sans toucher aux fichiers.

## 0.1.0 — novembre 2026

Première version publiée séparément de dracoconv.

- Miniatures et aperçu 3D des `.drc`, `.step`, `.stp`, `.stl`, `.obj` et `.3mf` dans l'Explorateur Windows.
- STEP : couleurs des pièces et des faces, vitrages translucides, assemblages jusqu'à 200 Mo, cache court du maillage.
- Isolation : processus séparé à faible intégrité, limites de mémoire et de temps, nettoyage des dossiers temporaires après plantage.
- Installateur Windows autonome (Python embarqué, OpenCascade inclus), par utilisateur ; retrait réversible.
