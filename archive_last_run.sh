#!/bin/bash

set -e

timestamp=$(date '+%Y_%m_%d_%H_%M_%S')
new_dir=/mnt/team/simulation_science/pub/models/vivarium_gates_lsff_2026_maternal/$timestamp
mkdir -p $new_dir

# https://unix.stackexchange.com/a/2503
rsync -v --stats --progress -am --include='*.hdf' --include '*.parquet' --include='*/' --exclude='*' . $new_dir

touch $new_dir/git_info.txt
git status >> $new_dir/git_info.txt
git diff >> $new_dir/git_info.txt