# Notes techniques de l’extension

Deux classes COM x64 : miniatures et aperçu 3D isolés, pour `.drc`, `.step` et `.stp`. Installation courante : voir le [README](../../README.md) à la racine. Ce qui suit détaille la construction, les sondes de contrôle et les choix techniques ; [verification.md](verification.md) garde les mesures.

Construction et contrôle complets, depuis la racine du dépôt, PowerShell :

```powershell
.venv/Scripts/python.exe windows/preview/configure.py
python -I windows/preview/fetch_occt.py   # une fois : OpenCascade pour STEP, dans third_party
./windows/preview/build.ps1                # trouve seul Visual Studio (vswhere) et le SDK Windows
.venv/Scripts/python.exe -m pytest
./windows/preview/build/probe.exe
.venv/Scripts/python.exe windows/preview/probes/test_failure.py
.venv/Scripts/python.exe windows/preview/register.py install
./windows/preview/build/cache_probe.exe (Join-Path $PWD 'windows\preview\cube.drc')
```

Dans Explorer, sélectionner `windows/preview/cube.drc`, ouvrir le volet avec Alt+P. Glisser pour tourner, molette pour zoomer, R pour réinitialiser. L’installation est par utilisateur, uniquement les gestionnaires `.drc`, `.step` et `.stp`. Pour STEP, ils sont inscrits sous `SystemFileAssociations` : la clé `.step` de l’utilisateur appartient au trancheur associé, qui la réécrit et y efface les sous-clés `shellex` (constaté le 13 novembre 2026). Elle refuse les gestionnaires étrangers trouvés directement ou par ProgID associé, y compris UserChoice ; le programme d’ouverture par défaut reste intact.

Retrait :

```powershell
.venv/Scripts/python.exe windows/preview/register.py uninstall
.venv/Scripts/python.exe windows/preview/register.py status
```

Conserver `build/registration.json` tant que l’installation est active : ce manifeste permet le retour exact des valeurs antérieures. Le retrait laisse intactes les valeurs modifiées entre-temps par une autre application. Les chemins Python/source sont propres à cette copie du dépôt dans `build/preview.ini` ; garder les fichiers en place pendant l’essai. Ne pas exécuter test_failure.py pendant une installation active : il remplace temporairement ce fichier de configuration pour simuler un auxiliaire défaillant.

Limites : 64 Mio pour un Draco, 200 Mio pour un STEP, 3072 Mio par job, 90 s pour une miniature ou le chargement initial. Toutes les faces sont dessinées par OpenGL ; sans OpenGL, un dessin échantillonné de 12 000 faces prend le relais et l’annonce. Le clavier ne fonctionne qu’après un clic dans le modèle (R pour réinitialiser) : Tab et Maj+Tab n’entrent pas dans l’aperçu et n’en sortent pas. Ne jamais arrêter `prevhost.exe` de force pendant qu’Explorer tourne : l’aperçu resterait vide jusqu’au redémarrage d’Explorer. Pour recharger la DLL : arrêter Explorer, puis les `prevhost.exe`, puis relancer Explorer. Le lancement Python dans le venv utilise un petit processus relais ; les descendants restent dans le job tué à la fermeture. L’aperçu et les miniatures ont chacun une limite de concurrence de1. Aucun réglage d’isolation Windows n’est modifié.

STEP : le format est reconnu au contenu (`ISO-10303-21`), pas au nom. L’auxiliaire lance `build/step/step_mesh.exe`, programme natif lié à OpenCascade 8.0.1, dans le même job : il lit le fichier, le découpe en triangles (flèche 0,1 % de la plus grande dimension) et écrit `model.mesh` (positions, triangles, couleur et opacité par sommet) dans le dossier temporaire, supprimé après lecture. Il a 80 s. Quand cette lecture dure plus de 5 s, le maillage est gardé une heure au plus dans `LocalLow/DracoConvPreview/mesh-cache` (deux fichiers au maximum, nommés par l’empreinte SHA-256 du contenu), pour que la miniature et l’aperçu d’un même gros fichier ne le lisent pas deux fois. `stage_step.py` copie à côté de lui les 45 DLL nécessaires (46 Mo, dont FreeImage et FreeType qu’OpenCascade charge sans s’en servir ici) ; le runtime Visual C++ reste celui de Windows. Le paquet OpenCascade de conda-forge est choisi plutôt que la bibliothèque Python OCP : importer OCP réserve à lui seul 860 Mo, ce qui dépasse la limite du job une fois le rendu ajouté. Les couleurs des pièces et des faces du fichier sont lues (lecteur XCAF) et dessinées ; une face sans couleur garde le bleu par défaut. La transparence est lue aussi ; quand le fichier n’en donne pas (export Fusion), une couleur dont le nom désigne un vitrage (« Polycarbonate », « Glass », « Acrylic », « Clear », « Tinted »...) est dessinée translucide. Les faces translucides sont dessinées après les autres, sans tri entre elles. Le dessin de secours sans OpenGL reste d’une seule couleur. `build.ps1 -StepOnly` recompile ce lecteur seul, sans toucher à la DLL verrouillée par Explorer.

`probes/inspect_integrity.py PID...` relève les niveaux d’intégrité sans modifier les processus. Les entrées temporaires sont privées au profil utilisateur sous LocalLow/DracoConvPreview et supprimées au déchargement normal. Une interruption brutale de l’hôte peut laisser un dossier temporaire : la DLL tient un bail exclusif (`lease.v1`) dans chaque dossier, et l’auxiliaire suivant supprime les dossiers dont le bail est libre (`collect_stale` dans `explorer_preview/preview_temp.py`), fichier par fichier et par nom connu seulement.

État au 13 novembre 2026 : extension validée dans Explorer pour `.drc`, `.step` et `.stp` (voir [verification.md](verification.md)). Elle reste un prototype : les chemins de `build/preview.ini` sont propres à cette copie du dépôt, il n’y a pas d’installateur, et le parcours Tab/Maj+Tab ne fonctionne pas.
