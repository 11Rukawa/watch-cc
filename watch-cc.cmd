@echo off
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
"C:\Users\quicktron\AppData\Local\Programs\Python\Python312\python.exe" "C:\Users\quicktron\.claude\bin\watch-cc.py" %*
