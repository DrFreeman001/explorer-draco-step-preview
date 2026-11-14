# Prototype Windows Draco — vérification

État au 12 novembre 2026 : faisabilité démontrée sur cube synthétique, pas une extension prête à distribuer. Installation d’essai retirée : register.py status confirme « not installed ». Aucun auxiliaire shell_preview.py ni fichier temporaire résiduel constaté après désélection.

## Résultats observés
- DLL x64 compilée avec MSVC 14.51 et SDK 10.0.26100.0.
- COM direct : Initialize S_OK, seconde initialisation 800704df, miniature HBITMAP S_OK, DllCanUnloadNow S_OK.
- Cache Windows réel : IThumbnailCache::GetThumbnail avec WTS_FORCEEXTRACTION retourne S_OK sur cube.drc.
- Explorer réel : cube affiché dans son volet latéral ; glisser fait tourner, molette change le zoom, R restaure l’orientation et le zoom après focus souris.
- Redimensionnement du volet réussi après correction dimensions Win32 physiques / Qt logiques (écran à 150 %).
- Isolation vérifiée par OpenProcessToken/GetTokenInformation : prevhost PID80064 et Python PID80344,42568 ont tous le RID 0x1000 (Low). Aucun DisableLowILProcessIsolation/DisableProcessIsolation ajouté.
- Plusieurs sélections/désélections : disparition des processus auxiliaires et nettoyage du répertoire temporaire constatés.
- Régression panne : test_failure.py constate le défaut avant correction (Chargement persiste), puis succès après correction (Apercu indisponible), Unload S_OK.
- Régression démarrage bloqué : auxiliaire dormant60s, message d’indisponibilité après20s, Unload S_OK.
- Six tests Python ciblés passent : image réelle, géométrie/projection, invalides/nuages de points, registre/restauration, conflit ProgID par défaut et UserChoice.

## Dernière vérification et réserve clavier
Le 12 novembre à 19:38, le cube est de nouveau affiché dans le véritable volet Explorer avec la DLL corrigée (surveillance auxiliaire, focus enfant, dimensions à 150 %). Après clic dans le modèle, Tab et Shift+Tab ont été envoyés. Le fournisseur d’accessibilité conserve cependant le champ Address Bar comme focus et aucun indicateur visuel ne permet de confirmer la sortie et le retour du focus : parcours clavier non validé, correction à considérer provisoire. Le reset R était vérifié après focus souris lors du passage précédent, pas après parcours clavier. Ce point reste bloquant avant distribution.

La suite complète du dépôt exécutée par l’agent principal a terminé avec 325 tests réussis ; journal local (non publié) `.superpowers/validation-2026-11-11/pytest-prototype-final.log`. Aucun changement de code après ce résultat. Retour à Home dans Explorer, retrait avec register.py uninstall, puis status : not installed. Aucun processus Python de ce prototype ni résidu dans LocalLow/DracoConvPreview au contrôle final.

## Limites du prototype
Entrée comprimée plafonnée à32MiB ; le Bouddha validé de43,55MB est donc exclu. Budget du job complet1536MiB ;768MiB provoquait un arrêt0xc0000409 pendant le démarrage Python/Qt. Un seul aperçu et une seule miniature à la fois (deux jobs au maximum). Au-delà de12000 triangles, échantillonnage de faces pour affichage uniquement, annoncé « Affichage simplifié » ; ce n’est pas une décimation et peut rendre un modèle poreux. Géométrie seulement, sans textures ni couleurs ; nuages de points refusés. Aucun grand modèle fourni n’a été validé ici. Pas de modification des sources ni de changement de programme par défaut.

## 13 novembre 2026 — clavier abandonné, rendu complet intégré

**Clavier (décision de l'utilisateur : non bloquant, on s'arrête là).** Essai manuel dans le vrai Explorer, sur un `.drc` réel lu seulement. R réinitialise la vue après un clic dans le modèle. Tab et Maj+Tab ne fonctionnent dans aucun sens :
- entrée : Explorer s'arrête sur sa propre fenêtre « Shell Preview Extension Host » puis appelle `IPreviewHandler::SetFocus` ; `SetFocus` vers la fenêtre Qt échoue avec l'erreur 5 (accès refusé) ;
- sortie : la fenêtre Qt reçoit R mais jamais Tab, donc `focusNextPrevChild` n'est jamais appelé.
Le code de diagnostic a été retiré ; le pont et l'auxiliaire sont revenus à leur version du 12 novembre pour cette partie. Limite connue : l'aperçu se manipule à la souris, et R après un clic.

