@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Teams Chat Extractor

cd /d "%~dp0"

REM 1. Detectar ejecutable de Python
set "PYTHON_CMD="

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD=.venv\Scripts\python.exe"
    goto PYTHON_FOUND
)
if exist "venv\Scripts\python.exe" (
    set "PYTHON_CMD=venv\Scripts\python.exe"
    goto PYTHON_FOUND
)

where py >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "PYTHON_CMD=py"
    goto PYTHON_FOUND
)

where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "PYTHON_CMD=python"
    goto PYTHON_FOUND
)

:PYTHON_NOT_FOUND
echo ===============================================================================
echo [ERROR] No se ha encontrado Python en el sistema.
echo.
echo Por favor, instala Python 3.10 o superior desde https://www.python.org/
echo IMPORTANTE: Marca la opcion "Add Python to PATH" durante la instalacion.
echo ===============================================================================
echo.
pause
exit /b 1

:PYTHON_FOUND
REM 2. Comprobar dependencia cramjam
"%PYTHON_CMD%" -c "import cramjam" >nul 2>nul
if errorlevel 1 (
    echo [*] La libreria requerida 'cramjam' no esta instalada.
    echo [*] Instalando dependencia 'cramjam' mediante pip...
    "%PYTHON_CMD%" -m pip install cramjam
    if errorlevel 1 (
        echo.
        echo [ERROR] Fallo al instalar 'cramjam'. Ejecuta manualmente: pip install cramjam
        pause
        exit /b 1
    )
    echo [OK] Dependencias instaladas correctamente.
    echo.
)

REM 3. Si se pasaron argumentos desde consola, ejecutar directamente
if not "%~1"=="" (
    "%PYTHON_CMD%" parse_teams_chat.py %*
    exit /b
)

REM 4. Menu interactivo cuando se ejecuta con doble clic
:MENU
cls
echo ===============================================================================
echo                   TEAMS CHAT EXTRACTOR - INICIAR EXTRACCION
echo ===============================================================================
echo.
echo   [1] Iniciar extraccion segun config.json (por defecto)
echo   [2] Listar todas las conversaciones en la cache local (--list)
echo   [3] Extraer conversacion por palabra clave o titulo (--topic)
echo   [4] Extraer conversacion por Thread ID exacto (--id)
echo   [5] Salir
echo.
echo ===============================================================================
set "OPCION="
set /p "OPCION=Selecciona una opcion [1-5] (por defecto 1): "

if "%OPCION%"=="" set "OPCION=1"
if "%OPCION%"=="1" goto OP_DEFAULT
if "%OPCION%"=="2" goto OP_LIST
if "%OPCION%"=="3" goto OP_TOPIC
if "%OPCION%"=="4" goto OP_ID
if "%OPCION%"=="5" goto SALIR

echo.
echo [!] Opcion no valida. Intentalo de nuevo.
timeout /t 2 >nul
goto MENU

:OP_DEFAULT
echo.
echo [*] Iniciando extraccion con la configuracion por defecto...
"%PYTHON_CMD%" parse_teams_chat.py
goto FIN

:OP_LIST
echo.
echo [*] Descubriendo conversaciones disponibles en la cache local de Teams...
"%PYTHON_CMD%" parse_teams_chat.py --list
goto FIN

:OP_TOPIC
echo.
set "TOPIC_NAME="
set /p "TOPIC_NAME=Introduce el nombre o palabra clave de la conversacion: "
if "%TOPIC_NAME%"=="" (
    echo [!] Nombre no valido.
    pause
    goto MENU
)
echo.
echo [*] Extrayendo conversacion para el tema: "%TOPIC_NAME%"...
"%PYTHON_CMD%" parse_teams_chat.py --topic "%TOPIC_NAME%"
goto FIN

:OP_ID
echo.
set "THREAD_ID="
set /p "THREAD_ID=Introduce el Thread ID completo (ej. 19:...@thread.v2): "
if "%THREAD_ID%"=="" (
    echo [!] ID no valido.
    pause
    goto MENU
)
echo.
echo [*] Extrayendo conversacion para el ID: "%THREAD_ID%"...
"%PYTHON_CMD%" parse_teams_chat.py --id "%THREAD_ID%"
goto FIN

:FIN
echo.
echo ===============================================================================
echo  Operacion finalizada.
echo ===============================================================================
echo.
pause
goto MENU

:SALIR
exit /b 0
