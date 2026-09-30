# Text-to-speech for Buzz host lines using the Windows OneCore voices (WinRT), which include
# en-GB "George" (male), "Hazel" and "Susan". Run with Windows PowerShell 5.1 (powershell.exe):
# PowerShell 7 has no WinRT projection.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File buzz_tts.ps1 -Jobs jobs.json
#
# jobs.json: [{"text": "...", "out": "C:\\path\\clip.wav"}, ...]   (text may be SSML if it
# starts with "<speak"). Writes one 16-bit PCM WAV per job, at the voice's native rate.
param(
    [Parameter(Mandatory = $true)][string]$Jobs,
    [string]$Voice = "George",
    [double]$Rate = 1.0,
    [double]$Pitch = 1.0,
    [switch]$ListVoices
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime]

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$resultType) {
    $task = $asTaskGeneric.MakeGenericMethod($resultType).Invoke($null, @($op))
    $null = $task.Wait(-1)
    $task.Result
}

$all = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices
if ($ListVoices) { $all | ForEach-Object { "{0} | {1} | {2}" -f $_.DisplayName, $_.Language, $_.Gender }; exit 0 }

$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$v = $all | Where-Object { $_.DisplayName -like "*$Voice*" } | Select-Object -First 1
if (-not $v) { throw "voice '$Voice' not installed" }
$synth.Voice = $v
$synth.Options.SpeakingRate = $Rate
$synth.Options.AudioPitch = $Pitch

foreach ($job in (Get-Content -Raw -Encoding UTF8 $Jobs | ConvertFrom-Json)) {
    if ($job.text.TrimStart().StartsWith("<speak")) {
        $op = $synth.SynthesizeSsmlToStreamAsync($job.text)
    } else {
        $op = $synth.SynthesizeTextToStreamAsync($job.text)
    }
    $stream = Await $op ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
    $reader = New-Object Windows.Storage.Streams.DataReader($stream.GetInputStreamAt(0))
    $size = [uint32]$stream.Size
    $null = Await ($reader.LoadAsync($size)) ([uint32])
    $bytes = New-Object byte[] $size
    $reader.ReadBytes($bytes)
    [IO.File]::WriteAllBytes($job.out, $bytes)
    "{0}`t{1}" -f $size, $job.out
}
