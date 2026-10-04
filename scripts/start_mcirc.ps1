# Starts mcIRC on any Windows PC.  Called by Run_GUI.bat (double-click that file; you do not run this one yourself).
#   - finds a Python 3.10+ with Tk: the project's .venv, the Python on PATH, the `py` launcher, the usual install folders (best match: one that already has the packages)
#   - on a first start installs the packages from requirements.txt (a visible window shows the progress)
#   - starts mcIRC without a console window; explains in a message box what to do when something is missing
# Options:  --make-shortcut  (put an mcIRC shortcut with the logo on the Desktop, then exit)   anything else is passed on to mcIRC.py
param([Parameter(ValueFromRemainingArguments = $true)] $Rest)
$ErrorActionPreference = 'SilentlyContinue'
$testing = [bool]$env:MCIRC_LAUNCHER_TEST          # tests: no dialogs, no pip, no browser - the text goes to the file named in MCIRC_LAUNCHER_TEST
$here = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $here
Add-Type -AssemblyName System.Windows.Forms

function Say($text, $icon = 'Information') {
    if ($testing) { Add-Content -Path $env:MCIRC_LAUNCHER_TEST -Value "SAY: $text"; return }
    [void][System.Windows.Forms.MessageBox]::Show($text, 'mcIRC', 'OK', $icon)
}
function Runs($py) {     # a Python we can use: 3.10 or newer, with Tk
    if (-not $py -or -not (Test-Path $py)) { return $false }
    & $py -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
    return ($LASTEXITCODE -eq 0)
}
function HasPackages($py) { & $py -c "import meshcore_cli, serial" 2>$null; return ($LASTEXITCODE -eq 0) }

# --- candidates, best first ---------------------------------------------------------------------------------------------
$roots = @()
if ($env:MCIRC_TEST_PYTHONS) { $roots = $env:MCIRC_TEST_PYTHONS -split ';' | Where-Object { $_ } }
else {
    $roots += Join-Path $here '.venv\Scripts\python.exe'
    Get-Command python.exe -All | Where-Object { $_.Source -notmatch 'WindowsApps' } | ForEach-Object { $roots += $_.Source }      # (the Microsoft Store stub is not a real Python)
    $pyl = (Get-Command py.exe | Select-Object -First 1).Source
    if ($pyl) { $p = & $pyl -3 -c "import sys; print(sys.executable)" 2>$null; if ($p) { $roots += $p } }
    foreach ($pat in "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "$env:ProgramFiles\Python3*\python.exe", "${env:ProgramFiles(x86)}\Python3*\python.exe", "C:\Python3*\python.exe") {
        Get-ChildItem $pat | Sort-Object FullName -Descending | ForEach-Object { $roots += $_.FullName }
    }
}
$usable = @($roots | Select-Object -Unique | Where-Object { Runs $_ })
$py = $usable | Where-Object { HasPackages $_ } | Select-Object -First 1
$needInstall = $false
if (-not $py -and $usable.Count -gt 0) { $py = $usable[0]; $needInstall = $true }

if (-not $py) {
    Say ("mcIRC needs Python 3.10 or newer (with Tk), and none was found on this PC.`n`nThe Python download page will open. In its installer tick 'Add python.exe to PATH' and keep 'tcl/tk and IDLE' selected, then double-click Run_GUI.bat again.") 'Warning'
    if (-not $testing) { Start-Process 'https://www.python.org/downloads/windows/' }
    exit 2
}

if ($needInstall) {
    if ($testing -and -not $env:MCIRC_TEST_PIPARGS) { Add-Content -Path $env:MCIRC_LAUNCHER_TEST -Value "WOULD INSTALL packages with $py"; exit 0 }
    $pipArgs = if ($env:MCIRC_TEST_PIPARGS) { $env:MCIRC_TEST_PIPARGS } else { "install -r `"$here\requirements.txt`"" }       # (tests swap in a harmless pip command)
    $cmd = "`"$py`" -m pip $pipArgs"
    Say "First start: mcIRC will now install the Python packages it needs (meshcore-cli, pyserial, ...). A window shows the progress; it takes a minute. Press OK to start." 'Information'
    # cmd strips the first and last quote of a /c line that starts with a quote and has more than two: wrap everything in one more pair and use /s so exactly that pair is removed
    $style = if ($testing) { 'Hidden' } else { 'Normal' }
    Start-Process -FilePath $env:ComSpec -ArgumentList "/s /c `"$cmd & if errorlevel 1 (echo. & echo Installing failed - see the message above. & pause)`"" -WindowStyle $style -Wait
    if (-not (HasPackages $py)) { Say "The packages could not be installed.`n`nOpen a command prompt in the mcIRC folder and run:`n    pip install -r requirements.txt`nThen try again." 'Error'; exit 3 }
}

$wanted = @($Rest)
if ($wanted -contains '--make-shortcut') {
    $out = & $py (Join-Path $here 'mcIRC.py') --make-shortcut 2>&1 | Out-String
    Say $out.Trim()
    exit 0
}
$pyw = Join-Path (Split-Path $py -Parent) 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = $py }
$argList = '"' + (Join-Path $here 'mcIRC.py') + '"'
if ($wanted.Count) { $argList += ' ' + (($wanted | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' ') }
if ($testing) { Add-Content -Path $env:MCIRC_LAUNCHER_TEST -Value "START: $pyw $argList"; exit 0 }
Start-Process -FilePath $pyw -ArgumentList $argList -WorkingDirectory $here
