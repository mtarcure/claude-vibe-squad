#!/usr/bin/env bash
# Compatibility namespace -> visible model-lane tmux window name.
#
# Departments are mailbox/source namespaces only. They deliberately map onto
# the four execution lanes so folder location cannot imply model choice.

lead_window_name() {
    case "$1" in
        coding)   echo "gpt-codex" ;;
        security) echo "claude" ;;
        content)  echo "gemini" ;;
        sysmgmt)  echo "claude" ;;
        research) echo "kimi" ;;
        chrono)   echo "chrono" ;;
        watchers) echo "watchers/status" ;;
        *)        echo "$1" ;;
    esac
}

lead_display_name() {
    case "$1" in
        coding)   echo "GPT/Codex Lane" ;;
        security) echo "Claude Lane" ;;
        content)  echo "Gemini Lane" ;;
        sysmgmt)  echo "Claude Lane" ;;
        research) echo "Kimi Lane" ;;
        chrono)   echo "Chrono Coordinator" ;;
        *)        echo "$1" ;;
    esac
}
