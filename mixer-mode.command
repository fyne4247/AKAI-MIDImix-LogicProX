#!/bin/zsh
# Double-click launcher for the MIDI Mix → Logic mixer bridge.
# Keep this file beside tools/.

cd -- "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  print -u2 "Python 3 was not found."
  print -u2 "Install Python 3, then run mixer-mode.command again."
  print
  print "Press any key to close."
  read -k 1
  exit 127
fi

if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 9))'; then
  print -u2 "Python 3.9 or newer is required."
  print -u2 "Update Python, then run mixer-mode.command again."
  print
  print "Press any key to close."
  read -k 1
  exit 2
fi

python3 tools/mcu_surface.py run
bridge_status=$?

# A double-clicked .command window can close before an error is readable.
if [[ $bridge_status -ne 0 ]]; then
  print
  print "Mixer bridge stopped with status $bridge_status. Press any key to close."
  read -k 1
fi

exit $bridge_status
