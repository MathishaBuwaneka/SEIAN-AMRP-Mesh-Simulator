param()
$ErrorActionPreference = 'Stop'
$paper = $PSScriptRoot
$output = Join-Path $paper 'build'
New-Item -ItemType Directory -Force -Path $output | Out-Null

function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Exe failed with exit code $LASTEXITCODE. See build/main.log."
    }
}

$tex = (Get-Command pdflatex -ErrorAction Stop).Source
$bib = (Get-Command bibtex -ErrorAction Stop).Source
$texArgs = @('-interaction=nonstopmode', '-halt-on-error', '-file-line-error',
             '-no-shell-escape', '-output-directory=build', 'main.tex')
if ((& $tex --version | Select-Object -First 1) -match 'MiKTeX') {
    $texArgs = @('--disable-installer') + $texArgs
}
$oldBibInputs = $env:BIBINPUTS
Push-Location $paper
try {
    Invoke-Checked $tex $texArgs
    $env:BIBINPUTS = "$paper;$oldBibInputs;"
    Push-Location $output
    try {
        Invoke-Checked $bib @('main')
    } finally {
        Pop-Location
    }
    Invoke-Checked $tex $texArgs
    Invoke-Checked $tex $texArgs
    $log = Get-Content -Raw -LiteralPath (Join-Path $output 'main.log')
    if ($log -match 'There were undefined references|Citation .+ undefined|Reference .+ undefined') {
        throw 'The PDF has unresolved references; inspect build/main.log.'
    }
    Write-Host "Built $(Join-Path $output 'main.pdf')"
} finally {
    $env:BIBINPUTS = $oldBibInputs
    Pop-Location
}