**Piège : ne jamais arrêter `prevhost.exe` de force.** Explorer garde alors la fenêtre hôte du processus mort et la repasse à chaque `SetWindow` (`IsWindow` = 0, rectangle 0 × 0, `CreateWindowEx` en erreur 1400). L'aperçu reste vide dans ce processus Explorer jusqu'à son redémarrage. Constaté deux fois, dans deux processus Explorer distincts. Pour recharger la DLL après recompilation : renommer la DLL chargée, recompiler, puis redémarrer Explorer.

**Rendu complet.** L'auxiliaire dessine toutes les faces par OpenGL (`explorer_preview/preview_rendering.py`), pour l'aperçu comme pour la miniature. Le dessin échantillonné ne sert plus que de secours quand OpenGL manque, et l'affiche (« Affichage simplifié »). Vue Z en haut, comme les trancheurs, légèrement par-dessus. Limite d'entrée portée à 64 Mio dans le pont et l'auxiliaire. Miniatures 512 px produites par l'auxiliaire, en processus normal, pour Genius (334 858 faces) et le Bouddha (2 909 880 faces, 43,5 Mo) : surfaces pleines, sources inchangées (SHA-256). Les deux modèles apparaissent debout (correction : une note précédente annonçait le Bouddha couché, à tort).

**Validation dans le vrai Explorer (faible intégrité), 13 novembre au soir.** Après redémarrage d'Explorer, DLL compilée à 17 h 13 (limite 64 Mio) chargée.
- Aperçu Genius (334 858 faces) : toutes les faces, debout, sans mention « Affichage simplifié ».
- Aperçu Bouddha (2 909 880 faces, 43,5 Mo) : prêt en 1,9 s, toutes les faces, debout. Mémoire de l'auxiliaire : 893 Mo privés, 230 Mo de pointe en mémoire vive, sous la limite de 1 536 Mio de l'objet job.
- Miniatures neuves (copies des deux modèles dans un dossier d'essai, donc hors cache) : surfaces pleines et debout. Copies supprimées ensuite.
- SHA-256 des deux sources inchangés.
- Les dossiers temporaires des aperçus fermés normalement ont été supprimés par l'extension.

**Hôte d'aperçu resté bloqué.** Redémarrer Explorer ne suffit pas quand un ancien `prevhost.exe` survit avec une ancienne DLL : Explorer le réutilise (fenêtre 0 × 0, verrou d'aperçu occupé). Procédure sûre : arrêter Explorer, puis seulement alors arrêter les `prevhost.exe`, puis relancer Explorer. Arrêter `prevhost` pendant qu'Explorer tourne reste à proscrire.

**Un seul aperçu vivant à la fois (voulu).** Un verrou global limite l'aperçu à une instance. Si deux fenêtres Explorer affichent le volet d'aperçu, la seconde reste vide tant que la première montre un `.drc`. Limite connue, non corrigée.

**Reste ouvert.** Après un arrêt brutal de l'hôte, les dossiers temporaires (avec la copie du modèle, jusqu'à 64 Mio) restent dans `LocalLow\DracoConvPreview`. Le nettoyage natif de ces dossiers abandonnés n'est pas fait. Ceux de nos essais ont été supprimés à la main.

## 13 novembre 2026 — aperçu et miniatures STEP

Collection : 69 fichiers STEP, 122 Mo, le plus gros 33 Mo. Sources lues seulement ; SHA-256 des trois fichiers d'essai inchangés.

**Choix du lecteur.** Mesuré sur « The 100 v11-beta1-5.step » (33 Mo, 466 253 triangles) :
- OCP (OpenCascade pour Python) : 10 s, mais 864 Mo réservés dès l'import, 1 373 Mo au pic ; 555 Mo installés avec VTK, obligatoire à l'import.
- gmsh : pas fini en 2 minutes.
- `step_mesh.exe`, natif, OpenCascade 8.0.1 de conda-forge : 9 s, 526 Mo au pic. Retenu.

