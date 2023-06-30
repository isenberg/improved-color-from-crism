#!/bin/sh
SCRIPTDIR=`cd "\`dirname "$0"\`" && pwd`
IMGDIR="$1"

cd $SCRIPTDIR
if [ -d "$IMGDIR" ]; then
  echo "processing images in $IMGDIR..."
  find "$IMGDIR" -name \*if\*mtr3\*lbl -exec python3 crism.py mtrdr_to_color --file={} --name={} \;
else
  echo "usage: $0 IMGDIR"
  echo "  IMGDIR needs to contain pairs of *if*mtr3*.lbl, *if*mtr3*.img"
  exit 1
fi
