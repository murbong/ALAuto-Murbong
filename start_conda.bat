@echo off
call conda activate azurlane
title ALAUTO
:alauto
python alauto.py --debug
goto alauto