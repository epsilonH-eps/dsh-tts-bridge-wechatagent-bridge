param(
    [string]$MsBuild = ''
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root 'hook-copy\WeChat-Hook'
$native = Join-Path $root 'hook-copy\native-hook'
$build = Join-Path $root 'build-source'
$output = Join-Path $root 'build'
if (-not (Test-Path -LiteralPath (Join-Path $source 'x64_Version_dll.vcxproj'))) { throw 'Hook source copy missing.' }
New-Item -ItemType Directory -Path $build,$output -Force | Out-Null
if (Test-Path -LiteralPath $build) { Get-ChildItem $build -Force | Remove-Item -Recurse -Force }
foreach ($entry in Get-ChildItem -LiteralPath $source -Force) {
    if ($entry.Name -eq '.git') { continue }
    Copy-Item -LiteralPath $entry.FullName -Destination $build -Recurse -Force
}
$encoding = [Text.UTF8Encoding]::new($false)
function Replace-Checked([string]$File, [string]$Before, [string]$After) {
    $text = [IO.File]::ReadAllText($File)
    if (-not $text.Contains($Before)) { throw ('Expected upstream code missing: ' + $File + ' :: ' + $Before) }
    [IO.File]::WriteAllText($File, $text.Replace($Before, $After), $encoding)
}
Replace-Checked (Join-Path $build 'src\inline_weixin_dll_load.cpp') 'g_httpServer->Start("0.0.0.0", g_StartPort);' 'g_httpServer->Start("127.0.0.1", g_StartPort);'
Replace-Checked (Join-Path $build 'src\inline_weixin_dll_load.cpp') '#include "global.h"' "#include `"global.h`"`n#include `"deferred_init.h`""
Replace-Checked (Join-Path $build 'src\inline_weixin_dll_load.cpp') '    Patch_Revoke();' '    // WeChatAgent does not change message recall behavior.'
Replace-Checked (Join-Path $build 'dllmain.cpp') 'HideModuleFromPEB(hModule);' '// WeChatAgent keeps the module visible for diagnostics.'
Replace-Checked (Join-Path $build 'dllmain.cpp') '#include "global.h"' "#include `"global.h`"`n#include `"deferred_init.h`""
Replace-Checked (Join-Path $build 'dllmain.cpp') 'CustomInit(hModule);' 'ScheduleWeChatAgentInit(hModule);'
Replace-Checked (Join-Path $build 'dllmain.cpp') '    if (ul_reason_for_call == DLL_PROCESS_ATTACH)' "    if (ul_reason_for_call == DLL_PROCESS_DETACH) { CancelWeChatAgentInit(); return TRUE; }`n    if (ul_reason_for_call == DLL_PROCESS_ATTACH)"
Replace-Checked (Join-Path $build 'src\version_proxy.cpp') '#include "version_proxy.h"' "#include `"version_proxy.h`"`n#include `"deferred_init.h`""
Replace-Checked (Join-Path $build 'src\version_proxy.cpp') '    g_hWeixinExe = GetModuleHandleW(L"weixin.exe");' "    WeChatAgentInitStage(`"module_lookup`");`n    g_hWeixinExe = GetModuleHandleW(L`"weixin.exe`");"
Replace-Checked (Join-Path $build 'src\version_proxy.cpp') '    if (MH_Initialize() != MH_OK)' "    WeChatAgentInitStage(`"minhook_initialize`");`n    const auto minhookStatus = MH_Initialize();`n    WeChatAgentInitLog(`"minhook_status`", static_cast<unsigned long>(minhookStatus));`n    if (minhookStatus != MH_OK && minhookStatus != MH_ERROR_ALREADY_INITIALIZED)"
Replace-Checked (Join-Path $build 'src\version_proxy.cpp') '    Evt_WeixinLoad();' "    WeChatAgentInitStage(`"weixin_load_enter`");`n    Evt_WeixinLoad();`n    WeChatAgentInitStage(`"weixin_load_returned`");"
Replace-Checked (Join-Path $build 'src\inline_weixin_dll_load.cpp') 'GetParentProcessId();' "GetParentProcessId();`n    WeChatAgentInitStage(`"parent_pid_ready`");"
Replace-Checked (Join-Path $build 'src\inline_weixin_dll_load.cpp') '        g_httpServer = new HttpServer();' "        WeChatAgentInitStage(`"http_wrapper_construct`");`n        g_httpServer = new HttpServer();"
[IO.File]::WriteAllText((Join-Path $build 'src\http_routes.cpp'), "#include `"http_routes.h`"`n#include `"wechatagent_hook.h`"`nvoid RegisterRoutes(httplib::Server& server) { RegisterWeChatAgentRoutes(server); }`n", $encoding)
foreach ($name in @('wechatagent_hook.h','sticker_sender.h','voice_sender.h','file_sender.h','deferred_init.h','http_server.h')) {
    Copy-Item -LiteralPath (Join-Path $native $name) -Destination (Join-Path $build 'include') -Force
}
foreach ($name in @('wechatagent_hook.cpp','sticker_sender.cpp','sticker_trace.cpp','voice_sender.cpp','file_sender.cpp','deferred_init.cpp','http_server.cpp')) {
    Copy-Item -LiteralPath (Join-Path $native $name) -Destination (Join-Path $build 'src') -Force
}
$project = Join-Path $build 'x64_Version_dll.vcxproj'
Replace-Checked $project '<ClCompile Include="src\http_routes.cpp" />' '<ClCompile Include="src\http_routes.cpp" /><ClCompile Include="src\wechatagent_hook.cpp" /><ClCompile Include="src\sticker_sender.cpp" /><ClCompile Include="src\sticker_trace.cpp" /><ClCompile Include="src\file_sender.cpp" /><ClCompile Include="src\deferred_init.cpp" /><ClCompile Include="src\voice_sender.cpp" />'
Replace-Checked $project 'psapi.lib;gdiplus.lib;' 'version.lib;psapi.lib;gdiplus.lib;'
Replace-Checked $project '<PreprocessorDefinitions>' '<PreprocessorDefinitions>_DISABLE_CONSTEXPR_MUTEX_CONSTRUCTOR;'
if (-not $MsBuild) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (Test-Path -LiteralPath $vswhere) {
        $MsBuild = (& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -find 'MSBuild\**\Bin\MSBuild.exe' | Select-Object -First 1)
    }
}
if (-not $MsBuild) { throw 'MSBuild not found. Install Visual Studio C++ Build Tools.' }
Push-Location $build
try {
    & $MsBuild $project /m /t:Build /p:Configuration=Release /p:Platform=x64 /p:PlatformToolset=v143 /v:minimal /nologo
    if ($LASTEXITCODE -ne 0) { throw 'Native Hook build failed.' }
} finally { Pop-Location }
$dll = Join-Path $build 'x64\Release\version.dll'
if (-not (Test-Path -LiteralPath $dll)) { throw 'version.dll was not produced.' }
Copy-Item -LiteralPath $dll -Destination (Join-Path $output 'version.dll') -Force
$sha = (Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash.ToLowerInvariant()
@{ targetVersion='4.1.10.27'; voiceRoute='/SendVoiceMsg'; sha256=$sha } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output 'build.json') -Encoding UTF8
Write-Output ('Compiled: ' + (Join-Path $output 'version.dll') + ' sha256=' + $sha)
