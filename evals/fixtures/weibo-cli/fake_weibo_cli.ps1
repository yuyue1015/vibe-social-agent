$python = $env:PYTHON
if (-not $python) { $python = "python" }
$script = Join-Path $PSScriptRoot "fake_weibo_cli.py"
& $python $script @args
exit $LASTEXITCODE
