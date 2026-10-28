[CmdletBinding()]
param(
    [string]$PythonPath = '',
    [switch]$CpuOnly,
    [switch]$SkipTorch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $TaskVenv = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $TaskVenv -PathType Leaf) {
        $PythonPath = $TaskVenv
    } else {
        $PythonPath = (Get-Command python -CommandType Application -ErrorAction Stop).Source
    }
}
$TaskPython = (Resolve-Path -LiteralPath $PythonPath).Path
function Invoke-DemoPython {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    & $TaskPython @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python command failed (exit $LASTEXITCODE). See the error above." }
}

Push-Location -LiteralPath $PSScriptRoot
try {
    Write-Host "Python: $TaskPython"
    Invoke-DemoPython -Arguments @('-B', '-c', 'import sys,struct; assert sys.version_info[:2]==(3,10), "Use Python 3.10"; assert struct.calcsize("P")==8, "64-bit Python required"; print(sys.version)')
    if (-not $SkipTorch) {
        $TaskIndex = 'https://download.pytorch.org/whl/cu128'
        if ($CpuOnly) { $TaskIndex = 'https://download.pytorch.org/whl/cpu' }
        Invoke-DemoPython -Arguments @('-m','pip','install','--no-cache-dir','torch==2.7.1','torchvision==0.22.1','--index-url',$TaskIndex)
    }
    Invoke-DemoPython -Arguments @('-m','pip','install','--no-cache-dir','-r',(Join-Path $PSScriptRoot 'requirements.txt'))
    Invoke-DemoPython -Arguments @('-B','app.py','--verify-upstream')
    if ($CpuOnly) {
        Invoke-DemoPython -Arguments @('-B','-c','import torch,torchvision; print("PyTorch:",torch.__version__); print("CPU mode: saved results and bicubic are available; live SinSR needs CUDA.")')
    } else {
        Invoke-DemoPython -Arguments @('-B','-c','import torch; assert torch.cuda.is_available(), "CUDA unavailable: check the NVIDIA driver or use -CpuOnly for replay"; print(torch.__version__,torch.cuda.get_device_name(0)); print((torch.ones(4,device="cuda")*2).cpu().tolist()); torch.cuda.synchronize()')
    }
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'python_path.local.txt'), ($TaskPython + "`n"), [Text.UTF8Encoding]::new($false))
    Write-Host 'Setup completed. Run python app.py, or double-click start_demo.bat.'
    Write-Host 'GPU users: python app.py --prepare downloads weights and regenerates saved examples.'
}
finally { Pop-Location }
