#!/bin/zsh
# Double-click launcher for the MIDI Mix → Logic mixer bridge.
#
# Keep this file beside tools/. Future options can be passed when launched
# from Terminal, for example:  ./mixer-mode.command <future-option>

cd -- "$(dirname "$0")" || exit 1

python3 tools/mcu_surface.py run "$@"
status=$?

# A double-clicked .command window can close before an error is readable.
if [[ $status -ne 0 ]]; then
  print
  print "Mixer bridge stopped with status $status. Press any key to close."
  read -k 1
fi

exit $status
