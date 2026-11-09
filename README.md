# photo-card-import

**Je branche la carte de mon appareil photo, et sans aucune manipulation les photos arrivent sur le Mac, rangées par jour de prise de vue et par appareil. Chaque copie est vérifiée à l'octet, puis la carte est vidée et éjectée : il n'y a plus qu'à la retirer.**

```
Import cartes/
  2026-10-29_D750/
  2026-11-09_D750/
  2026-11-09_RicohGR/
```

Un petit outil pour Mac : un script Python, et une icône dans la barre des menus grâce à [SwiftBar](https://github.com/swiftbar/SwiftBar). Il marche avec tout ce qui apparaît comme un disque avec un dossier `DCIM` : une carte SD dans le lecteur, ou un appareil branché en USB qui se monte comme un disque.

## Ce qu'il fait

- **Il détecte la carte tout seul.** Toutes les 10 secondes, l'icône regarde si un disque avec un `DCIM` vient d'arriver, et lance l'import. Pendant la copie, elle affiche la progression (`37/71`), puis une notification dit ce qui est arrivé et où.
- **Un dossier par jour et par appareil.** Le jour est celui de la prise de vue (l'horloge de l'appareil, lue dans les métadonnées EXIF). L'appareil est lu dans l'EXIF aussi, jamais dans le nom de la carte : une carte qui passe d'un boîtier à l'autre ne mélange rien. Vous choisissez le nom court de chaque appareil (`D750`, `RicohGR`…).
- **Une copie vérifiée.** Le fichier lu sur la carte et sa copie relue depuis le disque sont comparés à l'octet près (empreinte BLAKE2). Une copie différente est une erreur, et le fichier est recopié au passage suivant.
- **Jamais deux fois le même fichier.** Un journal garde la trace de tout ce qui a été importé. Une carte rebranchée sans avoir été vidée ne redonne que les nouvelles photos, même si vous avez déplacé ou trié les dossiers entre-temps. La même photo enregistrée sur les deux cartes d'un boîtier à double emplacement n'est copiée qu'une fois.
- **Rien n'est jamais écrasé.** Deux photos différentes qui portent le même nom (le compteur de l'appareil est repassé par zéro) donnent `DSC_0001.JPG` et `DSC_0001_2.JPG`.
- **Pratique avec un dossier synchronisé dans le cloud.** La copie se fait d'abord dans un dossier caché du même disque, puis tout est rangé d'un coup. Le service de synchro ne voit les fichiers qu'à la fin et ne ralentit pas le transfert.
- **La carte vidée, en option.** Avec `"vider_la_carte": true`, un fichier n'est effacé de la carte que si sa copie identique est dans le dossier de destination **à ce moment-là**. Copie absente (dossier vidé depuis) ou différente : le fichier reste sur la carte. Rien n'est effacé si l'import a été interrompu. Seuls les fichiers photo et vidéo sont effacés, jamais les dossiers ni les fichiers propres à l'appareil. Option désactivée par défaut : chez moi elle est activée.
- **La carte éjectée** quand tout s'est bien passé. Sinon elle reste branchée, pour qu'on voie le problème dans le menu.
- **Il vérifie la place** avant de copier (2 Go de marge) et ne fait qu'un import à la fois : une deuxième carte attend son tour.

## Installation

Il faut un Mac avec :
- [SwiftBar](https://github.com/swiftbar/SwiftBar) (gratuit) ;
- `python3` (il vient avec les outils en ligne de commande d'Apple : `xcode-select --install`) ;
- `exiftool` : `brew install exiftool` avec [Homebrew](https://brew.sh).

Puis, dans le Terminal :

```bash
git clone https://github.com/ThomasHMD/photo-card-import.git
cd photo-card-import
cp appareils.exemple.json appareils.json      # vos réglages, à adapter
ln -s "$PWD/import-cartes.10s.sh" "$(defaults read com.ameba.SwiftBar PluginDirectory)/import-cartes.10s.sh"
```

L'icône d'appareil photo apparaît dans la barre des menus. Sans `appareils.json`, l'outil prend les réglages de l'exemple : les photos vont dans `~/Pictures/Import cartes` et la carte n'est pas vidée.

Avant le premier vrai import, vous pouvez voir ce qui serait copié sans rien toucher :

```bash
python3 -I import-cartes.py importer --simulation
```

## Réglages (`appareils.json`)

| Réglage | Rôle |
|---|---|
| `destination` | Le dossier où arrivent les photos : chemin absolu, en `~`, ou relatif au fichier de réglages. |
| `vider_la_carte` | `true` : chaque fichier est effacé de la carte une fois sa copie identique vérifiée. |
| `ejecter_apres_import` | `true` : la carte est éjectée quand tout s'est bien passé. |
| `notifications` | `false` pour couper les notifications. |
| `appareils` | Le nom court de chaque appareil. La première règle dont la marque **et** le modèle EXIF contiennent les textes donnés l'emporte (`""` = n'importe lequel). Appareil inconnu : son modèle EXIF, sans les espaces. |
| `volumes_ignores` | Les disques à ne jamais regarder. |
| `extensions_photo`, `extensions_video` | Les fichiers copiés. |
| `depot` *(facultatif)* | Le dossier intermédiaire, relatif à la racine du disque de la destination (`.import-cartes-depot` par défaut). Si la destination est sur le disque du Mac : `~/.import-cartes-depot`. |
| `journal` *(facultatif)* | La liste de ce qui a déjà été importé (`journal/importes.tsv` par défaut). Placée dans un dossier synchronisé, elle est commune à plusieurs Mac. |

## Utilisation

Rien à faire : branchez la carte. Le menu de l'icône propose aussi :
- **Cartes branchées** : pour chaque carte, *Importer maintenant* et *Éjecter* ;
- **Dernier import** : le nombre de fichiers, le volume copié, un lien vers chaque dossier créé, les erreurs éventuelles ;
- **Tout importer maintenant**, si rien n'est parti tout seul ;
- **Ouvrir** le dossier de destination, et le **Journal**.

En ligne de commande :

```bash
python3 -I import-cartes.py importer                   # toutes les cartes branchées
python3 -I import-cartes.py importer "/Volumes/NO NAME"
python3 -I import-cartes.py importer --simulation      # ce qui serait copié, sans rien toucher
python3 -I import-cartes.py etat
```

L'état de chaque Mac (progression, dernier import) est dans `~/Library/Application Support/import-cartes/`, le journal texte dans `~/Library/Logs/import-cartes/import-cartes.log`.

## Limites

- Un appareil branché **par câble** qui ne se monte pas comme un disque (beaucoup de Nikon, qui parlent le protocole PTP) n'est pas vu : passez par un lecteur de cartes.
- Une vidéo sans métadonnées prend l'appareil le plus fréquent de la carte, et la date du fichier.
- Carte retirée en pleine copie : ce qui est entièrement copié est rangé, le reste sera copié au prochain branchement.
- macOS seulement (SwiftBar, notifications, éjection par `diskutil`).

## Tests

Sur de fausses cartes (de simples dossiers), sans jamais toucher un vrai disque :

```bash
python3 tests/test_import.py
```

## Licence

MIT, voir [`LICENSE`](LICENSE).