**Explorer réel, faible intégrité.**
- The 100 : aperçu complet en 10,6 s ; pic 454 Mo pour `step_mesh`, 828 Mo pour l'auxiliaire, 1 231 Mo cumulés, sous la limite de 1 536 Mio.
- Bloc d'essai `tests/data/tall_block.step` : debout, trou sur le dessus.
- Miniatures neuves (copies hors cache) de la bobine PETmachine, de la carte BTT EBB42 et de The 100 : complètes. Type affiché « Orca.Slicer.1 » : programme par défaut inchangé.
- Dossier temporaire supprimé à la fermeture, `model.mesh` compris.
- Une seconde fenêtre affiche désormais « Un autre apercu 3D est deja ouvert dans une autre fenetre. » au lieu d'un volet vide.

**Piège : clé `.step` réécrite.** Inscrits d'abord sous `HKCU\Software\Classes\.step\shellex`, les gestionnaires disparaissaient (pour `.step` et `.stp`) dès qu'Explorer affichait un fichier STEP ; la valeur par défaut « Orca.Slicer.1 » restait. Sous `SystemFileAssociations\.step` et `.stp`, ils tiennent. L'auteur de l'effacement n'est pas identifié (pas d'outil de traçage sans élévation).

**Reste ouvert.** Les couleurs de pièces ne sont pas lues. Un STEP proche de 64 Mo pourrait dépasser 16 s ou la limite mémoire : l'aperçu afficherait alors une erreur, sans risque pour le fichier.

## 14 novembre 2026 — couleurs STEP

`step_mesh.exe` lit maintenant les couleurs (STEPCAFControl, styles XCAF : la couleur d'une face l'emporte sur celle de son solide) et les écrit par sommet (format `DCMESH2`). Le rendu OpenGL les dessine.

Mesuré hors Explorer, sources lues seulement (SHA-256 inchangés) :
- The 100 (33 Mo) : `step_mesh` 8,8 s, 535 Mio réservés au pic (526 avant) ; miniature complète 9,1 s, auxiliaire 848 Mio (828 avant).
- Carte BTT EBB42 (29 Mo) : 6,0 s, 372 Mio ; miniature 6,3 s.
- Images contrôlées à l'œil : châssis gris et carte électronique de The 100, carte EBB42 noire avec bornier vert et entretoises dorées, engrenage PETmachine blanc.

**Non refait :** l'essai dans le vrai Explorer en faible intégrité. La DLL n'a pas changé ; l'auxiliaire et `step_mesh.exe` sont relus à chaque aperçu. Les miniatures déjà en cache restent bleues jusqu'à leur renouvellement.

## 14 novembre 2026 — gros fichiers STEP : où part le temps

Essai avec un `step_mesh.exe` instrumenté (retiré ensuite), sources lues seulement :

| Fichier | Lecture | Conversion STEP → formes | Maillage | Triangles |
|---|---|---|---|---|
| The 100 (33 Mo), flèche 0,1 % | 1,0 s | 6,0 s | 1,6 s | 466 253 |
| The 100, flèche 1 % | 1,0 s | 6,2 s | 1,6 s | 367 535 |
| Carte EBB42 (29 Mo), flèche 0,1 % | 0,8 s | 3,5 s | 1,5 s | 545 680 |
| Carte EBB42, flèche 1 % | 0,8 s | 3,5 s | 1,5 s | 270 078 |

- Un maillage dix fois plus grossier ne gagne aucun temps : la conversion domine et ne dépend pas de la finesse. Idée abandonnée.
- Couper la réparation des formes d'OpenCascade (`SetShapeProcessFlags` vide) ne change rien non plus : 6,1 s et 3,5 s, mêmes triangles.
- Le seul levier restant est le délai : 16 s côté Python, 20 s dans `bridge.cpp`. Un fichier deux fois plus gros que The 100 demanderait environ 18 s de lecteur et dépasserait. Non modifié : il faut recompiler la DLL et redémarrer Explorer. Aucun fichier de la collection ne dépasse 33 Mo.

## 14 novembre 2026 — délai porté à 45 s

À la demande de l'utilisateur : 45 s dans `bridge.cpp` (miniature et chargement initial de l'aperçu), 40 s pour `step_mesh.exe`. DLL recompilée Explorer arrêté, puis Explorer relancé.

- `probe.exe` : miniature et déchargement réussis. `cache_probe.exe` sur une copie neuve de `tests/data/colored_block.step` : miniature fournie par le cache de Windows (HRESULT 0), donc par la nouvelle DLL.
- Suite complète réussie.
- **Non vérifié :** un fichier STEP assez gros pour dépasser l'ancien délai (aucun dans la collection) ; le volet d'aperçu à l'œil après ce changement ; `test_failure.py` (à ne pas lancer tant que l'extension est installée). La limite mémoire de 1 536 Mio n'a pas bougé et peut devenir la première atteinte.

