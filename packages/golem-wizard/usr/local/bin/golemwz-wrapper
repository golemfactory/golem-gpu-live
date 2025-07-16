#!/bin/bash

sleep 3

function exit_wrapper {
    sudo /usr/bin/chvt 1
}

trap 'exit_wrapper' 0 1 2 3 6 15

sudo /usr/bin/chvt 6

/usr/local/bin/golemwz
