[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Speech
$wallSenseSpeaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $wallSenseSpeaker.SelectVoice('Microsoft Huihui Desktop')
    $wallSenseSpeaker.Rate = 0
    while ($null -ne ($wallSenseCue = [Console]::ReadLine())) {
        if ($wallSenseCue.Length -gt 0) { $wallSenseSpeaker.Speak($wallSenseCue) }
    }
} finally {
    $wallSenseSpeaker.Dispose()
}
