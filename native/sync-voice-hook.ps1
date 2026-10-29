param(
    [string]$PluginRoot = 'D:\dsh-mod\dsh-tts-bridge-wechatagent-bridge',
    [string]$WeChatAgentRoot = 'D:\WeChatAgent\data\workspace'
)
$ErrorActionPreference = 'Stop'
$mod = Join-Path $PluginRoot 'native\build\version.dll'
if (-not (Test-Path -LiteralPath $mod)) { throw 'Missing modified DLL: ' + $mod }
$native = Join-Path $WeChatAgentRoot 'state\hook\native'
$client = Join-Path $WeChatAgentRoot 'state\hook\wechat-4.1.10.27'
$sha = (Get-FileHash -LiteralPath $mod -Algorithm SHA256).Hash.ToLowerInvariant()
Copy-Item -LiteralPath $mod -Destination (Join-Path $native 'version.dll') -Force
Copy-Item -LiteralPath $mod -Destination (Join-Path $native 'deployed.previous.dll') -Force
Copy-Item -LiteralPath $mod -Destination (Join-Path $client 'version.dll') -Force
$utf8 = [Text.UTF8Encoding]::new($false)
foreach ($name in @('build.json','build.previous.json')) {
    $file = Join-Path $native $name
    $json = Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json
    $json.sha256 = $sha
    $json.integration = 'WeChatAgent-1+VoiceRoute'
    $json | Add-Member -NotePropertyName voiceRoute -NotePropertyValue '/SendVoiceMsg' -Force
    [IO.File]::WriteAllText($file, ($json | ConvertTo-Json -Depth 8), $utf8)
}
Write-Output ('Synced modified hook: ' + $sha)
Write-Output 'Now start WeChat directly, or run launch-hook-wechat.ps1 after WeChat is logged in.'
