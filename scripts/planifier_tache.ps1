<#
  Installe ou retire la tâche planifiée Windows d'Alternance Copilot.
  Chaque jour à l'heure choisie : collecte des offres ; notation par Claude le lundi, mercredi et vendredi.

  Exemples :
    .\planifier_tache.ps1 -Action installer -Heure 10:00
    .\planifier_tache.ps1 -Action retirer
#>
param(
    [ValidateSet("installer", "retirer", "etat")] [string] $Action = "installer",
    [string] $Heure = "10:00",
    [string] $Nom = "Alternance Copilot - collecte"
)
$ErrorActionPreference = "Stop"
$projet = Split-Path -Parent $PSScriptRoot

if ($Action -eq "retirer") {
    Unregister-ScheduledTask -TaskName $Nom -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Tâche « $Nom » retirée."
    exit 0
}

if ($Action -eq "etat") {
    $tache = Get-ScheduledTask -TaskName $Nom -ErrorAction SilentlyContinue
    if ($null -eq $tache) { Write-Host "Tâche « $Nom » non installée."; exit 1 }
    $info = $tache | Get-ScheduledTaskInfo
    Write-Host "Tâche « $Nom » : $($tache.State) · prochaine exécution : $($info.NextRunTime) · dernière : $($info.LastRunTime) (code $($info.LastTaskResult))"
    exit 0
}

$python = Join-Path $projet ".venv\Scripts\pythonw.exe"   # pythonw : aucune fenêtre ne s'ouvre
if (-not (Test-Path $python)) { throw "Environnement Python introuvable : $python" }

$tache = New-ScheduledTaskAction -Execute $python -Argument "-m src.automatisation" -WorkingDirectory $projet
$declencheur = New-ScheduledTaskTrigger -Daily -At $Heure
$reglages = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)
# StartWhenAvailable : si le PC était éteint à l'heure prévue, la tâche se lance dès que possible

Register-ScheduledTask -TaskName $Nom -Action $tache -Trigger $declencheur -Settings $reglages `
    -Description "Alternance Copilot : collecte quotidienne des offres, notation par Claude lundi/mercredi/vendredi." `
    -Force | Out-Null
Write-Host "Tâche « $Nom » installée : tous les jours à $Heure (utilisateur courant, session ouverte)."
Write-Host "Journal : $projet\data\logs\automatisation.log"
