<#
.SYNOPSIS
    Espelha as skills de .agents/skills/ em .claude/skills/.

.DESCRIPTION
    As skills compartilhadas deste repositorio vivem em .agents/skills/, no
    formato universal que Codex, Copilot, Amp e outros agentes leem. O Claude
    Code so carrega skills de .claude/skills/ -- sem o espelho, as skills do
    projeto existem no disco e nenhum agente Claude as enxerga, que e o que
    aconteceu ate 2026-09-04.

    O espelho usa junction de diretorio (nao symlink) porque symlink nativo no
    Windows exige privilegio de administrador ou Modo Desenvolvedor, e junction
    nao exige. Os junctions sao ignorados pelo .gitignore: versiona-los faria o
    mesmo conteudo entrar no repositorio duas vezes.

    Rode depois de clonar o repositorio, ou depois de adicionar uma skill nova
    em .agents/skills/. E idempotente.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\link-skills.ps1
    powershell -ExecutionPolicy Bypass -File scripts\link-skills.ps1 -Prune
#>
[CmdletBinding()]
param(
    # Remove junctions em .claude/skills/ cujo alvo nao existe mais.
    [switch]$Prune
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceDir = Join-Path $repoRoot '.agents\skills'
$targetDir = Join-Path $repoRoot '.claude\skills'

if (-not (Test-Path $sourceDir)) {
    Write-Output "Nada a fazer: $sourceDir nao existe."
    exit 0
}

if (-not (Test-Path $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir | Out-Null
}

function Test-IsJunction {
    param([string]$Path)
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if ($null -eq $item) { return $false }
    return [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
}

$linked = 0
$skipped = 0

foreach ($skill in Get-ChildItem -Path $sourceDir -Directory) {
    $link = Join-Path $targetDir $skill.Name

    if (Test-Path -LiteralPath $link) {
        # Um diretorio real com o mesmo nome e uma skill propria do Claude
        # (ex.: aurora-*), versionada aqui. Nunca sobrescrever.
        $skipped++
        continue
    }

    New-Item -ItemType Junction -Path $link -Target $skill.FullName | Out-Null
    Write-Output "  + $($skill.Name)"
    $linked++
}

$pruned = 0
if ($Prune) {
    foreach ($entry in Get-ChildItem -Path $targetDir -Directory -Force) {
        if (-not (Test-IsJunction $entry.FullName)) { continue }
        $origin = Join-Path $sourceDir $entry.Name
        if (Test-Path -LiteralPath $origin) { continue }
        Remove-Item -LiteralPath $entry.FullName -Force
        Write-Output "  - $($entry.Name) (alvo removido)"
        $pruned++
    }
}

Write-Output ""
Write-Output "Skills espelhadas: $linked criadas, $skipped ja existiam$(if ($Prune) { ", $pruned removidas" })."
Write-Output "Reinicie a sessao do Claude Code para o catalogo de skills recarregar."
