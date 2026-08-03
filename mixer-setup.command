#!/bin/zsh
# Knob layout and fader mode selector for the MIDI Mix → Logic bridge.
# mixer-mode.command reads the saved choices on its next launch.

cd -- "$(dirname "$0")" || exit 1

layout_file=".knob_layout"
takeover_file=".soft_takeover"

current_layout="fixed"
current_takeover="on"
setup_failed=0

if [[ -f "$layout_file" ]]; then
  saved_layout=$(<"$layout_file")
  case "$saved_layout" in
    fixed|vpot|disabled) current_layout="$saved_layout" ;;
    *)
      print -u2 "Warning: ignoring invalid knob setting '$saved_layout'; using fixed."
      ;;
  esac
fi

if [[ -f "$takeover_file" ]]; then
  saved_takeover=$(<"$takeover_file")
  case "$saved_takeover" in
    on|off) current_takeover="$saved_takeover" ;;
    *)
      print -u2 "Warning: ignoring invalid fader setting '$saved_takeover'; using soft-takeover."
      ;;
  esac
fi

save_preference() {
  local setting_value="$1"
  local setting_file="$2"
  if print -r -- "$setting_value" > "$setting_file"; then
    return 0
  fi

  print -u2 "Error: could not save '$setting_value' to $setting_file."
  return 1
}

print "MIDI Mix → Logic Pro bridge setup"
print "================================="
print
print "Current settings:"
print "  Knob layout:   $current_layout"
print "  Fader mode:    $(if [[ $current_takeover == off ]]; then print absolute; else print soft-takeover; fi)"
print

print "Knob layout:"
print "  1) fixed                 — 24 stable custom-learn knobs (does not bank)"
print "                           Learn any Logic parameter per knob."
print "  2) vpot                  — top row controls one manually selected MCU parameter"
print "                              (banked; Pan or one send slot, no learns)"
print "  3) disabled              — knobs off"
print
printf "Choose knob layout [1-3, Enter to keep current]: "
read -r choice
case "$choice" in
  1)
    if save_preference "fixed" "$layout_file"; then
      current_layout="fixed"
      print "  → fixed custom-learn knobs"
    else
      setup_failed=1
    fi
    ;;
  2)
    if save_preference "vpot" "$layout_file"; then
      current_layout="vpot"
      print "  → one manually selected banked V-Pot parameter"
    else
      setup_failed=1
    fi
    ;;
  3)
    if save_preference "disabled" "$layout_file"; then
      current_layout="disabled"
      print "  → disabled"
    else
      setup_failed=1
    fi
    ;;
  "") print "  (keeping $current_layout)" ;;
  *) print "  unknown choice, keeping $current_layout" ;;
esac

print
print "Fader mode:"
print "  1) soft-takeover — fader must cross Logic's value before it takes effect"
print "                     (prevents jumps after banking or switching projects)"
print "  2) absolute      — fader always sends its position immediately"
print
printf "Choose fader mode [1-2, Enter to keep current]: "
read -r choice
case "$choice" in
  1)
    if save_preference "on" "$takeover_file"; then
      current_takeover="on"
      print "  → soft-takeover"
    else
      setup_failed=1
    fi
    ;;
  2)
    if save_preference "off" "$takeover_file"; then
      current_takeover="off"
      print "  → absolute"
    else
      setup_failed=1
    fi
    ;;
  "") print "  (keeping $(if [[ $current_takeover == off ]]; then print absolute; else print soft-takeover; fi))" ;;
  *) print "  unknown choice, keeping $(if [[ $current_takeover == off ]]; then print absolute; else print soft-takeover; fi)" ;;
esac

print
if (( setup_failed )); then
  print -u2 "Setup finished with an error; one or more choices were not saved."
else
  print "Settings saved. They apply the next time mixer-mode.command starts."
  print "If the bridge is already running, quit and relaunch it."
fi

case "$current_layout" in
  vpot)
    print "The top knob row will control the V-Pot parameter selected in Logic."
    ;;
  fixed)
    print "After starting the bridge, type 'learn' for the one-time Logic"
    print "Controller Assignment instructions."
    ;;
  disabled)
    print "The bridge will ignore all three knob rows."
    ;;
esac

print
print "Press any key to close."
read -k 1

(( setup_failed )) && exit 1
exit 0
