#!/bin/bash

java org.antlr.v4.Tool -Dlanguage=Python3 -long-messages dcm20.g4 -o ./parsers/
