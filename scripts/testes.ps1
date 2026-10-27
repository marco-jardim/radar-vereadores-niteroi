param(
  [string]$Raiz = (Split-Path -Parent $PSScriptRoot),
  [string[]]$Modulos = @(),
  [string]$Python = "python",
  [int]$ThrottleLimit = 12
)
# Roda os módulos de teste Python em paralelo, um processo por módulo, cobrindo os mesmos módulos que
# "python -m unittest discover -s tests -t ." encontra (inclusive subpacotes). Sai com 1 se algum módulo
# falhar ou se nenhum teste rodar. O CI continua sequencial e é a referência: testes que dependem de
# ordem ou gravam no mesmo caminho podem se comportar diferente aqui.
[Console]::OutputEncoding = [Text.UTF8Encoding]::new()
Push-Location $Raiz -ErrorAction Stop
try {
  $Modulos = @($Modulos | ForEach-Object { $_ -split "," } | Where-Object { $_ })
  if (-not $Modulos.Count) {
    $dirTestes = Get-Item -LiteralPath (Join-Path $Raiz "tests") -ErrorAction Stop
    $Modulos = @(Get-ChildItem -LiteralPath $dirTestes.FullName -Recurse -File -Filter "test_*.py" -ErrorAction Stop | Where-Object {
      # O discover só entra em subdiretórios que sejam pacotes, inclusive todos os ancestrais.
      $dir = $_.Directory
      $pacote = $true
      while ($null -ne $dir) {
        if (-not (Test-Path -LiteralPath (Join-Path $dir.FullName "__init__.py") -PathType Leaf)) {
          $pacote = $false
          break
        }
        if ($dir.FullName -eq $dirTestes.FullName) { break }
        $dir = $dir.Parent
      }
      $pacote
    } | Sort-Object FullName | ForEach-Object {
      $rel = [IO.Path]::GetRelativePath($dirTestes.FullName, $_.FullName) -replace "\.py$", ""
      "tests." + ($rel -replace "[\\/]", ".")
    })
  }
  $t = Get-Date
  $res = @($Modulos | ForEach-Object -ThrottleLimit $ThrottleLimit -Parallel {
    Set-Location $using:Raiz
    $saida = & $using:Python -m unittest $_ 2>&1 | Out-String
    $codigo = $LASTEXITCODE
    $ran = ([regex]::Match($saida, "Ran (\d+) test")).Groups[1].Value
    # Código 5 = módulo sem testes; o discover não o trata como falha.
    [pscustomobject]@{ modulo = $_; ok = ($codigo -eq 0 -or $codigo -eq 5); testes = [int]("0" + $ran); saida = $saida }
  })
  $total = ($res | Measure-Object -Property testes -Sum).Sum
  $falhas = @($res | Where-Object { -not $_.ok })
  "python: {0} módulos, {1} testes, {2} com falha ({3:n0}s)" -f $res.Count, [int]$total, $falhas.Count, ((Get-Date) - $t).TotalSeconds
  foreach ($f in $falhas) { "=== $($f.modulo)"; ($f.saida -split "`n" | Select-String -Pattern "^(ERROR|FAIL):|Error|assert" | Select-Object -First 15) -join "`n" }
  if ($falhas.Count -or -not $total) { exit 1 }
}
finally {
  Pop-Location
}
