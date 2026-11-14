# Composants tiers

explorer-draco-step-preview est sous licence Apache-2.0 (voir `LICENSE`). Ce dépôt ne contient aucun code ni binaire tiers : les composants ci-dessous sont installés par `pip` ou téléchargés par `windows/preview/fetch_occt.py`. Qui redistribue un paquet les incluant doit respecter leurs licences.

## Bibliothèques Python (installées par `pip`)

| Composant | Licence déclarée par le paquet |
|---|---|
| DracoPy | Apache-2.0 |
| numpy | BSD-3-Clause et autres licences permissives |
| PySide6 (Qt pour Python) | LGPL-3.0-only, GPL-2.0-only ou GPL-3.0 |

## Lecteur STEP (téléchargé par `windows/preview/fetch_occt.py`)

- Open CASCADE Technology 8.0.1 : LGPL-2.1 avec l'exception Open CASCADE. https://dev.opencascade.org
- DLL dont OpenCascade dépend, paquets conda-forge : FreeImage, FreeType, Imath, libjpeg-turbo, libpng, LibRaw, libtiff, libwebp, zlib, OpenEXR, OpenJPEG, LERC, libdeflate, Zstandard, liblzma, Little CMS, OpenJPH. Chacune garde sa propre licence, fournie dans son paquet conda-forge ; elles n'ont pas été relevées une à une ici.
