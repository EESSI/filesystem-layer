#!/bin/bash
#
# This file is part of the EESSI filesystem layer,
# see https://github.com/EESSI/filesystem-layer
#
# author: Thomas Roeblitz (@trz42)
#
# license: GPLv2
#
PYTHONPATH=$PWD:$PYTHONPATH pytest --capture=no "$@"