**Contrôle à l'écran, même jour.** Carte BTT EBB42 (29 Mo) sélectionnée dans le vrai Explorer, volet d'aperçu ouvert : modèle complet et en couleurs (carte noire, bornier vert, entretoises jaunes, connecteurs blancs) avec la nouvelle DLL. Rotation à la souris non rejouée.

## 14 novembre 2026 — essai sur un très gros STEP (Rat Rig V-Core 4.1 500 IDEX)

Fichier exporté d'Autodesk Fusion par l'utilisateur : 142 Mo, 790 solides, 50 638 faces. Source lue seulement, SHA-256 inchangé.

- **Aperçu normal :** refusé aussitôt (limite d'entrée de 64 Mio), sans lecture.
- **Lecteur seul, hors limites :** réussi en 46,7 s, 1 634 Mio réservés au pic ; 3 292 965 sommets, 3 435 920 triangles, maillage de 86 Mio.
- **Dessin :** 0,3 s pour la première image, 0,015 s pour la suivante ; auxiliaire à 1 084 Mio au pic.
- **Image :** modèle complet et en couleurs, mais les panneaux du caisson, transparents dans la CAO, sont dessinés opaques et cachent l'intérieur. La transparence n'est pas lue.

Il dépasse donc les trois limites actuelles : 64 Mio d'entrée, 40 s de lecteur, 1 536 Mio de job (le lecteur seul en demande 1 634). Limites non modifiées.

## 14 novembre 2026 — limites relevées pour les gros assemblages STEP

À la demande de l'utilisateur : 200 Mio d'entrée pour un STEP (64 Mio inchangé pour un Draco), 90 s dans `bridge.cpp`, 80 s pour `step_mesh.exe`, 3 072 Mio par job. DLL recompilée Explorer arrêté, puis Explorer relancé.

Essai dans le vrai Explorer sur le Rat Rig V-Core 4.1 500 IDEX (142 Mo), source inchangée (SHA-256 identique) :
- miniature produite et affichée ;
- volet d'aperçu : modèle complet affiché après environ une minute de « Chargement... » ;
- relevés pendant l'essai : auxiliaire d'aperçu 944 Mio réservés, lecteur 963 Mio de mémoire vive au pic ; 3 930 Mio réservés au pic, aperçu et miniature cumulés (deux jobs distincts).

**Constaté :** Explorer relance la lecture pour la miniature pendant que l'aperçu est ouvert ; chaque lecture coûte environ 50 s de processeur. Les panneaux du caisson restent opaques (transparence non lue). **Non mesuré :** la marge exacte sous 3 072 Mio dans un seul job, et un fichier proche de 200 Mio.

## 14 novembre 2026 — transparence des vitrages STEP

Constat : le Rat Rig exporté par Fusion ne contient aucune transparence (`SURFACE_STYLE_TRANSPARENT` : 0 occurrence), et aucun STEP de la collection non plus. Fusion écrit en revanche le nom de la matière dans la couleur : `COLOUR_RGB('Polycarbonate (Tinted Black)', ...)`.

Fait : `step_mesh.exe` lit l'opacité standard quand elle existe et, à défaut, rend translucide (opacité 80/255) toute couleur dont le nom contient polycarbonate, acrylic, glass, transparent, translucent, plexi, pmma, clear ou tinted. Format `DCMESH3` (couleur et opacité par sommet). Le rendu dessine les faces opaques, puis les translucides avec mélange et sans écrire la profondeur.

- Rat Rig (142 Mo), hors Explorer : lecteur 50,8 s, 1 616 Mio réservés ; dessin 0,3 s ; la machine est visible à travers les panneaux.
- Vrai Explorer, volet d'aperçu : même image, machine visible à travers le caisson.
- **Limites :** deux pièces opaques de la même couleur exacte qu'un vitrage deviendraient translucides aussi. Les faces translucides ne sont pas triées entre elles. La miniature déjà en cache reste opaque jusqu'à son renouvellement. L'opacité standard du format n'a été vérifiée sur aucun fichier réel, faute d'exemple.

## 14 novembre 2026 — nettoyage après plantage, build portable, rangement

- **Mise en forme :** `bridge.cpp`, `step_mesh.cpp` et les sondes passés à clang-format (`.clang-format`). Contrôle : texte identique une fois les espaces retirés. `bridge.cpp` passe de 135 à 489 lignes, plus aucune au-delà de 120 caractères.
- **Nettoyage après plantage :** la DLL crée et tient `lease.v1` dans son dossier temporaire ; l'auxiliaire ramasse au démarrage les dossiers dont le bail est libre. Testé côté Python (`tests/test_preview_temp.py`) : dossier mort supprimé, dossier vivant, ancien dossier sans bail et dossier contenant un fichier inconnu laissés en place.
- **Build :** `build.ps1` trouve Visual Studio par `vswhere` et le SDK par le registre, au lieu de chemins fixes. `-CheckOnly` compile `bridge.cpp` sans toucher à la DLL installée. Sondes déplacées dans `probes/`.
- **Registre :** libellés « DracoConv 3D thumbnail / preview » au lieu de « prototype » ; extension désinscrite puis réinscrite.
- **Anciens dossiers temporaires :** cinq dossiers sans bail supprimés à la main. Erreur de manipulation à noter : le premier passage a aussi vidé le dossier d'un aperçu encore ouvert (copies temporaires seulement, aucun fichier de l'utilisateur) ; il sera retiré à la fermeture de cet aperçu.

