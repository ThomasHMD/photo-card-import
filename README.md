**English** | [Français](README.fr.md)

# photo-card-import

**A macOS tool that imports photos from a camera SD card automatically: I plug in the card, and with no manual step the photos land on my Mac, sorted by shooting day and by camera. Every copy is verified byte for byte, then the card is emptied and ejected: all that is left is to pull it out.**

```
Import cartes/
  2026-10-29_D750/
  2026-11-09_D750/
  2026-11-09_RicohGR/
```

A small Mac tool: a Python script, and a menu bar icon thanks to [SwiftBar](https://github.com/swiftbar/SwiftBar). It works with anything that shows up as a disk with a `DCIM` folder: an SD card in the reader, or a camera plugged in over USB that mounts as a disk.

## What it does

- **It detects the card by itself.** Every 10 seconds, the icon checks whether a disk with a `DCIM` has just arrived, and starts the import. During the copy it shows the progress (`37/71`), then a notification says what arrived and where.
- **One folder per day and per camera.** The day is the shooting day (the camera's clock, read from the EXIF metadata). The camera is also read from the EXIF, never from the card's name: a card moved from one body to another mixes nothing up. You choose the short name of each camera (`D750`, `RicohGR`...).
- **A verified copy.** The file read from the card and its copy read back from the disk are compared byte for byte (BLAKE2 hash). A different copy is an error, and the file is copied again on the next pass.
- **Never the same file twice.** A journal keeps track of everything that was imported. A card plugged back in without having been emptied only gives back the new photos, even if you moved or sorted the folders in the meantime. The same photo saved on both cards of a dual-slot body is copied only once.
- **Nothing is ever overwritten.** Two different photos with the same name (the camera's counter went back to zero) give `DSC_0001.JPG` and `DSC_0001_2.JPG`.
- **Handy with a folder synced to the cloud.** The copy first goes to a hidden folder on the same disk, then everything is put in place at once. The sync service only sees the files at the end and does not slow the transfer down.
- **The card emptied, as an option.** With `"vider_la_carte": true`, a file is only erased from the card if its identical copy is in the destination folder **at that moment**. Copy missing (folder emptied since) or different: the file stays on the card. Nothing is erased if the import was interrupted. Only photo and video files are erased, never folders or the camera's own files. The option is off by default: on my machine it is on.
- **The card ejected** when everything went well. Otherwise it stays plugged in, so the problem shows in the menu.
- **It checks the free space** before copying (2 GB of margin) and runs only one import at a time: a second card waits its turn.

## Installation

You need a Mac with:
- [SwiftBar](https://github.com/swiftbar/SwiftBar) (free);
- `python3` (it comes with Apple's command line tools: `xcode-select --install`);
- `exiftool`: `brew install exiftool` with [Homebrew](https://brew.sh).

Then, in Terminal:

```bash
git clone https://github.com/ThomasHMD/photo-card-import.git
cd photo-card-import
cp appareils.exemple.json appareils.json      # your settings, to adapt
ln -s "$PWD/import-cartes.10s.sh" "$(defaults read com.ameba.SwiftBar PluginDirectory)/import-cartes.10s.sh"
```

The camera icon appears in the menu bar. Without `appareils.json`, the tool uses the example's settings: photos go to `~/Pictures/Import cartes` and the card is not emptied.

Before the first real import, you can see what would be copied without touching anything:

```bash
python3 -I import-cartes.py importer --simulation
```

## Settings (`appareils.json`)

| Setting | Role |
|---|---|
| `destination` | The folder where the photos arrive: absolute path, with `~`, or relative to the settings file. |
| `vider_la_carte` | `true`: each file is erased from the card once its identical copy is verified. |
| `ejecter_apres_import` | `true`: the card is ejected when everything went well. |
| `notifications` | `false` to turn notifications off. |
| `appareils` | The short name of each camera. The first rule whose EXIF make **and** model contain the given texts wins (`""` = any). Unknown camera: its EXIF model, without spaces. |
| `volumes_ignores` | The disks never to look at. |
| `extensions_photo`, `extensions_video` | The files that get copied. |
| `depot` *(optional)* | The intermediate folder, relative to the root of the destination's disk (`.import-cartes-depot` by default). If the destination is on the Mac's own disk: `~/.import-cartes-depot`. |
| `journal` *(optional)* | The list of what has already been imported (`journal/importes.tsv` by default). Placed in a synced folder, it is shared by several Macs. |

Game console cards (the New 2DS XL's SD, an R4 card) are always ignored, despite their `DCIM` folder: they carry the `.console-2ds` or `.carte-ds` marker (14/11/2026, the 2DS's SD had been imported and ejected right in the middle of installing mods).

## Usage

Nothing to do: plug in the card. The icon's menu also offers:
- **Cartes branchées** (plugged-in cards): for each card, *Importer maintenant* (import now) and *Éjecter* (eject);
- **Dernier import** (last import): the number of files, the volume copied, a link to each folder created, any errors;
- **Tout importer maintenant** (import everything now), if nothing started by itself;
- **Ouvrir** (open) the destination folder, and the **Journal** (log).

On the command line:

```bash
python3 -I import-cartes.py importer                   # every plugged-in card
python3 -I import-cartes.py importer "/Volumes/NO NAME"
python3 -I import-cartes.py importer --simulation      # what would be copied, touching nothing
python3 -I import-cartes.py etat
```

Each Mac's state (progress, last import) is in `~/Library/Application Support/import-cartes/`, the text log in `~/Library/Logs/import-cartes/import-cartes.log`.

## Limits

- A camera plugged in **by cable** that does not mount as a disk (many Nikons, which speak the PTP protocol) is not seen: use a card reader.
- A video without metadata takes the card's most frequent camera, and the file's date.
- Card pulled out mid-copy: whatever is entirely copied is put in place, the rest will be copied the next time it is plugged in.
- macOS only (SwiftBar, notifications, ejection through `diskutil`).

## Tests

On fake cards (plain folders), never touching a real disk:

```bash
python3 tests/test_import.py
```

## License

MIT, see [`LICENSE`](LICENSE).
