#!/bin/sh -e
# Run all of the tests in the test directory, bailing out if any fail.

cd "$(dirname $0)"
export PYTHONPATH=$(cd .. && pwd):$PYTHONPATH
for test in test_*.py; do
	echo "$test"
	python "$test"
done