**Non fait à cette date :** la DLL installée est encore l'ancienne. La nouvelle (avec le bail) compile, mais n'est ni installée ni essayée dans Explorer : il faut arrêter Explorer pour la remplacer. Le ramassage n'a donc pas été vu à l'œuvre après un vrai plantage.

**Suite, même jour : nouvelle DLL installée.** Explorer arrêté, DLL recompilée, Explorer relancé.
- `probe.exe` : miniature et déchargement réussis ; `cache_probe.exe` sur un STEP neuf : miniature fournie par Windows (HRESULT 0).
- Plantage simulé : `preview_probe.exe` (qui héberge la DLL) tué pendant un aperçu ouvert. Le dossier reste, avec `events.log`, `input.drc`, `lease.v1` et `ready` ; l'auxiliaire est bien arrêté par le job. Au lancement suivant (`probe.exe`), le dossier abandonné a disparu : 0 dossier restant.
- Non refait : le contrôle à l'œil du volet d'aperçu après ce changement, et un plantage de `prevhost.exe` lui-même (interdit tant qu'Explorer tourne).

## 14 novembre 2026 — cache court du maillage STEP

Explorer demande la miniature et l'aperçu séparément : le Rat Rig (142 Mo) était lu deux fois, environ 50 s et 1,6 Gio chaque fois. Le maillage d'une lecture de plus de 5 s est maintenant gardé une heure au plus (deux entrées au maximum), sous l'empreinte SHA-256 du contenu.

- Mesuré avec l'auxiliaire, dans un dossier d'essai : première miniature par lecture complète, la suivante en 0,9 s, images identiques octet pour octet ; un maillage de 94 Mio en cache.
- Un cache corrompu est rejeté et supprimé (testé). Les lectures rapides ne sont pas mises en cache (testé).
- **À savoir :** ce cache laisse, pendant une heure au plus, une copie de la géométrie dans le profil de l'utilisateur, alors qu'auparavant tout disparaissait à la fermeture. Il est purgé au lancement suivant d'un aperçu STEP, pas par une horloge. Non vérifié dans le vrai Explorer, ni quand miniature et aperçu démarrent en même temps (les deux lisent alors le fichier).

## 14 novembre 2026 — dépôt séparé

La visionneuse quitte le dépôt dracoconv pour celui-ci (paquet Python `explorer_preview`). Les mesures ci-dessus ont été faites avant le déménagement, avec les mêmes sources.

- Environnement neuf (`requirements-tested.txt`), OpenCascade déplacé, extension recompilée sur place : suite de tests réussie, `probe.exe` réussi.
- Ancienne inscription retirée, nouvelle posée. **Piège rencontré :** le retrait de l'ancienne a remis des valeurs d'une inscription plus ancienne encore (libellés « prototype », chemin de l'ancien dossier) que son manifeste avait gardées comme valeurs antérieures. Ces restes ont été retirés un par un, seulement s'ils étaient reconnaissables comme les nôtres ; l'inscription neuve a tenu une minute sous surveillance.
- Après redémarrage d'Explorer : miniature d'un STEP neuf fournie par Windows, et le volet d'aperçu de la carte EBB42 s'affiche en couleurs ; `prevhost.exe` charge la DLL du nouveau dossier.
