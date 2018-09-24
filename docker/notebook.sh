#!/usr/bin/env bash

source "${HOME}/.bash_profile"
# source activate dask-distributed

echo "limits are: " `ulimit -n`
jupyter lab --allow-root "$@"
