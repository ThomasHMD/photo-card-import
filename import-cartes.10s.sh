#!/bin/zsh
# <bitbar.title>Import photos</bitbar.title>
# <bitbar.version>1.1</bitbar.version>
# <bitbar.author>Thomas Hammoudi</bitbar.author>
# <bitbar.author.github>ThomasHMD</bitbar.author.github>
# <bitbar.desc>Dès qu'une carte photo est branchée, copie ses photos et vidéos dans un dossier par jour de prise de vue et par appareil, vérifie chaque copie, puis vide (en option) et éjecte la carte.</bitbar.desc>
# <bitbar.abouturl>https://github.com/ThomasHMD/photo-card-import</bitbar.abouturl>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>
#
# Rafraîchi toutes les 10 s (le .10s du nom). À relier dans le dossier des plugins de SwiftBar, voir README.md.

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
SELF="${0:A}"; PY="${SELF:h}/import-cartes.py"
export IMPORT_CARTES_PLUGIN="$SELF"

case "$1" in
  importer) shift; python3 -I "$PY" lancer "$@" >/dev/null 2>&1; exit 0 ;;
  ejecter)  if diskutil eject "$2" >/dev/null 2>&1; then
              osascript -e "display notification \"Tu peux la retirer.\" with title \"${2:t} éjectée\""
            else
              osascript -e "display notification \"Pas éjectée : un import ou une appli l'utilise encore.\" with title \"${2:t}\""
            fi; exit 0 ;;
esac

exec python3 -I "$PY" menu
