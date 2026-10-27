param([string]$Raiz = (Split-Path -Parent $PSScriptRoot), [string[]]$Modulos = @())
# Roda os módulos de teste Python em paralelo, um processo por módulo, como o unittest discover do CI.
# Sai com código 1 quando algum módulo falha.
Set-Location $Raiz
$Modulos = @($Modulos | ForEach-Object { $_ -split "," } | Where-Object { $_ })
if (-not $Modulos.Count) {
  $Modulos = Get-ChildItem (Join-Path $Raiz "tests") -Filter "test_*.py" | ForEach-Object { "tests." + $_.BaseName }
}
$t = Get-Date
$res = $Modulos | ForEach-Object -ThrottleLimit 12 -Parallel {
  Set-Location $using:Raiz
  $saida = python -m unittest $_ 2>&1 | Out-String
  $codigo = $LASTEXITCODE
  $ran = ([regex]::Match($saida, "Ran (\d+) test")).Groups[1].Value
  [pscustomobject]@{ modulo = $_; ok = ($codigo -eq 0); testes = [int]("0" + $ran); saida = $saida }
}
$falhas = @($res | Where-Object { -not $_.ok })
"python: {0} módulos, {1} testes, {2} com falha ({3:n0}s)" -f $res.Count, ($res | Measure-Object -Property testes -Sum).Sum, $falhas.Count, ((Get-Date) - $t).TotalSeconds
foreach ($f in $falhas) { "=== $($f.modulo)"; ($f.saida -split "`n" | Select-String -Pattern "^(ERROR|FAIL):|Error|assert" | Select-Object -First 15) -join "`n" }
if ($falhas.Count) { exit 1 }
