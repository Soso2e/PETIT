#requires -Version 7.0
param([string]$OutputDirectory = 'storage/wakeword/audio')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$corpus = Get-Content (Join-Path $PSScriptRoot 'corpus.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$root = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $root | Out-Null
if (Test-Path (Join-Path $root 'manifest.json')) { throw 'Manifest already exists; choose a new OutputDirectory.' }
$voices = @(
    @{ name = 'Microsoft Ayumi'; split = 'train' },
    @{ name = 'Microsoft Ichiro'; split = 'train' },
    @{ name = 'Microsoft Haruka'; split = 'validation' },
    @{ name = 'Microsoft Sayaka'; split = 'test' }
)
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$rows = [Collections.Generic.List[object]]::new()
try {
    $available = @($synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name })
    foreach ($voice in $voices) {
        if ($voice.name -notin $available) { throw "Missing local SAPI voice: $($voice.name)" }
    }
    foreach ($voice in $voices) {
        $synth.SelectVoice($voice.name)
        foreach ($label in @('positive', 'negative')) {
            foreach ($phrase in $corpus.$label) {
                foreach ($rate in @(-2, 0, 2)) {
                    $id = '{0:d5}' -f $rows.Count
                    $file = "$id.wav"
                    $synth.Rate = $rate
                    $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
                    $synth.SetOutputToWaveFile((Join-Path $root $file), $format)
                    $synth.Speak($phrase)
                    $synth.SetOutputToNull()
                    $rows.Add(@{ file=$file; label=$label; phrase=$phrase; voice=$voice.name; rate=$rate; split=$voice.split })
                }
            }
        }
        Write-Host "Synthesized $($voice.name): $($rows.Count) clips total"
    }
    $rows | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $root 'manifest.json') -Encoding UTF8
} finally { $synth.Dispose() }
