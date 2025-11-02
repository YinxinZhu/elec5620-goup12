@echo off
setlocal ENABLEDELAYEDEXPANSION

set "SEED_DEMO=1"
set "RUN_SERVER=1"

:parse_args
if "%~1"=="" goto after_parse
if "%~1"=="--no-seed" (
  set "SEED_DEMO=0"
) else if "%~1"=="--skip-run" (
  set "RUN_SERVER=0"
) else if "%~1"=="-h" (
  goto show_help
) else if "%~1"=="--help" (
  goto show_help
) else (
  echo Unknown option: %~1
  goto show_help_error
)
shift
goto parse_args

:show_help
call :print_usage
endlocal
exit /b 0

:show_help_error
call :print_usage 1>&2
endlocal
exit /b 1

:print_usage
echo Usage: scripts\bootstrap.bat [options]
echo.
echo Creates a Python virtual environment, installs dependencies, initialises the database,
echo optionally seeds demo data, and starts the Flask development server.
echo.
echo Options:
echo   --no-seed      Skip loading demo data via "flask --app manage.py seed-demo".
echo   --skip-run     Only perform setup steps without starting the dev server.
echo   -h, --help     Show this help message and exit.
exit /b 0

:after_parse
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
pushd "%SCRIPT_DIR%\.." >nul
set "PROJECT_ROOT=%CD%"

where python >nul 2>&1
if errorlevel 1 (
  echo python is required but was not found in PATH 1>&2
  goto error
)

if not exist "%PROJECT_ROOT%\.venv" (
  echo Creating virtual environment in %PROJECT_ROOT%\.venv
  python -m venv "%PROJECT_ROOT%\.venv"
  if errorlevel 1 goto error
)

call "%PROJECT_ROOT%\.venv\Scripts\activate.bat"
if errorlevel 1 goto error

python -m pip install --upgrade pip
if errorlevel 1 goto error

python -m pip install -r requirements.txt
if errorlevel 1 goto error

flask --app manage.py init-db
if errorlevel 1 goto error

if "%SEED_DEMO%"=="1" (
  flask --app manage.py seed-demo
  if errorlevel 1 goto error
)

if "%RUN_SERVER%"=="1" (
  flask --app app run --debug
  if errorlevel 1 goto error
)

goto success

:error
popd >nul
endlocal
exit /b 1

:success
popd >nul
endlocal
exit /b 0
