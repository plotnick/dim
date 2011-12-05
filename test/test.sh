#!/bin/sh -e

TESTDIR=$(dirname $0)
PYTHONPATH=$TESTDIR/..:$PYTHONPATH

cd $TESTDIR
for t in test_*.py; do
	echo $t
	python $t
done
