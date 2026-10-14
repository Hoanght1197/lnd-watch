# run_local.ps1 — phần thu dữ liệu chạy ở MÁY ANH HOÀNG (Etsy + FB Ad Library cần Chrome 9230 thật).
# Windows PowerShell 5.1. Task Scheduler gọi lúc 6:05 sáng (lệnh cài: xem collect\README.md).
#   1. Bật Chrome 9230 (profile chrome-cdp-chutan) nếu chưa chạy, chờ tối đa 30 giây.
#   2. Etsy:  python ..\4-SPY\spy_etsy.py watch --shops etsy_watch.txt   (ghi vào 4-SPY\data\etsy)
#   3. Ads:   python collect\run_ads.py                                  (ghi vào data\ads)
#   4. Chép snapshot Etsy 4-SPY\data\etsy\<shop>\<ngày>.json -> data\etsy\<shop>\
#   5. build_summary.py + check_schema.py
#   6. git: commit data -> pull --rebase -> build lại (gộp dữ liệu Actions) -> push
# Log: collect\logs\<ngày>.log. Không giết tiến trình nào, không đóng Chrome (cdp.py tự đóng tab của nó).
# File lưu UTF-8 có BOM để PowerShell 5.1 đọc đúng tiếng Việt.

$ErrorActionPreference = 'Continue'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Here
$Spy = Join-Path (Split-Path -Parent $Root) '4-SPY'
$Date = (Get-Date).ToString('yyyy-MM-dd')
$LogDir = Join-Path $Here 'logs'
New-Item -ItemType Directory -Force $LogDir | Out-Null
$Log = Join-Path $LogDir "$Date.log"
$env:PYTHONIOENCODING = 'utf-8'
$ChromeCmd = 'F:\APP BY HOANG\app-hub\scripts\chrome_debug.py'

function Write-Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date).ToString('HH:mm:ss'), $msg
    Add-Content -Path $Log -Value $line -Encoding UTF8
    Write-Host $line
}

# chạy lệnh qua cmd để log giữ đúng UTF-8 (redirect của PS 5.1 ghi UTF-16 và bọc stderr thành lỗi)
function Invoke-Logged([string]$cmdline) {
    Write-Log "> $cmdline"
    cmd /c "$cmdline >> `"$Log`" 2>&1"
    $code = $LASTEXITCODE
    Write-Log "  (mã thoát $code)"
    return $code
}

function Test-Chrome {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:9230/json/version' -TimeoutSec 3
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

Write-Log "=== run_local $Date (Root=$Root, Spy=$Spy) ==="

# ---- 1. Chrome 9230
$chromeOk = Test-Chrome
if (-not $chromeOk) {
    Write-Log "Chrome 9230 chưa chạy -> mở bằng chrome_debug.py"
    Start-Process -FilePath 'python' -ArgumentList @("`"$ChromeCmd`"", '9230', 'chrome-cdp-chutan') -WindowStyle Hidden
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Chrome) { $chromeOk = $true; break }
    }
}
if ($chromeOk) { Write-Log "Chrome 9230 OK" } else { Write-Log "! Chrome 9230 không lên sau 30s -> bỏ Etsy + ads, vẫn build + push" }

# ---- 2 + 3. Etsy + ads (lỗi phần nào thì ghi log, chạy tiếp phần sau)
if ($chromeOk) {
    $etsyList = Join-Path $Root 'etsy_watch.txt'
    $null = Invoke-Logged "python `"$Spy\spy_etsy.py`" watch --shops `"$etsyList`" --date $Date --max-pages 80"
    $null = Invoke-Logged "python `"$Here\run_ads.py`" --date $Date"
}

# ---- 4. chép snapshot Etsy sang data\etsy (file ngày hôm nay luôn ghi đè; ngày cũ chưa có thì chép bù)
$shops = Get-Content (Join-Path $Root 'etsy_watch.txt') -Encoding UTF8 | ForEach-Object { ($_ -split '#')[0].Trim() } | Where-Object { $_ }
foreach ($shop in $shops) {
    $src = Join-Path $Spy "data\etsy\$shop"
    if (-not (Test-Path $src)) { Write-Log "  Etsy ${shop}: chưa có snapshot trong 4-SPY"; continue }
    $dst = Join-Path $Root "data\etsy\$shop"
    New-Item -ItemType Directory -Force $dst | Out-Null
    $n = 0
    Get-ChildItem $src -Filter '????-??-??.json' | ForEach-Object {
        $target = Join-Path $dst $_.Name
        if (($_.BaseName -eq $Date) -or (-not (Test-Path $target))) {
            Copy-Item $_.FullName $target -Force
            $n++
        }
    }
    Write-Log "  Etsy ${shop}: chép $n file"
}

# ---- 5. build + kiểm schema
$null = Invoke-Logged "python `"$Here\build_summary.py`""
$schema = Invoke-Logged "python `"$Here\check_schema.py`""
if ($schema -ne 0) {
    Write-Log "! check_schema lỗi -> KHÔNG commit/push, xem log"
    exit 1
}

# ---- 6. git (commit -> pull --rebase -> build lại để gộp dữ liệu Shopify của Actions -> push)
Set-Location $Root
$null = Invoke-Logged "git add data"
cmd /c "git diff --cached --quiet"
if ($LASTEXITCODE -ne 0) {
    $null = Invoke-Logged "git commit -m `"data: $Date local`""
} else {
    Write-Log "Không có thay đổi để commit"
}
# -X theirs (khi rebase = giữ bản local) cho file tổng hợp bị xung đột; ngay sau đó build lại nên file tổng hợp luôn đúng
$pull = Invoke-Logged "git pull --rebase -X theirs"
if ($pull -ne 0) {
    Write-Log "! git pull --rebase lỗi -> huỷ rebase, không push (xem log)"
    $null = Invoke-Logged "git rebase --abort"
    exit 1
}
$null = Invoke-Logged "python `"$Here\build_summary.py`""
$schema = Invoke-Logged "python `"$Here\check_schema.py`""
if ($schema -ne 0) { Write-Log "! check_schema lỗi sau khi gộp -> không push"; exit 1 }
$null = Invoke-Logged "git add data"
cmd /c "git diff --cached --quiet"
if ($LASTEXITCODE -ne 0) {
    $null = Invoke-Logged "git commit -m `"data: $Date local (build lại sau pull)`""
}
$push = Invoke-Logged "git push"
if ($push -ne 0) { Write-Log "! git push lỗi"; exit 1 }
Write-Log "=== xong ==="
exit 0
