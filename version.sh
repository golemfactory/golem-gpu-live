#! /bin/bash

tag2channel() {
  case "$1" in
    refs/tags/testing*)
      echo testing
      ;;
    refs/tags/v*)
      echo release
      ;;
    *)
      echo unstable
      ;;
  esac
}

if test -n "$1"
then
  echo "DIST_TYPE=$1"
else
  echo "DIST_TYPE=$(tag2channel $2)"
fi
